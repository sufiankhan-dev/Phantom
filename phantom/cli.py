"""The argparse command tree, dispatch, and error presentation."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import traceback
from typing import Any, Callable, Mapping, Sequence

from core.brain import (
    Brain,
    BrainConfigError,
    BrainError,
    ExternalServiceError,
)
from core.memory import (
    AmbiguousMemoryError,
    InvalidMemoryError,
    MemoryNotFoundError,
    PhantomMemoryError,
)

from phantom import __version__
from phantom.config import settings_from_args
from phantom.context import CommandContext
from phantom.errors import (
    CliError,
    DatabaseError,
    DependencyError,
    EXIT_INTERRUPTED,
    UsageError,
)

_COMMAND_MODULES = {
    "awaken": "phantom.commands.awaken",
    "chat": "phantom.commands.chat",
    "inspect": "phantom.commands.inspect",
    "remember": "phantom.commands.remember",
    "memories": "phantom.commands.memories",
    "forget": "phantom.commands.forget",
    "status": "phantom.commands.status",
    "exorcise": "phantom.commands.exorcise",
}

_EPILOG = """\
examples:
  python -m phantom.main awaken
  python -m phantom.main chat
  python -m phantom.main inspect PATH
  python -m phantom.main remember "I prefer pytest and short answers."
  python -m phantom.main memories
  python -m phantom.main forget 1a2b3c4d
  python -m phantom.main status
  python -m phantom.main exorcise

environment:
  PHANTOM_MODEL                 model name (default: qwen3:8b)
  PHANTOM_OLLAMA_HOST           Ollama endpoint (default: http://127.0.0.1:11434)
  OLLAMA_HOST                   used when PHANTOM_OLLAMA_HOST is unset
  PHANTOM_DB                    database path (default: ~/.phantom/phantom.db)
  PHANTOM_HOME                  directory holding phantom.db
  PHANTOM_TIMEOUT               model read timeout in seconds
  PHANTOM_ALLOW_REMOTE_OLLAMA=1 permit a non-loopback Ollama host
  NO_COLOR                      disable colour

exit codes:
  0 success   2 invalid input   3 local model unavailable
  4 database  5 inspection unavailable   130 interrupted
"""


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _common_parser() -> argparse.ArgumentParser:
    """Options accepted before or after the subcommand."""

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--model",
        metavar="NAME",
        default=argparse.SUPPRESS,
        help="Ollama model to use (default: qwen3:8b; env PHANTOM_MODEL).",
    )
    common.add_argument(
        "--host",
        metavar="URL",
        default=argparse.SUPPRESS,
        help="Ollama endpoint (default: http://127.0.0.1:11434; env OLLAMA_HOST).",
    )
    common.add_argument(
        "--db",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="Memory database path (default: ~/.phantom/phantom.db; env PHANTOM_DB).",
    )
    common.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=_positive_float,
        default=argparse.SUPPRESS,
        help="Model read timeout in seconds (default: 300).",
    )
    common.add_argument(
        "--allow-remote-ollama",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Permit a non-loopback Ollama host; prompts would leave this machine.",
    )
    common.add_argument(
        "--plain",
        action="store_true",
        default=argparse.SUPPRESS,
        help="ASCII, line-oriented output with no colour or animation.",
    )
    common.add_argument(
        "--no-animation",
        dest="animation",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Disable the short startup and shutdown reveals.",
    )
    common.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Show a traceback for unexpected errors.",
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    """Build the full command line parser."""

    common = _common_parser()
    parser = argparse.ArgumentParser(
        prog="phantom",
        description=(
            "PHANTOM - an offline first presence in your terminal. "
            "Local inference through Ollama, local memory in SQLite, no cloud."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"PHANTOM {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
        required=True,
        title="commands",
    )

    awaken = subparsers.add_parser(
        "awaken",
        parents=[common],
        help="Check dependencies, open the archive, and introduce PHANTOM.",
        description=(
            "Display the startup sequence, verify Python and Ollama, initialize "
            "the memory archive, and introduce the entity. A missing model is a "
            "warning unless --strict is given."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n  python -m phantom.main awaken\n  python -m phantom.main awaken --strict",
    )
    awaken.add_argument(
        "--strict",
        action="store_true",
        help="Exit 3 when Ollama or the selected model is not ready.",
    )

    subparsers.add_parser(
        "chat",
        parents=[common],
        help="Start an interactive, streamed conversation.",
        description=(
            "Start an interactive session. Responses stream from the local "
            "model, history stays in memory for this session only, and slash "
            "commands manage memories and mood. /help lists them."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m phantom.main chat\n"
            "  python -m phantom.main chat --model gemma3:4b"
        ),
    )

    inspect = subparsers.add_parser(
        "inspect",
        parents=[common],
        help="Inspect a file or directory (engine not implemented yet).",
        description=(
            "Validate and resolve PATH. The inspection engine is not implemented "
            "in this build, so the command reports that plainly and reads nothing."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n  python -m phantom.main inspect .",
    )
    inspect.add_argument("path", metavar="PATH", help="File or directory to inspect.")

    remember = subparsers.add_parser(
        "remember",
        parents=[common],
        help="Archive one explicit memory.",
        description=(
            "Store exact user supplied text in the local SQLite archive. The "
            "memory is labelled as user supplied and never sent anywhere."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='example:\n  python -m phantom.main remember "I prefer pytest."',
    )
    remember.add_argument("text", metavar="TEXT", help="Exact memory text to store.")

    memories = subparsers.add_parser(
        "memories",
        parents=[common],
        help="List archived memories with IDs and timestamps.",
        description="List stored memories, newest first, with short IDs and local timestamps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n  python -m phantom.main memories --limit 10",
    )
    memories.add_argument(
        "--limit",
        "-n",
        metavar="N",
        type=_positive_int,
        default=None,
        help="Show at most N memories.",
    )

    forget = subparsers.add_parser(
        "forget",
        parents=[common],
        help="Delete one memory after confirmation.",
        description=(
            "Show the selected memory and delete only that record after an "
            "explicit confirmation. A unique ID prefix is accepted. Use --yes "
            "to skip the prompt in a non-interactive context."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m phantom.main forget 1a2b3c4d\n"
            "  python -m phantom.main forget 1a2b3c4d --yes"
        ),
    )
    forget.add_argument(
        "memory_id",
        metavar="ID",
        help="Full memory ID or a unique prefix of at least 4 hex characters.",
    )
    forget.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt.",
    )

    status = subparsers.add_parser(
        "status",
        parents=[common],
        help="Report model connectivity, configuration, and archive health.",
        description=(
            "Perform real checks: Ollama reachability, installed model presence, "
            "database integrity, schema version, memory count, and mood."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m phantom.main status\n"
            "  python -m phantom.main status --json"
        ),
    )
    status.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of tables.",
    )

    subparsers.add_parser(
        "exorcise",
        parents=[common],
        help="Close the session without deleting anything.",
        description=(
            "End the experience with an atmospheric shutdown summary. This "
            "command never deletes files or memories."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n  python -m phantom.main exorcise",
    )

    return parser


def _load_handler(command: str) -> Callable[[CommandContext, Any], int]:
    module = importlib.import_module(_COMMAND_MODULES[command])
    handler = getattr(module, "run", None)
    if not callable(handler):
        raise RuntimeError(f"Command module for {command!r} has no run handler.")
    return handler


def _translate(exc: Exception) -> CliError | None:
    if isinstance(exc, CliError):
        return exc
    if isinstance(exc, ExternalServiceError):
        return UsageError(str(exc), hint=exc.hint)
    if isinstance(exc, BrainConfigError):
        return UsageError(str(exc), hint=exc.hint)
    if isinstance(exc, BrainError):
        return DependencyError(str(exc), hint=exc.hint)
    if isinstance(exc, (InvalidMemoryError, MemoryNotFoundError, AmbiguousMemoryError)):
        return UsageError(str(exc), hint=exc.hint)
    if isinstance(exc, PhantomMemoryError):
        return DatabaseError(str(exc), hint=exc.hint)
    return None


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: Any | None = None,
    stderr: Any | None = None,
    env: Mapping[str, str] | None = None,
    brain_factory: Callable[[Any], Brain] | None = None,
    input_func: Callable[[str], str] | None = None,
) -> int:
    """Parse arguments, dispatch one command, and return an exit code.

    The injection points exist so tests can run every command without a real
    Ollama service or an interactive terminal.
    """

    parser = build_parser()
    args = parser.parse_args(argv)

    # Rich is imported after parsing so --help works even if the renderer
    # dependency is missing.
    from phantom.render import Renderer

    values = dict(os.environ) if env is None else dict(env)
    plain = bool(getattr(args, "plain", False))
    no_color = (
        plain
        or "NO_COLOR" in values
        or values.get("TERM", "").strip().lower() == "dumb"
    )
    renderer = Renderer(
        plain=plain,
        no_color=no_color,
        file=stdout,
        error_file=stderr,
    )

    debug = bool(getattr(args, "debug", False))
    try:
        settings = settings_from_args(args, env=values, stdout=stdout)
        debug = debug or settings.debug
        factory = brain_factory or (lambda current: Brain(current.brain))
        ctx = CommandContext(
            settings=settings,
            renderer=renderer,
            brain_factory=factory,
            input_func=input_func or input,
        )
        return _load_handler(args.command)(ctx, args)
    except KeyboardInterrupt:
        renderer.error(
            "Interrupted. No partial result was committed.",
            title="Interrupted",
        )
        return EXIT_INTERRUPTED
    except Exception as exc:
        translated = _translate(exc)
        if translated is not None:
            renderer.error(
                translated.message,
                hint=translated.hint,
                title=translated.title,
            )
            return translated.exit_code
        if debug:
            traceback.print_exc(file=stderr if stderr is not None else sys.stderr)
        renderer.error(
            "An unexpected error occurred.",
            hint=(
                f"{type(exc).__name__}: {exc}. "
                "Re-run with --debug for a traceback."
            ),
        )
        return 1


__all__ = ["build_parser", "main"]
