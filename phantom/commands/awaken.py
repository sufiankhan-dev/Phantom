"""``awaken`` - dependency checks, storage initialization, and introduction."""

from __future__ import annotations

import importlib.util
import platform
import sys
from typing import Any

from core.personality import MoodEngine, MoodEvent
from rich.text import Text

from phantom.context import CommandContext
from phantom.render import status_text
from phantom.storage import load_mood, open_store, record_mood
from phantom.views import plural

INTRO = (
    "The terminal cools by a degree. Something settles behind the cursor.\n\n"
    "I am PHANTOM. I run on this machine through Ollama, and nowhere else.\n"
    "What you tell me to remember stays in a local SQLite file you can read.\n"
    "Ask plainly; I will answer plainly."
)

NEXT_STEPS: tuple[tuple[str, str], ...] = (
    ("phantom chat", "speak with the entity"),
    ('phantom remember "TEXT"', "archive an explicit memory"),
    ("phantom memories", "read what it keeps"),
    ("phantom inspect PATH", "read-only look at a project"),
    ("phantom status", "check model and archive"),
)


def run(ctx: CommandContext, args: Any) -> int:
    renderer = ctx.renderer
    settings = ctx.settings
    renderer.banner(animate=settings.animation)

    checks: list[tuple[str, Any]] = []
    checks.append(
        (
            "Python",
            status_text(
                "ok" if sys.version_info >= (3, 11) else "fail",
                f"{platform.python_version()} (3.11 or newer required)",
            ),
        )
    )
    ollama_package = importlib.util.find_spec("ollama") is not None
    checks.append(
        (
            "Ollama package",
            status_text(
                "ok" if ollama_package else "fail",
                "installed" if ollama_package else "missing (pip install ollama)",
            ),
        )
    )

    with open_store(settings) as store:
        health = store.health()
        checks.append(
            (
                "Memory archive",
                status_text("ok" if health.ok else "fail", health.path),
            )
        )

        brain = ctx.make_brain()
        try:
            with renderer.progress("Listening for the local model"):
                model_status = brain.status()
        finally:
            brain.close()

        if model_status.reachable and model_status.model_available:
            model_checks = status_text(
                "ok", f"{model_status.model} available at {model_status.host}"
            )
        elif model_status.reachable:
            model_checks = status_text(
                "fail", f"{model_status.model} is not installed"
            )
        else:
            model_checks = status_text(
                "fail", f"Ollama unreachable at {model_status.host}"
            )
        checks.append(("Local model", model_checks))

        renderer.fields("Awakening", checks, detail="preflight")

        if not health.ok:
            renderer.error(
                "The memory archive failed its integrity check.",
                hint=health.error or "Use a different --db path.",
            )
            return 4

        model_ready = model_status.reachable and model_status.model_available
        if not model_ready:
            if model_status.reachable:
                hint = (
                    f"Install it with `ollama pull {model_status.model}`. "
                    "PHANTOM never downloads models automatically."
                )
            else:
                hint = (
                    f"Start Ollama with `ollama serve`, then confirm with "
                    f"`ollama list`. Details: {model_status.error or 'no response'}"
                )
            renderer.warning(
                "The entity is awake, but the local model is not ready.",
                title="Model not ready",
            )
            renderer.note(hint)
            if getattr(args, "strict", False):
                return 3

        mood = MoodEngine(load_mood(store))
        state = record_mood(
            store,
            mood,
            MoodEvent.SESSION_START,
            renderer=renderer,
        )

        renderer.panel(
            INTRO,
            title="TRANSMISSION",
            subtitle="local model / local archive",
        )

        facts: list[tuple[str, Any]] = [
            ("Model", f"{model_status.model} via {model_status.host}"),
            ("Memories on record", plural(health.memory_count, "memory", "memories")),
            ("Internal state", state.label),
        ]
        if health.schema_version is not None:
            facts.append(("Archive schema", f"v{health.schema_version}"))
        facts.append(("Privacy", "nothing leaves this machine"))
        renderer.fields("Presence", facts)

        renderer.section("Next", detail="commands")
        commands = renderer.table(None, ["Command", "Purpose"])
        for command, purpose in NEXT_STEPS:
            commands.add_row(
                Text(command, style="phantom.accent"),
                Text(purpose, style="phantom.body"),
            )
        renderer.print(commands)

        renderer.print()
        renderer.reveal(
            [
                "It is awake. It is listening."
                if model_ready
                else "It is awake. It is waiting for a model."
            ],
            delay=0.05 if settings.animation else 0.0,
        )

    return 0
