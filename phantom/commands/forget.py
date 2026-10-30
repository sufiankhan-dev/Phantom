"""``forget`` - delete exactly one explicitly identified memory."""

from __future__ import annotations

from typing import Any

from core.memory import MemoryRecord, MemoryStore
from core.personality import MoodEngine, MoodEvent

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.render import sanitize_output
from phantom.storage import load_mood, open_store, record_mood
from phantom.views import format_timestamp


def _select_memory(store: MemoryStore, selector: str) -> MemoryRecord:
    """Resolve a list number, full ID, or unique ID prefix.

    ``phantom memories`` numbers records newest first, so ``phantom forget 1``
    selects the same record the user just saw at the top of the list. The
    record is still shown and confirmed before it is deleted.
    """

    if selector.isdigit():
        position = int(selector)
        if position < 1:
            raise UsageError(
                "Memory numbers start at 1.",
                hint="Run `phantom memories` to see the numbered list.",
            )
        records = store.list_memories()
        if position > len(records):
            raise UsageError(
                f"There is no memory at position {position}.",
                hint=(
                    f"The archive holds {len(records)} "
                    f"{'memory' if len(records) == 1 else 'memories'}. "
                    "Run `phantom memories` to see the numbered list."
                ),
            )
        return records[position - 1]
    return store.get_memory(selector)


def run(ctx: CommandContext, args: Any) -> int:
    memory_id = str(args.memory_id).strip()
    if not memory_id:
        raise UsageError(
            "A memory ID is required.",
            hint="Run `phantom memories` to list identifiers.",
        )

    renderer = ctx.renderer
    with open_store(ctx.settings) as store:
        record = _select_memory(store, memory_id)

        renderer.panel(
            sanitize_output(record.content),
            title=f"Memory {record.short_id}",
            subtitle=(
                f"full id {record.id} - recorded "
                f"{format_timestamp(record.created_at)}"
            ),
            border_style="phantom.warn",
        )

        if not getattr(args, "yes", False):
            try:
                answer = ctx.input_func("Delete this memory permanently? [y/N] ")
            except EOFError as exc:
                raise UsageError(
                    "No confirmation was received; nothing was deleted.",
                    hint="Re-run with --yes in a non-interactive context.",
                ) from exc
            if answer.strip().lower() not in {"y", "yes"}:
                renderer.note("Nothing was deleted.")
                return 0

        removed = store.forget(record.id)
        mood = MoodEngine(load_mood(store))
        record_mood(
            store,
            mood,
            MoodEvent.MEMORY_FORGOTTEN,
            detail=removed.short_id,
            renderer=renderer,
        )
        remaining = store.count_memories()

    renderer.panel(
        sanitize_output(removed.content),
        title=f"Memory released - {removed.short_id}",
        subtitle="this was the only record removed",
    )
    renderer.ok(
        f"Deleted one memory. {remaining} "
        f"{'memory remains' if remaining == 1 else 'memories remain'}."
    )
    return 0
