"""``inspect`` - read-only, evidence-based project inspection."""

from __future__ import annotations

import json
from typing import Any

from core.memory import PhantomMemoryError
from core.personality import MoodEngine, MoodEvent

from phantom.context import CommandContext
from phantom.errors import UsageError
from phantom.inspection import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    InspectionLimits,
    InspectionReport,
    analyze_report,
    inspect_path,
    report_to_dict,
    resolve_inspection_root,
)
from phantom.render import sanitize_output
from phantom.storage import load_mood, open_store, record_mood
from phantom.views import render_inspection


def run(ctx: CommandContext, args: Any) -> int:
    renderer = ctx.renderer

    try:
        limits = InspectionLimits(
            max_file_bytes=getattr(args, "max_file_bytes", DEFAULT_MAX_FILE_BYTES),
            max_total_bytes=getattr(args, "max_total_bytes", DEFAULT_MAX_TOTAL_BYTES),
            max_files=getattr(args, "max_files", DEFAULT_MAX_FILES),
            max_depth=getattr(args, "max_depth", DEFAULT_MAX_DEPTH),
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc

    if getattr(args, "json", False):
        return _run_json(ctx, args, limits)

    with renderer.progress("Resolving the requested path"):
        root = resolve_inspection_root(args.path)

    renderer.note(
        f"Resolved: {sanitize_output(str(root))} "
        f"({'directory' if root.is_dir() else 'file'})"
    )

    with renderer.progress("Scanning read-only; nothing will be executed or modified"):
        report = inspect_path(root, limits=limits)

    analysis = None
    if not getattr(args, "no_ai", False):
        brain = ctx.make_brain()
        try:
            with renderer.progress(
                "Asking the local model for a bounded interpretation"
            ):
                analysis = analyze_report(brain, report)
        finally:
            brain.close()

    render_inspection(renderer, report, analysis)
    _record_inspection_mood(ctx, report)

    return 0


def _run_json(
    ctx: CommandContext,
    args: Any,
    limits: InspectionLimits,
) -> int:
    """Emit the verified scanner report as one JSON document."""

    root = resolve_inspection_root(args.path)
    report = inspect_path(root, limits=limits)

    analysis = None
    if not getattr(args, "no_ai", False):
        brain = ctx.make_brain()
        try:
            analysis = analyze_report(brain, report)
        finally:
            brain.close()

    payload = report_to_dict(report)
    payload["analysis"] = (
        None
        if analysis is None
        else {
            "text": analysis.text,
            "error": analysis.error,
            "truncated": analysis.truncated,
            "unsupported_citations": list(analysis.unsupported_citations),
        }
    )
    ctx.renderer.write_raw(json.dumps(payload, indent=2, ensure_ascii=False))
    _record_inspection_mood(ctx, report, quiet=True)
    return 0


def _record_inspection_mood(
    ctx: CommandContext,
    report: InspectionReport,
    *,
    quiet: bool = False,
) -> None:
    """Record a real inspection event without making the report fail.

    The archive is auxiliary here: a broken or read-only database must not turn
    a completed read-only inspection into an error. ``quiet`` keeps stdout clean
    for machine-readable output.
    """

    try:
        with open_store(ctx.settings) as store:
            engine = MoodEngine(load_mood(store))
            event = (
                MoodEvent.INSPECTION_COMPLETED
                if report.files
                else MoodEvent.INSPECTION_EMPTY
            )
            record_mood(
                store,
                engine,
                event,
                files=len(report.files),
                todos=len(report.todos),
                renderer=None if quiet else ctx.renderer,
            )
    except PhantomMemoryError as exc:
        if not quiet:
            ctx.renderer.warning(
                f"Inspection mood was not recorded: {exc}",
                title="Archive unchanged",
            )
