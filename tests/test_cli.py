from __future__ import annotations

import io
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pytest

from core.brain import (
    BrainStatus,
    ChatResult,
    ModelNotFoundError,
    OllamaUnavailableError,
    StreamChunk,
)
from core.memory import MemoryStore
from phantom.cli import build_parser, main

COMMANDS = (
    "awaken",
    "chat",
    "inspect",
    "remember",
    "memories",
    "forget",
    "status",
    "exorcise",
)


@dataclass
class CliResult:
    code: int
    out: str
    err: str


class FakeBrain:
    """A deterministic stand-in for the local model boundary."""

    def __init__(
        self,
        *,
        model: str = "qwen3:8b",
        host: str = "http://127.0.0.1:11434",
        reachable: bool = True,
        model_available: bool = True,
        models: Sequence[str] = ("qwen3:8b",),
        chunks: Iterable[StreamChunk] = (),
        preflight_error: Exception | None = None,
        stream_error: Exception | None = None,
        status_error: Exception | None = None,
        completion_text: str = "No clear problems found.",
        completion_error: Exception | None = None,
    ) -> None:
        self.model = model
        self.host = host
        self.reachable = reachable
        self.model_available = model_available
        self.models = tuple(models)
        self.chunks = tuple(chunks)
        self.preflight_error = preflight_error
        self.stream_error = stream_error
        self.status_error = status_error
        self.completion_text = completion_text
        self.completion_error = completion_error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def status(self) -> BrainStatus:
        if self.status_error is not None:
            return BrainStatus(
                host=self.host,
                model=self.model,
                reachable=False,
                model_available=False,
                error=str(self.status_error),
            )
        return BrainStatus(
            host=self.host,
            model=self.model,
            reachable=self.reachable,
            model_available=self.model_available,
            models=self.models,
            error=None if self.reachable else "connection refused",
        )

    def ensure_ready(self, model: str | None = None, *, force: bool = False) -> None:
        if self.preflight_error is not None:
            raise self.preflight_error

    def stream_chat(self, messages, *, system=None, **kwargs):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "system": system,
                **kwargs,
            }
        )
        if self.stream_error is not None:
            raise self.stream_error
        yield from self.chunks

    def complete_chat(self, messages, *, system=None, **kwargs):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "system": system,
                **kwargs,
            }
        )
        if self.completion_error is not None:
            raise self.completion_error
        return ChatResult(text=self.completion_text, model=self.model)

    def close(self) -> None:
        self.closed = True


class InterruptingBrain(FakeBrain):
    def stream_chat(self, messages, *, system=None, **kwargs):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "system": system,
                **kwargs,
            }
        )
        yield StreamChunk("partial ")
        raise KeyboardInterrupt


def run_cli(
    argv: Sequence[str],
    tmp_path: Path,
    *,
    brain: FakeBrain | None = None,
    factory: Callable[[Any], FakeBrain] | None = None,
    input_lines: Sequence[str] = (),
    input_func: Callable[[str], str] | None = None,
    env: dict[str, str] | None = None,
) -> CliResult:
    out = io.StringIO()
    err = io.StringIO()
    pending = list(input_lines)

    def default_input(prompt: str = "") -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    values = {
        "PHANTOM_DB": str(tmp_path / "phantom.db"),
        "NO_COLOR": "1",
    }
    if env:
        values.update(env)

    if factory is None:
        if brain is None:
            factory = lambda settings: FakeBrain(  # noqa: E731
                model=settings.brain.model,
                host=settings.brain.host,
            )
        else:
            factory = lambda settings: brain  # noqa: E731

    code = main(
        argv,
        stdout=out,
        stderr=err,
        env=values,
        brain_factory=factory,
        input_func=input_func or default_input,
    )
    return CliResult(code, out.getvalue(), err.getvalue())


def seed_memory(tmp_path: Path, text: str):
    store = MemoryStore(tmp_path / "phantom.db")
    store.initialize()
    try:
        return store.remember(text)
    finally:
        store.close()


def read_memories(tmp_path: Path):
    store = MemoryStore(tmp_path / "phantom.db")
    store.initialize()
    try:
        return store.list_memories()
    finally:
        store.close()


def read_mood(tmp_path: Path):
    store = MemoryStore(tmp_path / "phantom.db")
    store.initialize()
    try:
        return store.load_mood()
    finally:
        store.close()


# -- parser ------------------------------------------------------------


def test_parser_defaults_to_no_command_and_the_cli_awakens(tmp_path):
    assert build_parser().parse_args([]).command is None

    result = run_cli([], tmp_path)
    assert result.code == 0
    assert "TRANSMISSION" in result.out
    assert "Memories on record" in result.out
    assert (tmp_path / "phantom.db").exists()


def test_bare_phantom_is_the_same_experience_as_awaken(tmp_path):
    bare = run_cli([], tmp_path)
    explicit = run_cli(["awaken"], tmp_path)
    assert bare.code == explicit.code == 0
    assert "P H A N T O M" in bare.out
    assert "P H A N T O M" in explicit.out
    assert "It is awake." in bare.out
    assert "It is awake." in explicit.out


def test_pyproject_declares_the_phantom_console_script():
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["scripts"]["phantom"] == "phantom.main:main"


def test_parser_accepts_every_command():
    parser = build_parser()
    for command in COMMANDS:
        argv = [command]
        if command == "inspect":
            argv.append(".")
        elif command == "remember":
            argv.append("text")
        elif command == "forget":
            argv.append("abcd")
        args = parser.parse_args(argv)
        assert args.command == command


@pytest.mark.parametrize(
    "argv",
    [
        ["inspect"],
        ["inspect", ".", "--max-files", "0"],
        ["inspect", ".", "--max-file-bytes", "0"],
        ["inspect", ".", "--max-total-bytes", "0"],
        ["inspect", ".", "--max-depth", "0"],
        ["remember"],
        ["forget"],
        ["memories", "--limit", "0"],
        ["status", "--timeout", "0"],
    ],
)
def test_parser_rejects_invalid_input(argv, capsys):
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args(argv)
    assert info.value.code == 2
    capsys.readouterr()


def test_global_options_work_before_and_after_the_command():
    parser = build_parser()
    for argv in (
        ["--plain", "--model", "gemma3:4b", "status"],
        ["status", "--plain", "--model", "gemma3:4b"],
    ):
        args = parser.parse_args(argv)
        assert args.plain is True
        assert args.model == "gemma3:4b"


def test_help_lists_every_command():
    text = build_parser().format_help()
    for command in COMMANDS:
        assert command in text
    assert "PHANTOM_ALLOW_REMOTE_OLLAMA" in text
    assert "phantom inspect ." in text
    assert "phantom forget 1" in text
    assert "python -m phantom.main" in text
    assert "development" in text.lower()


def test_external_ollama_host_is_refused(tmp_path):
    result = run_cli(["status", "--host", "http://10.1.2.3:11434"], tmp_path)
    assert result.code == 2
    assert "non-local" in result.err
    # The recovery advice must appear once: as the hint, not duplicated in the
    # message as well.
    assert result.err.count("PHANTOM only talks to a local Ollama") == 1


# -- remember / memories ----------------------------------------------


def test_remember_stores_and_reports(tmp_path):
    result = run_cli(
        ["remember", "I prefer pytest and short answers."],
        tmp_path,
    )
    assert result.code == 0
    assert "Memory archived" in result.out
    assert "Nothing left this machine" in result.out

    records = read_memories(tmp_path)
    assert len(records) == 1
    assert records[0].content == "I prefer pytest and short answers."
    assert records[0].origin == "user"

    mood = read_mood(tmp_path)
    assert mood is not None
    assert mood["evidence"][0] == "memory archived"


def test_remember_rejects_empty_text(tmp_path):
    result = run_cli(["remember", "   "], tmp_path)
    assert result.code == 2
    assert "cannot be empty" in result.err
    assert read_memories(tmp_path) == []


def test_memories_lists_identifiers_and_timestamps(tmp_path):
    first = seed_memory(tmp_path, "I prefer pytest.")
    second = seed_memory(tmp_path, "My editor is Neovim.")

    result = run_cli(["memories"], tmp_path)
    assert result.code == 0
    assert first.short_id in result.out
    assert second.short_id in result.out
    assert "I prefer pytest." in result.out
    assert "user" in result.out
    assert "2 memories" in result.out


def test_memories_handles_an_empty_archive(tmp_path):
    result = run_cli(["memories"], tmp_path)
    assert result.code == 0
    assert "archive is empty" in result.out


def test_memories_limit_reports_what_was_shown(tmp_path):
    for index in range(3):
        seed_memory(tmp_path, f"Memory number {index}")

    result = run_cli(["memories", "--limit", "2"], tmp_path)
    assert result.code == 0
    assert "Showing 2 of 3" in result.out


def test_remember_rejects_oversized_text(tmp_path):
    result = run_cli(["remember", "x" * 4001], tmp_path)
    assert result.code == 2
    assert "too long" in result.err


def test_memories_render_untrusted_text_literally(tmp_path):
    seed_memory(tmp_path, "[bold red]not markup[/bold red]")
    seed_memory(tmp_path, "escape \x1b[31msequence\x1b[0m")

    result = run_cli(["memories", "--plain"], tmp_path)
    assert result.code == 0
    assert "[bold red]not markup[/bold red]" in result.out
    assert "\x1b" not in result.out
    assert "escape sequence" in result.out


def test_plain_renderer_emits_no_ansi_even_on_a_terminal():
    from phantom.render import Renderer

    stream = io.StringIO()
    renderer = Renderer(plain=True, file=stream, force_terminal=True)
    renderer.ok("done")
    renderer.panel("body")
    renderer.print(renderer.table("Table", ["A"]))
    assert "\x1b" not in stream.getvalue()


def test_remember_does_not_overwrite_a_corrupt_mood_record(tmp_path):
    seed_memory(tmp_path, "Existing memory.")
    connection = sqlite3.connect(tmp_path / "phantom.db")
    connection.execute(
        "INSERT OR REPLACE INTO mood_state (id, state_json, updated_at) "
        "VALUES (1, 'not json', '2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    result = run_cli(["remember", "New memory."], tmp_path)
    assert result.code == 0
    assert "Mood state could not be saved" in result.out
    assert len(read_memories(tmp_path)) == 2

    connection = sqlite3.connect(tmp_path / "phantom.db")
    row = connection.execute(
        "SELECT state_json FROM mood_state WHERE id = 1"
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] == "not json"


# -- forget -----------------------------------------------------------


def test_forget_requires_confirmation(tmp_path):
    record = seed_memory(tmp_path, "This must survive.")

    result = run_cli(["forget", record.short_id], tmp_path)
    assert result.code == 2
    assert "No confirmation" in result.err
    assert [item.id for item in read_memories(tmp_path)] == [record.id]


def test_forget_can_be_cancelled(tmp_path):
    record = seed_memory(tmp_path, "This must survive.")

    result = run_cli(["forget", record.short_id], tmp_path, input_lines=["n"])
    assert result.code == 0
    assert "Nothing was deleted" in result.out
    assert len(read_memories(tmp_path)) == 1


def test_forget_deletes_one_memory_after_yes(tmp_path):
    record = seed_memory(tmp_path, "This must go.")

    result = run_cli(["forget", record.short_id], tmp_path, input_lines=["y"])
    assert result.code == 0
    assert "Memory released" in result.out
    assert read_memories(tmp_path) == []


def test_forget_yes_skips_the_prompt(tmp_path):
    record = seed_memory(tmp_path, "This must go.")

    result = run_cli(["forget", record.short_id, "--yes"], tmp_path)
    assert result.code == 0
    assert "Deleted one memory" in result.out
    assert read_memories(tmp_path) == []


def test_forget_accepts_the_number_shown_by_memories(tmp_path):
    older = seed_memory(tmp_path, "Older memory.")
    newer = seed_memory(tmp_path, "Newer memory.")

    listing = run_cli(["memories"], tmp_path)
    assert listing.code == 0
    assert "1" in listing.out

    result = run_cli(["forget", "1"], tmp_path, input_lines=["y"])
    assert result.code == 0
    assert "Memory released" in result.out
    assert [record.id for record in read_memories(tmp_path)] == [older.id]
    assert newer.id not in [record.id for record in read_memories(tmp_path)]


def test_forget_number_out_of_range_deletes_nothing(tmp_path):
    seed_memory(tmp_path, "Only memory.")

    result = run_cli(["forget", "9"], tmp_path)
    assert result.code == 2
    assert "no memory at position 9" in result.err.lower()
    assert len(read_memories(tmp_path)) == 1


def test_forget_number_zero_is_refused(tmp_path):
    seed_memory(tmp_path, "Only memory.")

    result = run_cli(["forget", "0"], tmp_path)
    assert result.code == 2
    assert "start at 1" in result.err
    assert len(read_memories(tmp_path)) == 1


def test_forget_unknown_id_is_a_usage_error(tmp_path):
    result = run_cli(["forget", "deadbeef"], tmp_path)
    assert result.code == 2
    assert "No memory matches" in result.err


def test_forget_interrupt_deletes_nothing(tmp_path):
    record = seed_memory(tmp_path, "Still here.")

    def interrupt(prompt: str) -> str:
        raise KeyboardInterrupt

    result = run_cli(["forget", record.short_id], tmp_path, input_func=interrupt)
    assert result.code == 130
    assert "Interrupted" in result.err
    assert len(read_memories(tmp_path)) == 1


# -- status -----------------------------------------------------------


def test_status_reports_real_state_as_tables(tmp_path):
    seed_memory(tmp_path, "One memory.")

    result = run_cli(["status"], tmp_path)
    assert result.code == 0
    assert "Configuration" in result.out
    assert "Ollama service" in result.out
    assert "[ok] reachable" in result.out
    assert "Memory archive" in result.out
    assert "Memories" in result.out


def test_status_json_is_machine_readable(tmp_path):
    seed_memory(tmp_path, "One memory.")

    result = run_cli(["status", "--json"], tmp_path)
    assert result.code == 0
    payload = json.loads(result.out)
    assert payload["model"]["name"] == "qwen3:8b"
    assert payload["ollama"]["reachable"] is True
    assert payload["ollama"]["model_available"] is True
    assert payload["database"]["memories"] == 1
    assert payload["database"]["schema_version"] == 1


def test_status_honours_the_model_environment(tmp_path):
    result = run_cli(
        ["status", "--json"],
        tmp_path,
        env={"PHANTOM_MODEL": "gemma3:4b"},
    )
    assert result.code == 0
    payload = json.loads(result.out)
    assert payload["model"]["name"] == "gemma3:4b"


def test_status_with_unreachable_ollama(tmp_path):
    brain = FakeBrain(status_error=OllamaUnavailableError("Cannot reach Ollama."))
    result = run_cli(["status"], tmp_path, brain=brain)
    assert result.code == 3
    assert "unreachable" in result.out
    assert "Cannot reach Ollama." in result.out
    assert "ollama serve" in result.out


def test_status_with_missing_model(tmp_path):
    brain = FakeBrain(model_available=False, models=("gemma3:4b",))
    result = run_cli(["status"], tmp_path, brain=brain)
    assert result.code == 3
    assert "not installed" in result.out
    assert "ollama pull qwen3:8b" in result.out


def test_status_with_corrupt_database(tmp_path):
    (tmp_path / "phantom.db").write_bytes(b"this is not a sqlite database")

    result = run_cli(["status"], tmp_path)
    assert result.code == 4
    assert "database" in result.err.lower()


# -- awaken -----------------------------------------------------------


def test_awaken_initializes_storage_and_introduces_the_entity(tmp_path):
    result = run_cli(["awaken", "--plain"], tmp_path)
    assert result.code == 0
    assert (tmp_path / "phantom.db").exists()
    assert "P H A N T O M" in result.out
    assert "(  o o  )" in result.out
    assert "TRANSMISSION" in result.out
    assert "[ok] qwen3:8b available" in result.out
    assert "Memories on record" in result.out
    assert "\x1b" not in result.out

    mood = read_mood(tmp_path)
    assert mood is not None
    assert mood["evidence"][0] == "session opened"


def test_awaken_warns_when_the_model_is_missing(tmp_path):
    brain = FakeBrain(model_available=False, models=("gemma3:4b",))
    result = run_cli(["awaken", "--plain"], tmp_path, brain=brain)
    assert result.code == 0
    assert "not ready" in result.out
    assert "ollama pull qwen3:8b" in result.out


def test_awaken_strict_fails_when_the_model_is_missing(tmp_path):
    brain = FakeBrain(model_available=False, models=("gemma3:4b",))
    result = run_cli(["awaken", "--plain", "--strict"], tmp_path, brain=brain)
    assert result.code == 3


def test_awaken_warns_when_ollama_is_unreachable(tmp_path):
    brain = FakeBrain(status_error=OllamaUnavailableError("Cannot reach Ollama."))
    result = run_cli(["awaken", "--plain"], tmp_path, brain=brain)
    assert result.code == 0
    assert "Ollama unreachable" in result.out
    assert "ollama serve" in result.out


def test_awaken_fails_on_a_corrupt_archive(tmp_path):
    (tmp_path / "phantom.db").write_bytes(b"garbage")

    result = run_cli(["awaken"], tmp_path)
    assert result.code == 4


class FakeTTY(io.StringIO):
    """A writable stream that claims to be an interactive terminal."""

    def isatty(self) -> bool:
        return True


def _run_awaken_on_a_terminal(tmp_path, monkeypatch, *flags):
    from phantom import render as render_module

    delays: list[float] = []
    monkeypatch.setattr(render_module.time, "sleep", delays.append)
    out = FakeTTY()
    code = main(
        ["awaken", *flags],
        stdout=out,
        stderr=io.StringIO(),
        env={
            "PHANTOM_DB": str(tmp_path / "phantom.db"),
            "TERM": "xterm-256color",
        },
        brain_factory=lambda settings: FakeBrain(
            model=settings.brain.model,
            host=settings.brain.host,
        ),
    )
    return code, out.getvalue(), delays


def test_awaken_no_animation_never_sleeps(tmp_path, monkeypatch):
    code, out, delays = _run_awaken_on_a_terminal(
        tmp_path, monkeypatch, "--no-animation"
    )
    assert code == 0
    assert delays == []
    assert "It is awake." in out


def test_awaken_animation_is_short_and_bounded(tmp_path, monkeypatch):
    code, out, delays = _run_awaken_on_a_terminal(tmp_path, monkeypatch)
    assert code == 0
    assert delays, "the awakening mark should be revealed line by line"
    assert max(delays) <= 0.12
    assert sum(delays) < 2.0
    assert "It is awake." in out


# -- exorcise ---------------------------------------------------------


def test_exorcise_preserves_memories(tmp_path):
    seed_memory(tmp_path, "Do not delete me.")

    result = run_cli(["exorcise", "--plain"], tmp_path)
    assert result.code == 0
    assert "Nothing was deleted" in result.out
    assert "1 memory remains" in result.out
    assert len(read_memories(tmp_path)) == 1


def test_exorcise_does_not_create_an_archive(tmp_path):
    result = run_cli(["exorcise", "--plain"], tmp_path)
    assert result.code == 0
    assert "0 memories remain" in result.out
    assert not (tmp_path / "phantom.db").exists()


def test_exorcise_shows_the_closed_mark_and_closes_cleanly(tmp_path):
    result = run_cli(["exorcise", "--plain"], tmp_path)
    assert result.code == 0
    assert "(  - -  )" in result.out
    assert "the cursor goes dark" in result.out
    assert "\x1b" not in result.out


# -- inspect ----------------------------------------------------------


def test_inspect_rejects_a_missing_path(tmp_path):
    result = run_cli(["inspect", str(tmp_path / "missing")], tmp_path)
    assert result.code == 2
    assert "Path not found" in result.err


def test_inspect_reports_findings_without_modifying(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    source = target / "app.py"
    source.write_text(
        "print('unchanged')\n# TODO: check this\n",
        encoding="utf-8",
    )

    result = run_cli(["inspect", str(target), "--plain", "--no-ai"], tmp_path)
    assert result.code == 0
    assert "Confirmed observations" in result.out
    assert "app.py:2" in result.out
    assert "TODO" in result.out
    assert "Model interpretation skipped" in result.out
    assert "\x1b" not in result.out
    assert source.read_text(encoding="utf-8") == (
        "print('unchanged')\n# TODO: check this\n"
    )


# -- chat -------------------------------------------------------------


def test_chat_streams_and_keeps_bounded_history(tmp_path):
    brain = FakeBrain(
        chunks=(
            StreamChunk("The "),
            StreamChunk("ash."),
            StreamChunk("", done=True),
        )
    )
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["What do you see?", "And now?", "/exit"],
    )

    assert result.code == 0
    assert "phantom> The ash." in result.out
    assert len(brain.calls) == 2
    assert brain.calls[1]["messages"] == [
        {"role": "user", "content": "What do you see?"},
        {"role": "assistant", "content": "The ash."},
        {"role": "user", "content": "And now?"},
    ]
    assert brain.calls[0]["system"]
    assert read_memories(tmp_path) == []
    assert "\x1b" not in result.out

    mood = read_mood(tmp_path)
    assert mood is not None
    assert "conversation turn" in mood["evidence"]


def test_chat_reports_only_measured_stream_metrics(tmp_path):
    brain = FakeBrain(
        chunks=(
            StreamChunk("Measured."),
            StreamChunk(
                "",
                done=True,
                eval_count=10,
                eval_duration_ns=2_000_000_000,
            ),
        )
    )
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["hello", "/exit"],
    )

    assert result.code == 0
    assert "Measured." in result.out
    assert "10 tokens" in result.out
    assert "5.0 tok/s" in result.out


def test_chat_does_not_invent_stream_metrics(tmp_path):
    brain = FakeBrain(chunks=(StreamChunk("No measurement."),))
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["hello", "/exit"],
    )

    assert result.code == 0
    assert "No measurement." in result.out
    assert "tok/s" not in result.out
    assert "tokens" not in result.out


def test_chat_supplies_relevant_memories_to_the_prompt(tmp_path):
    seed_memory(tmp_path, "I prefer pytest.")
    brain = FakeBrain(chunks=(StreamChunk("Noted."),))

    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["Which test runner should I use?", "/exit"],
    )

    assert result.code == 0
    system = brain.calls[0]["system"]
    assert "I prefer pytest." in system
    assert "USER-SUPPLIED" in system


def test_chat_preflight_failure_exits_three(tmp_path):
    brain = FakeBrain(preflight_error=ModelNotFoundError("qwen3:8b"))
    result = run_cli(["chat"], tmp_path, brain=brain)
    assert result.code == 3
    assert "not installed" in result.err


def test_chat_survives_a_stream_failure_without_recording_the_turn(tmp_path):
    brain = FakeBrain(stream_error=OllamaUnavailableError("Cannot reach Ollama."))
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["hello", "again", "/exit"],
    )

    assert result.code == 0
    assert "Cannot reach Ollama." in result.err
    assert brain.calls[1]["messages"] == [{"role": "user", "content": "again"}]

    mood = read_mood(tmp_path)
    assert mood is not None
    assert any("model error" in item for item in mood["evidence"])


def test_chat_interrupt_during_stream_does_not_record_the_turn(tmp_path):
    brain = InterruptingBrain()
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["hello", "again", "/exit"],
    )

    assert result.code == 0
    assert "partial" in result.out
    assert "Interrupted" in result.out
    assert brain.calls[1]["messages"] == [{"role": "user", "content": "again"}]


def test_chat_clear_drops_conversation_history(tmp_path):
    brain = FakeBrain(chunks=(StreamChunk("A response."),))
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=["first", "/clear", "second", "/exit"],
    )

    assert result.code == 0
    assert brain.calls[1]["messages"] == [{"role": "user", "content": "second"}]


def test_chat_slash_commands_manage_memories(tmp_path):
    brain = FakeBrain(chunks=(StreamChunk("Noted."),))
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=[
            "/remember I like tea.",
            "/memories",
            "/mood",
            "/exit",
        ],
    )

    assert result.code == 0
    assert "Archived as" in result.out
    assert "I like tea." in result.out
    assert "Internal state" in result.out
    records = read_memories(tmp_path)
    assert [record.content for record in records] == ["I like tea."]


def test_chat_slash_forget_requires_confirmation(tmp_path):
    record = seed_memory(tmp_path, "Delete me.")
    brain = FakeBrain()

    cancelled = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=[f"/forget {record.short_id}", "n", "/exit"],
    )
    assert cancelled.code == 0
    assert "Nothing was deleted" in cancelled.out
    assert len(read_memories(tmp_path)) == 1

    confirmed = run_cli(
        ["chat", "--plain"],
        tmp_path,
        brain=brain,
        input_lines=[f"/forget {record.short_id}", "y", "/exit"],
    )
    assert confirmed.code == 0
    assert "released" in confirmed.out
    assert read_memories(tmp_path) == []


def test_chat_handles_eof_cleanly(tmp_path):
    result = run_cli(["chat", "--plain"], tmp_path, input_lines=[])
    assert result.code == 0
    assert "transcript was not saved" in result.out


def test_chat_handles_ctrl_c_at_the_prompt_cleanly(tmp_path):
    def interrupt(prompt: str) -> str:
        raise KeyboardInterrupt

    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        input_func=interrupt,
    )
    assert result.code == 0
    assert "transcript was not saved" in result.out
    assert "Traceback" not in result.out
    assert "Traceback" not in result.err


def test_keyboard_interrupt_during_a_check_exits_130(tmp_path):
    class InterruptingStatusBrain(FakeBrain):
        def status(self):
            raise KeyboardInterrupt

    result = run_cli(["status"], tmp_path, brain=InterruptingStatusBrain())
    assert result.code == 130
    assert "Interrupted" in result.err


def test_chat_reports_unknown_slash_commands(tmp_path):
    result = run_cli(
        ["chat", "--plain"],
        tmp_path,
        input_lines=["/summon", "/exit"],
    )
    assert result.code == 0
    assert "Unknown command" in result.out
