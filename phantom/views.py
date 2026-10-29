"""Reusable Rich views shared by commands and the chat session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from core.brain import BrainStatus
from core.memory import MemoryHealth, MemoryRecord
from core.personality import MoodState, format_mood

from phantom.config import Settings
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
