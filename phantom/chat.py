"""The interactive conversation session.

Conversation history lives only in memory for the length of the session. The
archive stores explicit memories and mood, never full transcripts.
"""

from __future__ import annotations

from typing import Callable

from core.brain import Brain, BrainError, StreamChunk, StreamInterruptedError
from core.memory import MemoryStore, PhantomMemoryError
from core.personality import (
    MemoryNote,
    MoodEngine,
    MoodEvent,
    build_system_prompt,
    format_mood,
)

from phantom.config import Settings
from phantom.render import Renderer, sanitize_output
from phantom.storage import load_mood, record_mood
from phantom.views import format_timestamp, memory_table, render_status

MAX_TURNS = 12
MAX_HISTORY_CHARS = 6000

_HELP_ROWS: tuple[tuple[str, str], ...] = (
    ("/help", "Show this list."),
    ("/remember TEXT", "Archive an explicit memory."),
    ("/memories", "List archived memories."),
    ("/forget ID", "Delete one memory after confirmation."),
    ("/status", "Check the model and the archive."),
    ("/mood", "Show PHANTOM's recorded internal state."),
    ("/clear", "Forget the conversation in this window only."),
    ("/exit", "Close the session (also /quit, /bye)."),
)

_EXIT_COMMANDS = {"exit", "quit", "bye"}


class ChatSession:
    """A bounded, streamed conversation over the local model."""

    def __init__(
        self,
        *,
        brain: Brain,
        store: MemoryStore,
        settings: Settings,
        renderer: Renderer,
        input_func: Callable[[str], str] = input,
    ) -> None:
        self.brain = brain
        self.store = store
        self.settings = settings
        self.renderer = renderer
        self.input_func = input_func
        self.history: list[dict[str, str]] = []
        self.mood = MoodEngine(load_mood(store))

    # -- session lifecycle ---------------------------------------------

    def run(self) -> int:
        """Run the read/stream loop until the user leaves."""

        self._record(MoodEvent.SESSION_START)
        self.renderer.sigil(animate=self.settings.animation)
        self.renderer.panel(
            "The cursor waits.\n"
            "Ask a question, or use /help. Nothing you type is persisted "
            "unless you explicitly archive it with /remember.",
            title="PHANTOM",
        )
        self.renderer.note(
            f"model {self.settings.brain.model} via {self.settings.brain.host} "
            "- /exit closes the session"
        )

        while True:
            try:
                raw = self.input_func("you> ")
            except (EOFError, KeyboardInterrupt):
                self.renderer.print()
                self.renderer.note("The connection thins. The transcript was not saved.")
                break

            text = raw.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self._handle_command(text):
                    break
                continue
            self._respond(text)

        self._record(MoodEvent.EXORCISE)
        self._closing_note()
        self.renderer.rule("until next time")
        return 0

    def _closing_note(self) -> None:
        try:
            count = self.store.count_memories()
        except PhantomMemoryError:
            count = None
        if count is None:
            self.renderer.note("Session closed. The archive could not be read.")
        else:
            self.renderer.note(
                f"Session closed. {count} "
                f"{'memory remains' if count == 1 else 'memories remain'} on disk."
            )

    # -- model turns ----------------------------------------------------

    def _respond(self, user_text: str) -> None:
        notes = self._relevant_notes(user_text)
        system = build_system_prompt(self.mood.state, notes)
        messages: list[dict[str, str]] = [
            *self.history,
            {"role": "user", "content": user_text},
        ]

        self.renderer.begin_reply()
        parts: list[str] = []
        final_chunk: StreamChunk | None = None
        try:
            for chunk in self.brain.stream_chat(messages, system=system):
                final_chunk = chunk
                if chunk.content:
                    safe = sanitize_output(chunk.content)
                    if safe:
                        parts.append(safe)
                        self.renderer.stream_chunk(safe)
        except KeyboardInterrupt:
            self.renderer.end_reply()
            self.renderer.warning(
                "Interrupted. This answer was not added to the conversation."
            )
            return
        except StreamInterruptedError as exc:
            self.renderer.end_reply()
            self.renderer.error(str(exc), title="Stream interrupted")
            self._record(MoodEvent.OLLAMA_ERROR, detail=str(exc))
            return
        except BrainError as exc:
            self.renderer.end_reply()
            self.renderer.error(str(exc), title="Model error")
            self._record(MoodEvent.OLLAMA_ERROR, detail=str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive boundary
            self.renderer.end_reply()
            self.renderer.error(
                "The model returned an unusable response.",
                hint=f"{exc}. Run `ollama list` and try again.",
            )
            return

        self.renderer.end_reply()
        answer = "".join(parts).strip()
        if not answer:
            self.renderer.warning(
                "The model produced no text. The turn was not recorded."
            )
            return

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": answer})
        self._trim_history()
        self._record(MoodEvent.CHAT_TURN)
        self._report_stream_metrics(final_chunk)

    def _report_stream_metrics(self, final_chunk: StreamChunk | None) -> None:
        """Show only metrics Ollama actually reported for this stream."""

        if final_chunk is None:
            return
        details: list[str] = []
        if final_chunk.eval_count:
            details.append(f"{final_chunk.eval_count} tokens")
        rate = final_chunk.tokens_per_second
        if rate is not None:
            details.append(f"{rate:.1f} tok/s")
        if details:
            self.renderer.info(
                f"{self.settings.brain.model} - " + " - ".join(details)
            )

    def _relevant_notes(self, user_text: str) -> list[MemoryNote]:
        try:
            records = self.store.search_memories(user_text)
        except PhantomMemoryError as exc:
            self.renderer.warning(f"Memories could not be retrieved: {exc}")
            return []
        return [
            MemoryNote(record.id, record.content, record.created_at)
            for record in records
        ]

    def _trim_history(self) -> None:
        while len(self.history) > MAX_TURNS * 2:
            del self.history[:2]
        while (
            sum(len(item["content"]) for item in self.history) > MAX_HISTORY_CHARS
            and len(self.history) > 2
        ):
            del self.history[:2]

    # -- slash commands -------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Handle one slash command. Return True when the session should end."""

        name, _, argument = text[1:].partition(" ")
        command = name.strip().lower()
        argument = argument.strip()

        if command in _EXIT_COMMANDS:
            return True
        if command == "help":
            self._show_help()
        elif command == "remember":
            self._remember(argument)
        elif command == "memories":
            self._show_memories()
        elif command == "forget":
            self._forget(argument)
        elif command == "status":
            self._show_status()
        elif command == "mood":
            self._show_mood()
        elif command == "clear":
            self.history.clear()
            self.renderer.ok("Conversation history cleared. Memories were not touched.")
        else:
            self.renderer.warning(
                f"Unknown command /{command}. Use /help to see the available commands."
            )
        return False

    def _show_help(self) -> None:
        table = self.renderer.table("Session commands", ["Command", "Effect"])
        for command, effect in _HELP_ROWS:
            table.add_row(command, effect)
        self.renderer.print(table)

    def _remember(self, argument: str) -> None:
        if not argument:
            self.renderer.warning("Usage: /remember TEXT")
            return
        try:
            record = self.store.remember(argument)
        except PhantomMemoryError as exc:
            self.renderer.error(str(exc))
            return
        self._record(MoodEvent.MEMORY_SAVED)
        self.renderer.ok(
            f"Archived as {record.short_id} at {format_timestamp(record.created_at)}."
        )
        self.renderer.panel(record.content, title="Memory archived")

    def _show_memories(self) -> None:
        try:
            records = self.store.list_memories()
        except PhantomMemoryError as exc:
            self.renderer.error(str(exc))
            return
        if not records:
            self.renderer.note("The archive is empty. Use /remember TEXT to add one.")
            return
        self.renderer.print(memory_table(self.renderer, records))

    def _forget(self, argument: str) -> None:
        if not argument:
            self.renderer.warning("Usage: /forget ID")
            return
        try:
            record = self.store.get_memory(argument)
        except PhantomMemoryError as exc:
            self.renderer.error(str(exc))
            return
        self.renderer.panel(
            record.content,
            title=f"Memory {record.short_id}",
            subtitle=f"recorded {record.created_at}",
        )
        try:
            answer = self.input_func("Delete this memory? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            self.renderer.print()
            self.renderer.note("No confirmation received. Nothing was deleted.")
            return
        if answer.strip().lower() not in {"y", "yes"}:
            self.renderer.note("Nothing was deleted.")
            return
        try:
            removed = self.store.forget(record.id)
        except PhantomMemoryError as exc:
            self.renderer.error(str(exc))
            return
        self._record(MoodEvent.MEMORY_FORGOTTEN)
        self.renderer.ok(f"Memory {removed.short_id} was released.")

    def _show_status(self) -> None:
        status = self.brain.status()
        health = self.store.health()
        render_status(self.renderer, self.settings, status, health, self.mood.state)

    def _show_mood(self) -> None:
        self.renderer.panel(
            f"{format_mood(self.mood.state).replace('·', '|')}\n\n"
            + (
                "\n".join(f"- {item}" for item in self.mood.state.evidence)
                if self.mood.state.evidence
                else "- no grounded events recorded yet"
            ),
            title="Internal state",
            subtitle="recorded events only",
        )

    # -- mood -----------------------------------------------------------

    def _record(self, event: MoodEvent, *, detail: str | None = None) -> None:
        record_mood(
            self.store,
            self.mood,
            event,
            detail=detail,
            renderer=self.renderer,
        )


__all__ = ["ChatSession", "MAX_HISTORY_CHARS", "MAX_TURNS"]
