"""``chat`` - an interactive, streamed conversation."""

from __future__ import annotations

from typing import Any

from core.brain import BrainError

from phantom.chat import ChatSession
from phantom.context import CommandContext
from phantom.storage import open_store


def run(ctx: CommandContext, args: Any) -> int:
    brain = ctx.make_brain()
    try:
        with open_store(ctx.settings) as store:
            try:
                with ctx.renderer.progress("Checking the local model"):
                    brain.ensure_ready()
            except BrainError as exc:
                ctx.renderer.error(str(exc), title="Local model unavailable")
                return 3

            session = ChatSession(
                brain=brain,
                store=store,
                settings=ctx.settings,
                renderer=ctx.renderer,
                input_func=ctx.input_func,
            )
            return session.run()
    finally:
        brain.close()
