"""``memories`` - list archived explicit memories."""

from __future__ import annotations

from typing import Any

from phantom.context import CommandContext
from phantom.storage import open_store
from phantom.views import memory_table


def run(ctx: CommandContext, args: Any) -> int:
    limit = getattr(args, "limit", None)
    with open_store(ctx.settings) as store:
        records = store.list_memories(limit=limit)
        total = store.count_memories()

    renderer = ctx.renderer
    if not records:
        renderer.panel(
            "The archive is empty.\n"
            'Use: phantom remember "TEXT"',
            title="No memories",
        )
        return 0

    renderer.print(memory_table(renderer, records))
    shown = len(records)
    if limit is not None and shown < total:
        renderer.note(f"Showing {shown} of {total} memories, newest first.")
    else:
        renderer.note(
            f"{total} {'memory' if total == 1 else 'memories'}, newest first."
        )
    return 0
