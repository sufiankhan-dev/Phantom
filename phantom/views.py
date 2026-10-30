"""Reusable Rich views shared by commands and the chat session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from core.brain import BrainStatus
from core.memory import MemoryHealth, MemoryRecord
from core.personality import MoodState, format_mood

from phantom.config import Settings
from phantom.inspection import InspectionReport, ModelAnalysis
from phantom.render import Renderer, badge, sanitize_output, status_text
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


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """Return ``count`` with its correct noun form."""

    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"


def _plain(value: object) -> Text:
    """Return untrusted dynamic text that Rich will not parse as markup."""

    return Text(sanitize_output(value))


def _separator(renderer: Renderer) -> str:
    """A middle dot on a styled terminal, a pipe everywhere else."""

    return "·" if renderer.styled else "|"


def _mood_line(renderer: Renderer, mood: MoodState) -> str:
    return format_mood(mood).replace("·", _separator(renderer))


def memory_table(
    renderer: Renderer,
    records: Sequence[MemoryRecord],
    *,
    title: str | None = None,
) -> Table:
    """Build the table used by ``memories`` and the ``/memories`` command."""

    table = renderer.table(
        title,
        ["#", "ID", "Origin", "Recorded", "Memory"],
    )
    table.columns[0].justify = "right"
    table.columns[1].no_wrap = True
    table.columns[2].no_wrap = True
    table.columns[3].no_wrap = True
    for position, record in enumerate(records, start=1):
        origin_style = (
            "phantom.accent" if record.origin == "user" else "phantom.warn"
        )
        table.add_row(
            Text(str(position), style="phantom.muted"),
            Text(record.short_id, style="phantom.accent"),
            badge(record.origin, origin_style),
            Text(format_timestamp(record.created_at), style="phantom.muted"),
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
    """Print the status dashboard: identity, configuration, model, archive."""

    ready = (
        model_status.reachable
        and model_status.model_available
        and health.ok
    )
    archive_state = "integrity ok" if health.ok else "integrity failed"
    model_state = (
        "model ready"
        if model_status.reachable and model_status.model_available
        else "model unavailable"
    )
    dot = _separator(renderer)
    summary = Text()
    summary.append(model_status.model, style="phantom.title")
    summary.append("  via  ", style="phantom.muted")
    summary.append(model_status.host, style="phantom.body")
    summary.append("\n", style="phantom.body")
    summary.append(plural(health.memory_count, "memory", "memories"), style="phantom.body")
    summary.append(f"  {dot}  archive ", style="phantom.muted")
    summary.append(
        f"v{health.schema_version}" if health.schema_version is not None else "unknown",
        style="phantom.body",
    )
    summary.append(f"  {dot}  ", style="phantom.muted")
    summary.append(mood.label, style="phantom.accent")
    summary.append("\n")
    summary.append(
        status_text("ok" if ready else "warn", f"{model_state}, {archive_state}"),
    )
    renderer.panel(
        summary,
        title="PHANTOM // status",
        subtitle="local only",
        border_style="phantom.border" if ready else "phantom.warn",
    )

    renderer.fields(
        "Configuration",
        [
            ("Model", settings.brain.model),
            ("Ollama host", settings.brain.host),
            ("Request timeout", f"{settings.brain.timeout:g}s"),
            ("Context window", f"{settings.brain.num_ctx} tokens"),
            ("Response cap", f"{settings.brain.num_predict} tokens"),
            ("Temperature", f"{settings.brain.temperature:g}"),
            (
                "Privacy",
                "local only"
                if not settings.brain.allow_remote
                else "remote host allowed",
            ),
            ("Database", settings.db_display),
            ("Mood", _mood_line(renderer, mood)),
        ],
    )

    model_rows: list[tuple[object, object]] = []
    if model_status.reachable:
        model_rows.append(("Ollama service", status_text("ok", "reachable")))
    else:
        model_rows.append(
            ("Ollama service", status_text("fail", f"unreachable at {model_status.host}"))
        )
    if model_status.reachable and model_status.model_available:
        model_rows.append(
            ("Requested model", status_text("ok", f"{model_status.model} installed"))
        )
    elif model_status.reachable:
        model_rows.append(
            ("Requested model", status_text("fail", f"{model_status.model} not installed"))
        )
        model_rows.append(
            (
                "Recovery",
                f"optional manual install: ollama pull {model_status.model}",
            )
        )
    else:
        model_rows.append(
            ("Requested model", status_text("warn", f"{model_status.model} (cannot verify)"))
        )
        model_rows.append(
            ("Recovery", "start Ollama with `ollama serve`, then retry")
        )
    model_rows.append(
        (
            "Installed models",
            ", ".join(model_status.models) if model_status.models else "none reported",
        )
    )
    if model_status.error:
        model_rows.append(
            ("Error", status_text("fail", sanitize_output(model_status.error)))
        )
    renderer.fields("Local model", model_rows)

    archive_rows: list[tuple[object, object]] = [
        (
            "Integrity",
            status_text("ok" if health.ok else "fail", "ok" if health.ok else "failed"),
        ),
        (
            "Schema version",
            str(health.schema_version) if health.schema_version is not None else "unknown",
        ),
        ("Memories", str(health.memory_count)),
        ("Interpretations", str(health.interpretation_count)),
        ("Path", health.path),
    ]
    if health.error:
        archive_rows.append(
            ("Error", status_text("fail", sanitize_output(health.error)))
        )
    renderer.fields("Memory archive", archive_rows)


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

    renderer.section(
        "Inspection",
        detail=f"{report.root_kind} - read-only, nothing executed",
    )

    renderer.fields(
        "Scan",
        [
            ("Root", report.root),
            ("Kind", report.root_kind),
            (
                "Text files read",
                f"{len(report.files)} (limit {report.limits.max_files})",
            ),
            (
                "Bytes read",
                f"{_format_bytes(report.total_bytes)} "
                f"(limit {report.limits.max_total_bytes:,})",
            ),
            ("Skipped entries", str(len(report.skipped))),
            ("TODO markers", str(len(report.todos))),
            (
                "Truncated",
                status_text(
                    "warn" if report.truncated else "ok",
                    "yes, limits were reached" if report.truncated else "no",
                ),
            ),
        ],
    )

    signal_rows: list[tuple[object, object]] = []
    if report.readme_path:
        signal_rows.append(("README", report.readme_path))
    for label, value in report.metadata:
        signal_rows.append((label, value))
    if report.extension_counts:
        signal_rows.append(
            (
                "File types",
                ", ".join(
                    f"{extension} ({count})"
                    for extension, count in report.extension_counts[:10]
                ),
            )
        )
    if report.entry_points:
        signal_rows.append(("Likely entry points", ", ".join(report.entry_points[:8])))
    if report.test_files:
        signal_rows.append(
            ("Tests", f"{len(report.test_files)} file(s), e.g. {report.test_files[0]}")
        )
    if signal_rows:
        renderer.fields("Project signals", signal_rows)

    if report.todos:
        renderer.section(
            "TODO markers",
            detail=f"scanner-confirmed - {plural(len(report.todos), 'marker')}",
        )
        markers = renderer.table(None, ["Location", "Tag", "Text"])
        for item in report.todos[:50]:
            markers.add_row(
                Text(f"{item.path}:{item.line}", style="phantom.accent"),
                Text(item.tag, style="phantom.warn"),
                _plain(item.text),
            )
        renderer.print(markers)
        if len(report.todos) > 50:
            renderer.note(f"... {len(report.todos) - 50} more markers not shown.")

    if report.skipped:
        renderer.section(
            "Skipped entries",
            detail=f"nothing was read - {plural(len(report.skipped), 'entry', 'entries')}",
        )
        skipped = renderer.table(None, ["Reason", "Count", "Detail", "Examples"])
        skipped.columns[1].justify = "right"
        for reason, count, detail, examples in _group_skips(report):
            skipped.add_row(
                _plain(reason),
                Text(str(count), style="phantom.muted"),
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
        subtitle="verified evidence",
    )

    if report.injection_markers:
        renderer.section(
            "Instruction-like text",
            detail="treated as data, never followed",
        )
        injection_table = renderer.table(None, ["Location", "Text"])
        for marker in report.injection_markers[:20]:
            injection_table.add_row(
                Text(f"{marker.path}:{marker.line}", style="phantom.accent"),
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
            renderer.section("Unsupported model citations", detail="not found on disk")
            citations = renderer.table(None, ["Citation", "Problem"])
            for citation in analysis.unsupported_citations:
                url, _, problem = citation.partition(" ")
                citations.add_row(
                    Text(url, style="phantom.accent"),
                    _plain(problem.strip("()")),
                )
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
