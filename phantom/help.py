"""The Rich rendered ``phantom --help`` page.

``argparse`` still owns parsing and its own help output. This module only
paints a friendlier top level page from the same content, so the two can
never drift: every row below is also used to build the argparse epilog.
"""

from __future__ import annotations

import argparse
from typing import Sequence

from rich.text import Text

from phantom.render import Renderer


def option_rows(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    """Collect the visible options of one parser, in declared order."""

    rows: list[tuple[str, str]] = []
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API
        if not action.option_strings:
            continue
        names = ", ".join(action.option_strings)
        if action.nargs != 0:
            metavar = action.metavar or action.dest.upper()
            names = f"{names} {metavar}"
        rows.append((names, action.help or ""))
    return rows


def _table(
    renderer: Renderer,
    title: str,
    rows: Sequence[tuple[str, str]],
    *,
    detail: str | None = None,
    first_style: str = "phantom.accent",
) -> None:
    renderer.section(title, detail=detail)
    table = renderer.table(None, ["", ""])
    table.show_header = False
    table.columns[0].no_wrap = True
    for first, second in rows:
        table.add_row(
            Text(first, style=first_style),
            Text(second, style="phantom.body"),
        )
    renderer.print(table)


def render_help(renderer: Renderer, parser: argparse.ArgumentParser) -> None:
    """Print the top level help screen."""

    from phantom import __version__
    from phantom.helpdata import (
        COMMANDS,
        DISPLAY,
        ENVIRONMENT,
        EXAMPLES,
        EXIT_CODES,
        MODEL,
    )

    renderer.banner()
    renderer.panel(
        Text.assemble(
            ("An offline first presence in your terminal.\n", "phantom.body"),
            (
                "Local inference through Ollama, local memory in SQLite, "
                "and no cloud model provider at any point.",
                "phantom.muted",
            ),
        ),
        title="PHANTOM",
        subtitle=f"v{__version__} / local only",
    )

    renderer.fields("Usage", [("phantom", "[OPTIONS] [COMMAND]")])
    renderer.note(
        "Bare `phantom` awakens the entity. Every command accepts the global "
        "options below, before or after the command name."
    )

    _table(
        renderer,
        "Commands",
        [(name, summary) for name, summary in COMMANDS],
        detail="run `phantom COMMAND --help` for details",
    )

    renderer.section("Examples", detail="copy and run")
    for command in EXAMPLES:
        renderer.print(
            Text("  $ ", style="phantom.muted") + Text(command, style="phantom.body")
        )

    _table(renderer, "Options", option_rows(parser))
    _table(renderer, "Model", MODEL)

    renderer.section("Environment")
    environment = renderer.table(None, ["", ""])
    environment.show_header = False
    environment.columns[0].no_wrap = True
    for name, meaning in ENVIRONMENT:
        environment.add_row(Text(name, style="phantom.accent"), Text(meaning))
    renderer.print(environment)

    _table(renderer, "Display", DISPLAY, first_style="phantom.body")
    _table(renderer, "Exit codes", EXIT_CODES, first_style="phantom.body")

    renderer.note(
        "Source, privacy notes, and the demonstration plan: see README.md. "
        "Every check above is local; nothing phones home."
    )


__all__ = ["option_rows", "render_help"]
