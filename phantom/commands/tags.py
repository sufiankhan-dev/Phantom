"""``tags`` - list every tag in the archive with its memory count."""

from __future__ import annotations

import json
from typing import Any

from phantom.context import CommandContext
from phantom.storage import open_store
from phantom.views import plural


def run(ctx: CommandContext, args: Any) -> int:
    with open_store(ctx.settings) as store:
        tags = store.list_tags()
        total = store.count_memories()

    renderer = ctx.renderer
    if getattr(args, "json", False):
        payload = {
            "total_tags": len(tags),
            "total_memories": total,
            "tags": [item.as_dict() for item in tags],
        }
        renderer.write_raw(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not tags:
        renderer.panel(
            "No tags have been attached yet.\n"
            'Try: phantom remember "TEXT" --tag python',
            title="No tags",
            subtitle="the archive is unchanged",
        )
        return 0

    renderer.section(
        "Tags",
        detail=f"{plural(len(tags), 'tag')} across "
        f"{plural(total, 'memory', 'memories')}",
    )
    table = renderer.table(None, ["Tag", "Memories"])
    table.columns[1].justify = "right"
    for item in tags:
        table.add_row(f"#{item.tag}", str(item.count))
    renderer.print(table)
    renderer.note("Filters: phantom memories --tag TAG, phantom search QUERY --tag TAG")
    return 0


__all__ = ["run"]
