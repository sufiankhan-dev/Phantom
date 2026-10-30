"""Settings resolution for the command line.

Precedence is command line > environment > defaults. Model and host
validation lives in :class:`core.brain.BrainConfig`; this module only decides
which values to pass to it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from core.brain import BrainConfig
from core.memory import default_db_path


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything a command needs to know about the current invocation."""

    brain: BrainConfig
    db_path: Path | str
    plain: bool = False
    animation: bool = True
    debug: bool = False

    @property
    def db_display(self) -> str:
        return str(self.db_path)


def settings_from_args(
    args: Any,
    *,
    env: Mapping[str, str] | None = None,
    stdout: Any | None = None,
) -> Settings:
    """Resolve command line arguments and environment into settings.

    Absent options are not present on ``args`` at all (the parser uses
    ``argparse.SUPPRESS``), so a global flag placed before or after the
    subcommand is handled identically.
    """

    values = dict(os.environ) if env is None else dict(env)
    base = BrainConfig.from_env(values)

    overrides: dict[str, Any] = {}
    model = getattr(args, "model", None)
    if model is not None:
        overrides["model"] = model
    host = getattr(args, "host", None)
    if host is not None:
        overrides["host"] = host
    timeout = getattr(args, "timeout", None)
    if timeout is not None:
        overrides["timeout"] = timeout
    if getattr(args, "allow_remote_ollama", False):
        overrides["allow_remote"] = True

    brain = replace(base, **overrides) if overrides else base

    db_argument = getattr(args, "db", None)
    if db_argument is not None and str(db_argument).strip():
        db_path: Path | str = (
            ":memory:"
            if str(db_argument).strip() == ":memory:"
            else Path(db_argument).expanduser()
        )
    else:
        db_path = default_db_path(values)

    plain = bool(getattr(args, "plain", False))
    stream = stdout if stdout is not None else sys.stdout
    is_interactive = bool(getattr(stream, "isatty", lambda: False)())
    term = values.get("TERM", "").strip().lower()
    animation = (
        bool(getattr(args, "animation", True))
        and is_interactive
        and not plain
        and "NO_COLOR" not in values
        and term != "dumb"
    )

    return Settings(
        brain=brain,
        db_path=db_path,
        plain=plain,
        animation=animation,
        debug=bool(getattr(args, "debug", False)),
    )
