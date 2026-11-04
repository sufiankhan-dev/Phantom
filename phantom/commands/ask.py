"""``ask`` - one grounded, streamed answer from the local model.

Two modes share the same local boundary:

* a plain question recalls relevant user-supplied memories and answers with
  PHANTOM's normal voice;
* ``--context PATH`` performs the same read-only scan as ``phantom inspect``
  and answers strictly from the scanner's verified facts and bounded excerpts.

No conversation is persisted. The archive is only read for memories and mood,
and mood is recorded as a real event after the answer completes.
"""

from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

from core.brain import ChatResult, StreamChunk
from core.memory import PhantomMemoryError
from core.personality import (
    MemoryNote,
    MoodEngine,
    MoodEvent,
    MoodState,
    build_system_prompt,
)

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.inspection import (
    GROUNDED_QUESTION_SYSTEM_PROMPT,
    InspectionReport,
    build_question_prompt,
    inspect_path,
    validate_citations,
)
from phantom.render import sanitize_output
from phantom.storage import load_mood, open_store, record_mood


def run(ctx: CommandContext, args: Any) -> int:
    renderer = ctx.renderer
    question = _question(args)
    json_output = bool(getattr(args, "json", False))
    context_path = getattr(args, "context", None)

    report: InspectionReport | None = None
    recall_error: str | None = None
    if context_path:
        scan = (
            contextlib.nullcontext()
            if json_output
            else renderer.progress(
                "Scanning the supplied path read-only; nothing will be executed"
            )
        )
        with scan:
            report = inspect_path(context_path)
        system = GROUNDED_QUESTION_SYSTEM_PROMPT
        message = build_question_prompt(report, question)
        notes: list[MemoryNote] = []
        if not json_output:
            renderer.note(
                f"Grounding the answer in {report.root_kind}: {report.root} "
                f"({len(report.files)} text file(s) read)"
            )
    else:
        mood, notes, recall_error = _recall(ctx, question)
        system = build_system_prompt(mood, notes)
        message = question
        if recall_error and not json_output:
            renderer.warning(
                "Relevant memories could not be read; answering without them.",
                title="Archive unavailable",
            )

    brain = ctx.make_brain()
    try:
        if json_output:
            result = brain.complete_chat(
                [{"role": "user", "content": message}],
                system=system,
            )
            return _emit_json(ctx, result, question, notes, report, recall_error)
        return _stream_answer(ctx, brain, message, system, report)
    finally:
        brain.close()


def _stream_answer(
    ctx: CommandContext,
    brain: Any,
    message: str,
    system: str,
    report: InspectionReport | None,
) -> int:
    renderer = ctx.renderer
    parts: list[str] = []
    final_chunk: StreamChunk | None = None

    renderer.begin_reply()
    try:
        for chunk in brain.stream_chat(
            [{"role": "user", "content": message}],
            system=system,
        ):
            final_chunk = chunk
            if not chunk.content:
                continue
            safe = sanitize_output(chunk.content)
            if safe:
                parts.append(safe)
                renderer.stream_chunk(safe)
    finally:
        renderer.end_reply()

    answer = "".join(parts).strip()
    if not answer:
        renderer.warning("The model returned no text. Nothing was displayed.")
        return 1

    _report_metrics(
        renderer,
        final_chunk,
        model=ctx.settings.brain.model,
    )

    if report is not None:
        _report_citations(renderer, answer, report)

    _record_turn(ctx, quiet=False)
    return 0


def _report_metrics(
    renderer: Any,
    final_chunk: StreamChunk | None,
    *,
    model: str,
) -> None:
    """Show only measurements the model actually reported."""

    if final_chunk is None:
        return
    details: list[str] = []
    if final_chunk.eval_count:
        details.append(f"{final_chunk.eval_count} tokens")
    rate = final_chunk.tokens_per_second
    if rate is not None:
        details.append(f"{rate:.1f} tok/s")
    if details:
        renderer.stats(f"{model} - " + " - ".join(details))


def _report_citations(renderer: Any, answer: str, report: InspectionReport) -> None:
    unsupported = validate_citations(answer, report)
    if not unsupported:
        return
    renderer.warning(
        "The model cited locations the scanner did not read or could not "
        "support:\n- " + "\n- ".join(sanitize_output(item) for item in unsupported),
        title="Unsupported model citations",
    )


def _emit_json(
    ctx: CommandContext,
    result: ChatResult,
    question: str,
    notes: list[MemoryNote],
    report: InspectionReport | None,
    recall_error: str | None,
) -> int:
    answer = sanitize_output(result.text).strip()
    payload: dict[str, Any] = {
        "question": question,
        "answer": answer,
        "model": ctx.settings.brain.model,
        "host": ctx.settings.brain.host,
        "grounding": (
            {"root": report.root, "root_kind": report.root_kind}
            if report is not None
            else None
        ),
        "memories_used": [note.memory_id for note in notes],
        "recall_error": recall_error,
        "unsupported_citations": (
            list(validate_citations(answer, report))
            if report is not None
            else []
        ),
        "metrics": {
            "eval_count": result.eval_count,
            "tokens_per_second": result.tokens_per_second,
        },
    }
    ctx.renderer.write_raw(json.dumps(payload, indent=2, ensure_ascii=False))
    _record_turn(ctx, quiet=True)
    if not answer:
        return 1
    return 0


def _recall(
    ctx: CommandContext,
    question: str,
) -> tuple[MoodState, list[MemoryNote], str | None]:
    """Read relevant memories and mood, or degrade to an empty context."""

    try:
        with open_store(ctx.settings) as store:
            mood = MoodEngine(load_mood(store)).state
            records = store.search_memories(question)
    except PhantomMemoryError as exc:
        return MoodState(), [], str(exc)
    return (
        mood,
        [
            MemoryNote(record.id, record.content, record.created_at)
            for record in records
        ],
        None,
    )


def _record_turn(ctx: CommandContext, *, quiet: bool) -> None:
    """Record one completed conversation turn as a real mood event."""

    try:
        with open_store(ctx.settings) as store:
            engine = MoodEngine(load_mood(store))
            record_mood(
                store,
                engine,
                MoodEvent.CHAT_TURN,
                renderer=None if quiet else ctx.renderer,
            )
    except PhantomMemoryError as exc:
        if not quiet:
            ctx.renderer.warning(
                f"The turn was answered, but mood was not recorded: {exc}",
                title="Archive unchanged",
            )


def _question(args: Any) -> str:
    parts = [str(part) for part in (getattr(args, "text", ()) or ())]
    text = " ".join(parts).strip()
    if text == "-":
        text = sys.stdin.read().strip()
    if not text:
        raise UsageError(
            "A question is required.",
            hint='Example: phantom ask "what should I fix first?"',
        )
    return text


__all__ = ["run"]
