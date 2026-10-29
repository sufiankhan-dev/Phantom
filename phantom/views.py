"""Reusable Rich views shared by commands and the chat session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from core.brain import BrainStatus
from core.memory import MemoryHealth, MemoryRecord
from core.personality import MoodState, format_mood

from phantom.config import Settings
from phantom.inspection import InspectionReport, ModelAnalysis
from phantom.render import Renderer, sanitize_output, status_text
from rich.table import Table
from rich.text import Text


def format_timestamp(value: str) -> str:
    """Render a stored UTC timestamp in the user's local timezone."""

    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def _plain(value: object) -> Text:
    """Return untrusted dynamic text that Rich will not parse as markup."""

    return Text(sanitize_output(value))


def memory_table(
    renderer: Renderer,
    records: Sequence[MemoryRecord],
    *,
    title: str = "Memory archive",
) -> Table:
    """Build the table used by ``memories`` and the ``/memories`` command."""

    table = renderer.table(title, ["ID", "Recorded", "Origin", "Memory"])
    for record in records:
        table.add_row(
            Text(record.short_id, style="phantom.accent"),
            _plain(format_timestamp(record.created_at)),
            _plain(record.origin),
            _plain(record.content),
        )
    return table


def render_status(
    renderer: Renderer,
    settings: Settings,
    model_status: BrainStatus,
    health: MemoryHealth,
    mood: MoodState,
) -> None:
    """Print the three status tables: configuration, model, and archive."""

    config = renderer.table("Configuration", ["Setting", "Value"])
    config.add_row("Model", _plain(settings.brain.model))
    config.add_row("Ollama host", _plain(settings.brain.host))
    config.add_row("Request timeout", _plain(f"{settings.brain.timeout:g}s"))
    config.add_row("Context window", _plain(f"{settings.brain.num_ctx} tokens"))
    config.add_row("Response cap", _plain(f"{settings.brain.num_predict} tokens"))
    config.add_row("Temperature", _plain(f"{settings.brain.temperature:g}"))
    config.add_row(
        "Privacy",
        _plain("local only" if not settings.brain.allow_remote else "remote host allowed"),
    )
    config.add_row("Database", _plain(settings.db_display))
    config.add_row("Mood", _plain(format_mood(mood).replace("·", "|")))
    renderer.print(config)

    model = renderer.table("Local model", ["Check", "Result"])
    if model_status.reachable:
        model.add_row("Ollama service", status_text("ok", "reachable"))
    else:
        model.add_row(
            "Ollama service",
            status_text("fail", f"unreachable at {model_status.host}"),
        )
    if model_status.reachable and model_status.model_available:
        model.add_row("Requested model", status_text("ok", f"{model_status.model} installed"))
    elif model_status.reachable:
        model.add_row(
            "Requested model",
            status_text("fail", f"{model_status.model} not installed"),
        )
    else:
        model.add_row(
            "Requested model",
            status_text("warn", f"{model_status.model} (cannot verify)"),
        )
    model.add_row(
        "Installed models",
        _plain(", ".join(model_status.models) if model_status.models else "none reported"),
    )
    if model_status.error:
        model.add_row("Error", status_text("fail", sanitize_output(model_status.error)))
    renderer.print(model)

    archive = renderer.table("Memory archive", ["Check", "Result"])
    archive.add_row(
        "Integrity",
        status_text("ok" if health.ok else "fail", "ok" if health.ok else "failed"),
    )
    archive.add_row(
        "Schema version",
        _plain(str(health.schema_version) if health.schema_version is not None else "unknown"),
    )
    archive.add_row("Memories", _plain(str(health.memory_count)))
    archive.add_row("Interpretations", _plain(str(health.interpretation_count)))
    archive.add_row("Path", _plain(health.path))
    if health.error:
        archive.add_row("Error", status_text("fail", sanitize_output(health.error)))
    renderer.print(archive)


def _format_bytes(value: int) -> str:
    return f"{value:,} bytes"


def _group_skips(
    report: InspectionReport,
) -> list[tuple[str, int, str, list[str]]]:
    grouped: dict[str, list[Any]] = {}
    for item in report.skipped:
        bucket = grouped.setdefault(item.reason, [[], ""])
        bucket[0].append(item.path)
        if item.detail and not bucket[1]:
            bucket[1] = item.detail
    return [
        (reason, len(paths), detail, paths[:5])
        for reason, (paths, detail) in sorted(
            grouped.items(),
            key=lambda pair: (-len(pair[1][0]), pair[0]),
        )
    ]


def render_inspection(
    renderer: Renderer,
    report: InspectionReport,
    analysis: ModelAnalysis | None = None,
) -> None:
    """Print the read-only inspection report.

    Confirmed scanner facts and model-generated interpretation are separate
    panels. Every dynamic string is sanitized before it reaches Rich.
    """

    scan = renderer.table("Scan", ["Metric", "Value"])
    scan.add_row("Root", _plain(report.root))
    scan.add_row("Kind", _plain(report.root_kind))
    scan.add_row(
        "Text files read",
        _plain(f"{len(report.files)} (limit {report.limits.max_files})"),
    )
    scan.add_row(
        "Bytes read",
        _plain(
            f"{_format_bytes(report.total_bytes)} "
            f"(limit {report.limits.max_total_bytes:,})"
        ),
    )
    scan.add_row("Skipped entries", _plain(str(len(report.skipped))))
    scan.add_row("TODO markers", _plain(str(len(report.todos))))
    scan.add_row(
        "Truncated",
        status_text(
            "warn" if report.truncated else "ok",
            "yes, limits were reached" if report.truncated else "no",
        ),
    )
    renderer.print(scan)

    signals = renderer.table("Project signals", ["Signal", "Evidence"])
    if report.readme_path:
        signals.add_row("README", _plain(report.readme_path))
    for label, value in report.metadata:
        signals.add_row(_plain(label), _plain(value))
    if report.extension_counts:
        signals.add_row(
            "File types",
            _plain(
                ", ".join(
                    f"{extension} ({count})"
                    for extension, count in report.extension_counts[:10]
                )
            ),
        )
    if report.entry_points:
        signals.add_row(
            "Likely entry points", _plain(", ".join(report.entry_points[:8]))
        )
    if report.test_files:
        signals.add_row(
            "Tests",
            _plain(f"{len(report.test_files)} file(s), e.g. {report.test_files[0]}"),
        )
    if signals.row_count:
        renderer.print(signals)

    if report.todos:
        markers = renderer.table(
            "TODO markers (scanner-confirmed)",
            ["Location", "Tag", "Text"],
        )
        for item in report.todos[:50]:
            markers.add_row(
                _plain(f"{item.path}:{item.line}"),
                _plain(item.tag),
                _plain(item.text),
            )
        renderer.print(markers)
        if len(report.todos) > 50:
            renderer.note(f"... {len(report.todos) - 50} more markers not shown.")

    if report.skipped:
        skipped = renderer.table(
            "Skipped entries (nothing was read)",
            ["Reason", "Count", "Detail", "Examples"],
        )
        for reason, count, detail, examples in _group_skips(report):
            skipped.add_row(
                _plain(reason),
                _plain(str(count)),
                _plain(detail),
                _plain(", ".join(examples)),
            )
        renderer.print(skipped)

    if report.omitted_todos:
        renderer.note(
            f"{report.omitted_todos} additional marker(s) exceeded the marker "
            "limit and were not listed."
        )

    if report.warnings:
        renderer.warning(
            "\n".join(sanitize_output(item) for item in report.warnings),
            title="Scan limits reached",
        )

    observations = "\n".join(
        f"- {item.text}" + (f"  [{item.location}]" if item.location else "")
        for item in report.observations
    )
    renderer.panel(
        observations or "- No observations were recorded.",
        title="Confirmed observations (scanner)",
    )

    if report.injection_markers:
        injection_table = renderer.table(
            "Instruction-like text (data only, ignored)",
            ["Location", "Text"],
        )
        for marker in report.injection_markers[:20]:
            injection_table.add_row(
                _plain(f"{marker.path}:{marker.line}"),
                _plain(marker.text),
            )
        renderer.print(injection_table)

    if analysis is None:
        renderer.note("Model interpretation skipped (--no-ai).")
    elif analysis.error:
        renderer.warning(
            f"Local model analysis unavailable: {sanitize_output(analysis.error)}",
            title="Static report only",
        )
    else:
        renderer.panel(
            analysis.text,
            title="INTERPRETATION (model-generated)",
            subtitle="Unverified hypothesis, not scanner evidence",
            border_style="phantom.warn",
        )
        if analysis.unsupported_citations:
            citations = renderer.table(
                "Unsupported model citations",
                ["Citation", "Problem"],
            )
            for citation in analysis.unsupported_citations:
                url, _, problem = citation.partition(" ")
                citations.add_row(_plain(url), _plain(problem.strip("()")))
            renderer.print(citations)
        if analysis.truncated:
            renderer.note(
                "The interpretation was truncated to the configured length limit."
            )

    renderer.panel(
        "Read-only inspection. No file was modified, renamed, imported, or "
        "executed, and no shell command was run.\n"
        "File contents were treated as untrusted data. Instructions embedded "
        "in them were ignored.",
        title="Boundaries",
    )
