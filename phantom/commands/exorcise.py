"""``exorcise`` - close the session without deleting anything."""

from __future__ import annotations

from pathlib import Path

from core.personality import MoodEngine, MoodEvent
from rich.text import Text

from phantom.config import Settings
from phantom.context import CommandContext
from phantom.storage import load_mood, open_store, record_mood


def _archive_exists(settings: Settings) -> bool:
    path = settings.db_path
    if str(path) == ":memory:":
        return False
    return Path(path).exists()


def run(ctx: CommandContext, args: Any) -> int:
    renderer = ctx.renderer
    settings = ctx.settings

    if _archive_exists(settings):
        with open_store(settings) as store:
            health = store.health()
            mood = MoodEngine(load_mood(store))
            state = record_mood(
                store,
                mood,
                MoodEvent.EXORCISE,
                renderer=renderer,
            )
            count = health.memory_count
            healthy = health.ok
            archive_path = health.path
    else:
        count = 0
        healthy = True
        state = None
        archive_path = settings.db_display

    lines = (
        "The light behind the cursor thins.",
        "The session ends; the archive does not.",
    )
    renderer.farewell(animate=settings.animation)
    renderer.reveal(lines, delay=0.12 if settings.animation else 0.0)

    table = renderer.table("Shutdown", ["Fact", "Value"])
    table.add_row(
        "Memories",
        Text(f"{count} {'memory remains' if count == 1 else 'memories remain'}"),
    )
    table.add_row("Archive", Text(archive_path))
    table.add_row("Archive health", Text("ok" if healthy else "needs attention"))
    if state is not None:
        table.add_row("Internal state", Text(state.label))
    table.add_row("Deleted", Text("nothing"))
    renderer.print(table)

    renderer.panel(
        "Nothing was deleted. Memories remain exactly where they were.\n"
        "PHANTOM is not gone. It is only not running.",
        title="Until next time",
    )
    renderer.rule("the cursor goes dark")
    return 0
