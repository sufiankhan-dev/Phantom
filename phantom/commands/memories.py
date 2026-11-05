"""``memories`` - list archived explicit memories, optionally by tag."""

from __future__ import annotations

import json
from typing import Any

from core.memory import normalize_tag

from phantom.context import CommandContext
from phantom.storage import open_store
from phantom.views import memory_table, plural


def run(ctx: CommandContext, args: Any) -> int:
    limit = getattr(args, "limit", None)
    raw_tag = getattr(args, "tag", None)
    tag = normalize_tag(raw_tag) if raw_tag is not None else None

    with open_store(ctx.settings) as store:
        records = store.list_memories(limit=limit, tag=tag)
        total = store.count_memories(tag=tag)
        archive_total = store.count_memories()

    renderer = ctx.renderer
    if getattr(args, "json", False):
        payload = {
            "tag": tag,
            "total_memories": total,
            "archive_total": archive_total,
            "results": [record.as_dict() for record in records],
        }
        renderer.write_raw(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    scope = f"tagged #{tag}" if tag else "newest first"
    if not records:
        if tag:
            renderer.panel(
                f'No stored memory carries the tag "#{tag}".\n'
                f"The archive holds {plural(archive_total, 'memory', 'memories')}.",
                title="No tagged memories",
                subtitle="nothing was changed",
            )
            renderer.note("Use `phantom tag ID TAG` to attach a tag.")
        else:
            renderer.panel(
                "The archive is empty.\n"
                'Use: phantom remember "TEXT"',
                title="Empty archive",
                subtitle="nothing has been stored yet",
            )
        return 0

    renderer.section("Memory archive", detail=f"user supplied - {scope}")
    renderer.print(memory_table(renderer, records))
    shown = len(records)
    if limit is not None and shown < total:
        renderer.note(f"Showing {shown} of {total} memories, {scope}.")
    elif tag:
        renderer.note(
            f"{plural(total, 'memory', 'memories')} tagged #{tag}, "
            f"of {plural(archive_total, 'memory', 'memories')} in the archive."
        )
    else:
        renderer.note(f"{plural(total, 'memory', 'memories')}, newest first.")
    return 0
