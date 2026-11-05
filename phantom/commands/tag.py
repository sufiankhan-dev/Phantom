"""``tag`` - add or remove tags on one explicitly identified memory."""

from __future__ import annotations

from typing import Any

from core.memory import normalize_tags

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.render import sanitize_output
from phantom.storage import open_store, split_tag_arguments
from phantom.views import format_timestamp


def run(ctx: CommandContext, args: Any) -> int:
    selector = str(getattr(args, "memory_id", "")).strip()
    if not selector:
        raise UsageError(
            "A memory ID is required.",
            hint="Run `phantom memories` to list identifiers.",
        )

    requested = normalize_tags(
        split_tag_arguments(getattr(args, "tags", None))
    )
    if not requested:
        raise UsageError(
            "At least one tag is required.",
            hint="Example: phantom tag 1a2b3c4d python testing",
        )

    remove = bool(getattr(args, "remove", False))
    renderer = ctx.renderer
    with open_store(ctx.settings) as store:
        record = store.get_memory(selector)
        before = set(record.tags)
        wanted = set(requested)
        changed = (before & wanted) if remove else (wanted - before)

        if not changed:
            state = "already absent" if remove else "already present"
            renderer.note(
                f"No tag changes: {', '.join(f'#{tag}' for tag in sorted(wanted))} "
                f"{'is' if len(wanted) == 1 else 'are'} {state}. Nothing was written."
            )
            return 0

        updated = store.tag_memory(record.id, sorted(wanted), remove=remove)

    verb = "Removed" if remove else "Added"
    tag_list = " ".join(f"#{tag}" for tag in sorted(changed))
    subtitle = (
        "tags: " + " ".join(f"#{tag}" for tag in updated.tags)
        if updated.tags
        else "no tags remain"
    )
    renderer.panel(
        sanitize_output(updated.content),
        title=f"Memory {updated.short_id}",
        subtitle=f"{subtitle} - recorded {format_timestamp(updated.created_at)}",
    )
    renderer.ok(f"{verb} {len(changed)} tag(s): {tag_list}. No memory was deleted.")
    return 0


__all__ = ["run"]
