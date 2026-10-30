from __future__ import annotations

import io
from typing import Mapping

import pytest

from phantom.cli import build_parser
from phantom.config import Settings, settings_from_args
from phantom.render import Renderer, sanitize_output, status_text


class Tty(io.StringIO):
    """A stream that claims to be an interactive terminal."""

    def isatty(self) -> bool:  # noqa: D102 - test double
        return True


def build_settings(
    *argv: str,
    env: Mapping[str, str] | None = None,
) -> Settings:
    args = build_parser().parse_args(list(argv))
    values = {"PHANTOM_DB": ":memory:"}
    if env:
        values.update(env)
    return settings_from_args(args, env=values, stdout=Tty())


def test_plain_mode_renders_ascii_marks_borders_and_markers():
    stream = io.StringIO()
    renderer = Renderer(
        plain=True,
        file=stream,
        error_file=stream,
        force_terminal=True,
        width=80,
    )

    renderer.banner(animate=True)
    renderer.panel("body", title="PANEL")
    renderer.print(renderer.table("TABLE", ["Column"]))
    renderer.error("something failed", hint="try again")
    renderer.farewell(animate=True)
    renderer.rule("done")

    value = stream.getvalue()
    assert "\x1b" not in value
    assert value.isascii()
    assert "P H A N T O M" in value
    assert "(  o o  )" in value
    assert "(  - -  )" in value
    assert "PANEL" in value
    assert "done" in value


def test_banner_uses_the_full_mark_only_when_styled_and_wide():
    wide = io.StringIO()
    Renderer(file=wide, force_terminal=True, width=80).banner()
    wide_text = sanitize_output(wide.getvalue())
    assert "   |   o     o   |" in wide_text
    assert "   |      ^      |" in wide_text

    narrow = io.StringIO()
    Renderer(file=narrow, force_terminal=True, width=18).banner()
    narrow_text = sanitize_output(narrow.getvalue())
    assert "(  o o  )" in narrow_text
    assert "   |   o     o   |" not in narrow_text
    assert "local only" in narrow_text
    assert "local intelligence" not in narrow_text


def test_reveal_never_sleeps_without_a_safe_terminal(monkeypatch):
    import phantom.render as render_module

    def fail_sleep(_seconds: float) -> None:
        raise AssertionError("reveal slept when animation was unsafe")

    monkeypatch.setattr(render_module.time, "sleep", fail_sleep)

    redirected = io.StringIO()
    Renderer(file=redirected).reveal(["one", "two"], delay=1.0)

    plain_tty = io.StringIO()
    Renderer(plain=True, file=plain_tty, force_terminal=True).reveal(
        ["one", "two"],
        delay=1.0,
    )

    assert "one" in redirected.getvalue()
    assert "two" in plain_tty.getvalue()


def test_animation_is_gated_by_plain_no_color_dumb_term_and_non_tty():
    assert build_settings("status").animation is True
    assert build_settings("status", "--no-animation").animation is False
    assert build_settings("status", "--plain").animation is False
    assert build_settings("status", env={"NO_COLOR": "1"}).animation is False
    assert build_settings("status", env={"TERM": "dumb"}).animation is False

    redirected = io.StringIO()
    args = build_parser().parse_args(["status"])
    settings = settings_from_args(
        args,
        env={"PHANTOM_DB": ":memory:"},
        stdout=redirected,
    )
    assert settings.animation is False


@pytest.mark.parametrize(
    ("state", "marker"),
    [("ok", "[ok]"), ("warn", "[!]"), ("fail", "[x]"), ("info", "[i]")],
)
def test_status_markers_do_not_depend_on_colour(state: str, marker: str):
    assert status_text(state, "detail").plain == f"{marker} detail"


def test_sections_and_field_grids_align_without_borders():
    stream = io.StringIO()
    renderer = Renderer(plain=True, file=stream, width=60)
    renderer.section("Configuration", detail="facts")
    renderer.fields("Configuration", [("Model", "qwen3:8b"), ("Privacy", "local")])

    value = stream.getvalue()
    assert "Configuration" in value
    assert "facts" in value
    assert "Model" in value
    assert "qwen3:8b" in value
    assert value.isascii()
    assert "\x1b" not in value


def test_ask_styles_the_prompt_only_on_a_styled_terminal():
    styled = io.StringIO()
    renderer = Renderer(file=styled, force_terminal=True, width=60)
    prompts: list[str] = []

    def styled_answer(prompt: str) -> str:
        prompts.append(prompt)
        return "hello"

    assert renderer.ask("you", styled_answer) == "hello"
    assert prompts == [""]
    assert "you> " in sanitize_output(styled.getvalue())

    plain = io.StringIO()
    plain_prompts: list[str] = []

    def plain_answer(prompt: str) -> str:
        plain_prompts.append(prompt)
        return "hello"

    plain_renderer = Renderer(plain=True, file=plain, width=60)
    assert plain_renderer.ask("you", plain_answer) == "hello"
    assert plain_prompts == ["you> "]
