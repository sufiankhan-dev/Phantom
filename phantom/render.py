"""Rich based terminal presentation for PHANTOM.

Everything visual lives here so commands stay about behaviour. Plain mode
uses ASCII borders and no colour, and animation is only enabled for an
interactive terminal. Status words such as ``[ok]`` always accompany colour,
so meaning survives a monochrome terminal.

The visual language is intentionally small:

* a centred ghost mark with the wordmark under it,
* left aligned section rules instead of floating table titles,
* quiet field grids for facts and bordered panels for speech,
* one blank line between blocks, never two.

Animation is deliberately quiet: a short line-by-line reveal of static ASCII
art. It never stands in for work, never hides a result, and never claims that
something happened before the corresponding real operation completed.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Callable, Iterable, Iterator, Sequence

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from phantom.art import (
    ART_WIDTH,
    PHANTOM_ART,
    PHANTOM_FAREWELL_ART,
    PHANTOM_FAREWELL_SIGIL,
    PHANTOM_SIGIL,
    SIGIL_WIDTH,
    TAGLINE,
    TAGLINE_SHORT,
    TAGLINE_TINY,
    WORDMARK,
)

PHANTOM_THEME = Theme(
    {
        "phantom.title": "bold #c9c0e8",
        "phantom.heading": "bold #a99fd1",
        "phantom.ghost": "#8f86b8",
        "phantom.body": "#d9d5e4",
        "phantom.muted": "dim #96a0a8",
        "phantom.key": "#9aa3b2",
        "phantom.accent": "#79c0b0",
        "phantom.ok": "#82c39a",
        "phantom.warn": "#d7b078",
        "phantom.err": "#d48686",
        "phantom.border": "#575073",
        "phantom.prompt": "bold #79c0b0",
    }
)

_MARKERS: dict[str, tuple[str, str]] = {
    "ok": ("[ok]", "phantom.ok"),
    "warn": ("[!]", "phantom.warn"),
    "fail": ("[x]", "phantom.err"),
    "info": ("[i]", "phantom.muted"),
}

_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_ART_DELAY = 0.03
_SIGIL_DELAY = 0.05

# A rule character that survives every encoding in plain mode.
_RULE_PLAIN = "-"
_RULE_STYLED = "─"


def sanitize_output(value: object) -> str:
    """Strip terminal escape sequences and control characters.

    Model output, file names, and stored memories are untrusted. They may be
    displayed, but never as terminal commands.
    """

    if not isinstance(value, str):
        return "" if value is None else str(value)
    cleaned = _ANSI_RE.sub("", value)
    cleaned = _CONTROL_RE.sub("", cleaned)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")


def status_text(state: str, detail: str | None = None) -> Text:
    """Return a status marker plus optional detail as a Rich ``Text``."""

    marker, style = _MARKERS.get(state, _MARKERS["info"])
    text = Text(marker, style=style)
    if detail:
        text.append(f" {sanitize_output(detail)}")
    return text


def badge(text: str, style: str = "phantom.accent") -> Text:
    """Return a small, emphasised inline label such as a memory origin."""

    label = Text(sanitize_output(text), style=style)
    label.stylize("bold")
    return label


def _art_line(line: str) -> Text:
    """Style one ASCII art line, giving the eyes a small teal glint."""

    row = Text(line, style="phantom.ghost")
    for index, character in enumerate(line):
        if character == "o":
            row.stylize("bold phantom.accent", index, index + 1)
        elif character == "^":
            row.stylize("phantom.title", index, index + 1)
    return row


class Renderer:
    """A thin, consistent wrapper around one or two Rich consoles."""

    def __init__(
        self,
        *,
        plain: bool = False,
        no_color: bool = False,
        file: object | None = None,
        error_file: object | None = None,
        width: int | None = None,
        force_terminal: bool | None = None,
    ) -> None:
        self.plain = plain
        self.no_color = no_color or plain
        self._started = False
        options: dict[str, object] = {
            "theme": PHANTOM_THEME,
            "no_color": self.no_color,
            "highlight": False,
        }
        if plain:
            # Plain mode must not emit ANSI even on a real terminal. Setting
            # color_system to None strips colour and attributes entirely.
            options["color_system"] = None
        if width is not None:
            options["width"] = width
        if force_terminal is not None:
            options["force_terminal"] = force_terminal

        self.console = Console(file=file, **options)  # type: ignore[arg-type]
        if error_file is None:
            self.error_console = Console(stderr=True, **options)  # type: ignore[arg-type]
        else:
            self.error_console = Console(file=error_file, **options)  # type: ignore[arg-type]

    # -- primitives -----------------------------------------------------

    @property
    def styled(self) -> bool:
        """Whether borders may use Unicode and animations may run."""

        return not self.plain and self.console.is_terminal

    @property
    def panel_box(self) -> box.Box:
        return box.ROUNDED if self.styled else box.ASCII

    @property
    def table_box(self) -> box.Box:
        return box.SIMPLE_HEAD if self.styled else box.ASCII

    def _space(self) -> None:
        """Open one blank line between blocks, but never at the top."""

        if self._started:
            self.console.print()
        self._started = True

    def print(self, *objects: object, **kwargs: object) -> None:
        self.console.print(*objects, **kwargs)
        self._started = True

    def note(self, message: str) -> None:
        self.console.print(Text(sanitize_output(message), style="phantom.muted"))
        self._started = True

    def info(self, message: str) -> None:
        """Print a status marker for a real, completed measurement."""

        self.console.print(status_text("info", message))
        self._started = True

    def ok(self, message: str) -> None:
        self.console.print(status_text("ok", message))
        self._started = True

    def stats(self, message: str) -> None:
        """Print a quiet, right aligned line of measured facts."""

        self.console.print(
            Text(sanitize_output(message), style="phantom.muted"),
            justify="right",
        )
        self._started = True

    def write_raw(self, text: str) -> None:
        """Write text without Rich wrapping, for machine-readable output."""

        stream = self.console.file
        stream.write(text if text.endswith("\n") else f"{text}\n")
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()

    def rule(self, label: str | None = None) -> None:
        self._space()
        self.console.rule(
            Text(sanitize_output(label), style="phantom.muted") if label else None,
            characters=self._rule_character,
            style="phantom.border",
        )

    @property
    def _rule_character(self) -> str:
        return _RULE_STYLED if self.styled else _RULE_PLAIN

    def section(self, title: str, detail: str | None = None) -> None:
        """Print a left aligned heading with a thin rule.

        Section headings keep their given case so reports still read like
        sentences ("Memory archive", not "MEMORY ARCHIVE").
        """

        label = Text(sanitize_output(title), style="phantom.heading")
        if detail:
            label.append("   ", style="phantom.muted")
            label.append(sanitize_output(detail), style="phantom.muted")
        self._space()
        self.console.rule(
            label,
            characters=self._rule_character,
            style="phantom.border",
            align="left",
        )

    @contextmanager
    def progress(self, message: str) -> Iterator[None]:
        """Show a transient spinner, or one stable line when that is unsafe.

        A spinner is never the only sign that work happened: plain and
        non-interactive runs print the message, and the spinner stops before
        any error or report is written.
        """

        label = sanitize_output(message)
        if not self.styled:
            self.note(f"... {label}")
            yield
            return
        self._space()
        with self.console.status(
            Text(label, style="phantom.muted"),
            spinner="simpleDots",
            spinner_style="phantom.accent",
        ):
            yield

    def warning(self, message: str, *, title: str = "Warning") -> None:
        body = Text(sanitize_output(message), style="phantom.warn")
        self._space()
        self.console.print(
            Panel(
                body,
                title=Text(sanitize_output(title), style="phantom.warn"),
                title_align="left",
                border_style="phantom.warn",
                box=self.panel_box,
                padding=(0, 2),
            )
        )

    def error(self, message: str, *, hint: str | None = None, title: str = "Error") -> None:
        body = Text(sanitize_output(message), style="phantom.err")
        if hint:
            body.append("\n\n", style="phantom.muted")
            body.append("hint: ", style="phantom.muted")
            body.append(sanitize_output(hint), style="phantom.muted")
        self.error_console.print(
            Panel(
                body,
                title=Text(sanitize_output(title), style="phantom.err"),
                title_align="left",
                border_style="phantom.err",
                box=self.panel_box,
                padding=(0, 2),
            )
        )

    def panel(
        self,
        body: RenderableType | str,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        border_style: str = "phantom.border",
        body_style: str | None = None,
    ) -> None:
        if isinstance(body, str):
            content: RenderableType = Text(
                sanitize_output(body), style=body_style or "phantom.body"
            )
        else:
            content = body
        self._space()
        self.console.print(
            Panel(
                content,
                title=(
                    Text(sanitize_output(title), style="phantom.title")
                    if title
                    else None
                ),
                subtitle=(
                    Text(sanitize_output(subtitle), style="phantom.muted")
                    if subtitle
                    else None
                ),
                title_align="left",
                subtitle_align="right",
                border_style=border_style,
                box=self.panel_box,
                padding=(0, 2),
            )
        )

    def table(
        self,
        title: str | None,
        columns: Sequence[str],
        *,
        show_lines: bool = False,
    ) -> Table:
        table = Table(
            title=(
                Text(sanitize_output(title), style="phantom.heading")
                if title
                else None
            ),
            box=self.table_box,
            header_style="phantom.heading",
            border_style="phantom.border",
            title_justify="left",
            expand=False,
            show_lines=show_lines,
            pad_edge=True,
            padding=(0, 2 if self.styled else 1),
        )
        for column in columns:
            table.add_column(
                Text(sanitize_output(column)),
                overflow="fold",
                no_wrap=False,
            )
        return table

    def fields(
        self,
        title: str,
        rows: Sequence[tuple[object, object]],
        *,
        detail: str | None = None,
        value_style: str = "phantom.body",
    ) -> None:
        """Print a section heading followed by an aligned key/value grid.

        Keys are dim and fixed width, values may be rich text such as a
        :func:`status_text` marker. No header row and no outer border, which
        keeps reports readable instead of boxed in.
        """

        self.section(title, detail)
        grid = Table(
            box=None,
            show_header=False,
            pad_edge=True,
            padding=(0, 2 if self.styled else 1),
            expand=False,
        )
        grid.add_column(no_wrap=True, style="phantom.key")
        grid.add_column(overflow="fold", style=value_style)
        for key, value in rows:
            grid.add_row(
                key if isinstance(key, Text) else Text(sanitize_output(key)),
                value
                if isinstance(value, (Text, Table))
                else Text(sanitize_output(value)),
            )
        self.console.print(grid)
        self._started = True

    def ask(
        self,
        label: str,
        input_func: Callable[[str], str] = input,
        *,
        style: str = "phantom.prompt",
    ) -> str:
        """Read one line, styling the prompt only on a live terminal.

        On a styled terminal the prompt is written by Rich (so colour works
        everywhere Rich works) and ``input_func`` receives an empty prompt.
        Everywhere else the plain label is handed to ``input_func`` exactly as
        before, which keeps redirected sessions script friendly.
        """

        if not self.styled:
            return input_func(f"{sanitize_output(label)}> ")
        self.console.print(
            Text(f"{sanitize_output(label)}", style=style)
            + Text("> ", style="phantom.border"),
            end="",
        )
        self._flush()
        reply = input_func("")
        self._started = True
        return reply

    def confirm(
        self,
        question: str,
        input_func: Callable[[str], str] = input,
    ) -> str:
        """Read a yes/no answer, styled only where that is safe."""

        label = sanitize_output(question)
        if not self.styled:
            return input_func(f"{label} ")
        self.console.print(Text(label, style="phantom.warn"), end=" ")
        self._flush()
        answer = input_func("")
        self._started = True
        return answer

    # -- composed views -------------------------------------------------

    def _mark(self, lines: Iterable[str], delay: float, animate: bool) -> None:
        for line in lines:
            self.console.print(_art_line(line))
            if animate:
                time.sleep(delay)

    def banner(self, *, animate: bool = False) -> None:
        """Print the PHANTOM mark, centred on the console.

        The full ghost is used on a styled terminal wide enough for it; a
        compact sigil is used in plain mode, narrow terminals, and redirected
        output so the mark never wraps into noise.
        """

        animate = animate and self.styled
        width = self.console.width
        if self.styled and width >= ART_WIDTH + 2:
            self._mark(PHANTOM_ART, _ART_DELAY, animate)
            self.console.print()
        elif width >= SIGIL_WIDTH + 2:
            self._mark(PHANTOM_SIGIL, _SIGIL_DELAY, animate)
            self.console.print()

        self.console.print(
            Text(
                WORDMARK if width >= len(WORDMARK) else "PHANTOM",
                style="phantom.title",
            ),
            justify="center",
        )
        if width >= len(TAGLINE):
            tagline = TAGLINE
        elif width >= len(TAGLINE_SHORT):
            tagline = TAGLINE_SHORT
        else:
            tagline = TAGLINE_TINY
        self.console.print(Text(tagline, style="phantom.muted"), justify="center")
        self._started = True

    def sigil(self, *, farewell: bool = False, animate: bool = False) -> None:
        """Print the compact three-line mark used inside a session."""

        lines = PHANTOM_FAREWELL_SIGIL if farewell else PHANTOM_SIGIL
        animate = animate and self.styled
        self._space()
        for line in lines:
            self.console.print(_art_line(line))
            if animate:
                time.sleep(_SIGIL_DELAY)

    def farewell(self, *, animate: bool = False) -> None:
        """Print a slow, closed-eye mark for shutdown.

        The full mark is used only where it fits and where styling is
        available. Plain and redirected output gets the compact sigil.
        """

        if self.styled and self.console.width >= ART_WIDTH + 2:
            self._space()
            animate = animate and self.styled
            self._mark(PHANTOM_FAREWELL_ART, _ART_DELAY, animate)
        else:
            self.sigil(farewell=True, animate=animate)
        self.console.print()
        self._started = True

    def reveal(self, lines: Iterable[str], *, delay: float = 0.06) -> None:
        """Print lines slowly only when animation is safe.

        ``delay`` is a request, not a guarantee. Plain mode, a redirected
        stream, and a non-terminal never sleep.
        """

        animate = delay > 0 and self.styled
        for line in lines:
            self.console.print(Text(sanitize_output(line), style="phantom.muted"))
            if animate:
                time.sleep(delay)
        self._started = True

    # -- streaming ------------------------------------------------------

    def begin_reply(self, prefix: str = "phantom") -> None:
        self.console.print(
            Text(prefix, style="phantom.prompt")
            + Text("> ", style="phantom.border"),
            end="",
        )
        self._flush()

    def stream_chunk(self, text: str) -> None:
        if not text:
            return
        self.console.print(
            Text(text, style="phantom.body"),
            end="",
            markup=False,
            highlight=False,
        )
        self._flush()

    def end_reply(self) -> None:
        self.console.print()
        self._started = True

    def _flush(self) -> None:
        stream = getattr(self.console, "file", None)
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()


__all__ = [
    "PHANTOM_THEME",
    "Renderer",
    "badge",
    "sanitize_output",
    "status_text",
]
