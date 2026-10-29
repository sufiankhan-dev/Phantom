"""The small runtime bundle passed to every command handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.brain import Brain

    from phantom.config import Settings
    from phantom.render import Renderer


@dataclass(slots=True)
class CommandContext:
    """Settings plus the injected presentation and model dependencies.

    Tests replace ``brain_factory`` and ``input_func`` so no real Ollama
    service or interactive terminal is required.
    """

    settings: "Settings"
    renderer: "Renderer"
    brain_factory: Callable[["Settings"], "Brain"]
    input_func: Callable[[str], str]

    def make_brain(self) -> "Brain":
        """Create a model client without contacting it yet."""

        return self.brain_factory(self.settings)
