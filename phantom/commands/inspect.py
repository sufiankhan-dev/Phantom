"""``inspect`` - command interface only.

The scanning engine is intentionally not implemented in this build. The
command validates the supplied path and says so plainly instead of inventing
findings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from phantom.context import CommandContext
from phantom.errors import InspectionError, UsageError
from phantom.render import sanitize_output


def run(ctx: CommandContext, args: Any) -> int:
    renderer = ctx.renderer
    raw = str(args.path).strip()
    if not raw:
        raise UsageError(
            "A path is required.",
            hint="Example: python -m phantom.main inspect .",
        )

    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise UsageError(
            f"Path not found: {raw}",
            hint="Pass a file or directory that exists on this machine.",
        ) from exc
    except OSError as exc:
        raise UsageError(
            f"Path could not be resolved: {raw}",
            hint=str(exc),
        ) from exc

    if not resolved.exists():
        raise UsageError(f"Path not found: {raw}")

    kind = "directory" if resolved.is_dir() else "file"
    renderer.note(f"Resolved: {sanitize_output(str(resolved))} ({kind})")
    raise InspectionError(
        "The inspection engine is not implemented in this build. "
        "No files were read and nothing was modified.",
        hint=(
            "This command will report grounded findings with file paths and "
            "line numbers once the scanner is added."
        ),
    )
