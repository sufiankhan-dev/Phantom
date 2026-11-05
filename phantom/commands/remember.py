"""``remember`` - archive one explicit, user supplied memory."""

from __future__ import annotations

from typing import Any

from core.personality import MoodEngine, MoodEvent

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.storage import (
    load_mood,
    open_store,
    record_mood,
    split_tag_arguments,
)
from phantom.views import format_timestamp
from phantom.render import sanitize_output


def run(ctx: CommandContext, args: Any) -> int:
    text = str(args.text)
    if not text.strip():
        raise UsageError(
            "Memory text cannot be empty.",
            hint='Example: phantom remember "I prefer pytest."',
        )

    tags = split_tag_arguments(getattr(args, "tag", None))
    with open_store(ctx.settings) as store:
        record = store.remember(text, tags=tags)
        mood = MoodEngine(load_mood(store))
        record_mood(
            store,
            mood,
            MoodEvent.MEMORY_SAVED,
            detail=record.short_id,
            renderer=ctx.renderer,
        )
        total = store.count_memories()

    subtitle = f"user supplied - {format_timestamp(record.created_at)}"
    if record.tags:
        subtitle += " - " + " ".join(f"#{tag}" for tag in record.tags)
    ctx.renderer.panel(
        sanitize_output(record.content),
        title=f"Memory archived - {record.short_id}",
        subtitle=subtitle,
    )
    ctx.renderer.ok(
        f"Stored {total} {'memory' if total == 1 else 'memories'} in "
        f"{ctx.settings.db_display}."
    )
    ctx.renderer.note("Nothing left this machine.")
    return 0
