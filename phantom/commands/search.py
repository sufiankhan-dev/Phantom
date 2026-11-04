"""``search`` - deterministic keyword search over stored memories.

No model is contacted. The scoring lives in :meth:`core.memory.MemoryStore.
search_memories` and ties are broken by recency, so the same archive always
produces the same ranking.
"""

from __future__ import annotations

import json
from typing import Any

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.storage import open_store
from phantom.views import memory_table, plural


def run(ctx: CommandContext, args: Any) -> int:
    query = " ".join(str(part) for part in (getattr(args, "query", ()) or ())).strip()
    if not query:
        raise UsageError(
            "Search text is required.",
            hint='Example: phantom search "test framework"',
        )

    limit = getattr(args, "limit", None)
    with open_store(ctx.settings) as store:
        records = store.search_memories(query, limit=limit or 5)
        total = store.count_memories()

    renderer = ctx.renderer
    if getattr(args, "json", False):
        payload = {
            "query": query,
            "limit": limit or 5,
            "total_memories": total,
            "results": [record.as_dict() for record in records],
        }
        renderer.write_raw(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if not records:
        renderer.panel(
            f'No stored memory matched "{query}".\n'
            f"The archive holds {plural(total, 'memory', 'memories')}.",
            title="No matches",
            subtitle="deterministic keyword search",
        )
        renderer.note("No model was contacted.")
        return 0

    renderer.section(
        "Memory search",
        detail=f'"{query}" - deterministic keyword match, newest wins ties',
    )
    renderer.print(memory_table(renderer, records))
    renderer.note(
        f"{len(records)} of {plural(total, 'memory', 'memories')} "
        "shown. No model was contacted."
    )
    return 0


__all__ = ["run"]
