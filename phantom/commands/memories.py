"""``memories`` - list archived explicit memories."""

from __future__ import annotations

from typing import Any

from phantom.context import CommandContext
from phantom.storage import open_store
from phantom.views import memory_table, plural


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
            title="Empty archive",
            subtitle="nothing has been stored yet",
        )
        return 0

    renderer.section("Memory archive", detail="newest first")
    renderer.print(memory_table(renderer, records))
    shown = len(records)
    if limit is not None and shown < total:
        renderer.note(f"Showing {shown} of {total} memories, newest first.")
    else:
        renderer.note(
            f"{plural(total, 'memory', 'memories')}, newest first."
        )
    return 0
