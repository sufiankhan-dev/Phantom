"""``forget`` - delete exactly one explicitly identified memory."""

from __future__ import annotations

from typing import Any

from core.personality import MoodEngine, MoodEvent

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.render import sanitize_output
from phantom.storage import load_mood, open_store, record_mood
from phantom.views import format_timestamp


def run(ctx: CommandContext, args: Any) -> int:
    memory_id = str(args.memory_id).strip()
    if not memory_id:
        raise UsageError(
            "A memory ID is required.",
            hint="Run `python -m phantom.main memories` to list identifiers.",
        )

    renderer = ctx.renderer
    with open_store(ctx.settings) as store:
        record = store.get_memory(memory_id)

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
