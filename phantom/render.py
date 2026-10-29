"""Rich based terminal presentation for PHANTOM.

Everything visual lives here so commands stay about behaviour. Plain mode
uses ASCII borders and no colour, and animation is only enabled for an
interactive terminal. Status words such as ``[ok]`` always accompany colour,
so meaning survives a monochrome terminal.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Iterable, Iterator, Sequence

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

PHANTOM_THEME = Theme(
    {
        "phantom.title": "bold #b8a6d9",
        "phantom.ghost": "#8b7fa8",
        "phantom.muted": "dim #9a9a9a",
        "phantom.accent": "#7fb7a8",
        "phantom.ok": "#7fb78a",
        "phantom.warn": "#d1a86b",
        "phantom.err": "#c97b7b",
        "phantom.border": "#5c5470",
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

_GHOST = (
    "      .-------.",
    "     /  o   o  \\",
    "    |     ^     |",
    "    |   \\___/   |",
    "     \\_________/",
)


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
        text.append(f" {detail}")
    return text


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
    def panel_box(self) -> box.Box:
        return box.ASCII if self.plain else box.ROUNDED

    @property
    def table_box(self) -> box.Box:
        return box.ASCII if self.plain else box.SIMPLE_HEAD

    def print(self, *objects: object, **kwargs: object) -> None:
        self.console.print(*objects, **kwargs)

    def note(self, message: str) -> None:
        self.console.print(Text(message, style="phantom.muted"))

    def write_raw(self, text: str) -> None:
        """Write text without Rich wrapping, for machine-readable output."""

        stream = self.console.file
        stream.write(text if text.endswith("\n") else f"{text}\n")
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()

    def rule(self, label: str | None = None) -> None:
        self.console.rule(
            Text(label, style="phantom.muted") if label else None,
            style="phantom.border",
        )

    @contextmanager
    def progress(self, message: str) -> Iterator[None]:
        """Show a transient spinner, or one stable line when that is unsafe.

        A spinner is never the only sign that work happened: plain and
        non-interactive runs print the message, and the spinner stops before
        any error or report is written.
        """

        label = sanitize_output(message)
        if self.plain or not self.console.is_terminal:
            self.note(f"... {label}")
            yield
            return
        with self.console.status(Text(label, style="phantom.muted"), spinner="dots"):
            yield

    def ok(self, message: str) -> None:
        self.console.print(status_text("ok", message))

    def warning(self, message: str, *, title: str = "Warning") -> None:
        body = Text(sanitize_output(message), style="phantom.warn")
        self.console.print(
            Panel(
                body,
                title=Text(title, style="phantom.warn"),
                border_style="phantom.warn",
                box=self.panel_box,
                padding=(0, 1),
            )
        )

    def error(self, message: str, *, hint: str | None = None, title: str = "Error") -> None:
        body = Text(sanitize_output(message), style="phantom.err")
        if hint:
            body.append("\n\n", style="phantom.muted")
            body.append(sanitize_output(hint), style="phantom.muted")
        self.error_console.print(
            Panel(
                body,
                title=Text(title, style="phantom.err"),
                border_style="phantom.err",
                box=self.panel_box,
                padding=(0, 1),
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
                sanitize_output(body), style=body_style or ""
            )
        else:
            content = body
        self.console.print(
            Panel(
                content,
                title=Text(title, style="phantom.title") if title else None,
                subtitle=(
                    Text(subtitle, style="phantom.muted") if subtitle else None
                ),
                border_style=border_style,
                box=self.panel_box,
                padding=(0, 1),
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
            title=Text(title, style="phantom.title") if title else None,
            box=self.table_box,
            header_style="phantom.title",
            title_justify="left",
            expand=False,
            show_lines=show_lines,
            pad_edge=False,
        )
        for column in columns:
            table.add_column(Text(column), overflow="fold", no_wrap=False)
        return table

    # -- composed views -------------------------------------------------

    def banner(self) -> None:
        self.console.print(Text("\n".join(_GHOST), style="phantom.ghost"))
        self.console.print(Text("P H A N T O M", style="phantom.title"))
        self.console.print(
            Text("local intelligence / no cloud / no leash", style="phantom.muted")
        )

    def reveal(self, lines: Iterable[str], *, delay: float = 0.06) -> None:
        """Print lines slowly only when animation is safe."""

        for line in lines:
            self.console.print(Text(sanitize_output(line), style="phantom.muted"))
            if delay > 0:
                time.sleep(delay)

    # -- streaming ------------------------------------------------------

    def begin_reply(self, prefix: str = "phantom> ") -> None:
        self.console.print(Text(prefix, style="phantom.title"), end="")
        self._flush()

    def stream_chunk(self, text: str) -> None:
        if not text:
            return
        self.console.print(Text(text), end="", markup=False, highlight=False)
        self._flush()

    def end_reply(self) -> None:
        self.console.print()

    def _flush(self) -> None:
        stream = getattr(self.console, "file", None)
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()


__all__ = ["PHANTOM_THEME", "Renderer", "sanitize_output", "status_text"]
