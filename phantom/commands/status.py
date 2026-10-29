"""``status`` - real model, configuration, and archive report."""

from __future__ import annotations

import json
from typing import Any

from phantom.context import CommandContext
from phantom.storage import load_mood, open_store
from phantom.views import render_status


def run(ctx: CommandContext, args: Any) -> int:
    with open_store(ctx.settings) as store:
        health = store.health()
        mood = load_mood(store)
        brain = ctx.make_brain()
        try:
            model_status = brain.status()
        finally:
            brain.close()

    settings = ctx.settings
    if getattr(args, "json", False):
        payload = {
            "model": {
                "name": settings.brain.model,
                "host": settings.brain.host,
                "timeout_seconds": settings.brain.timeout,
                "num_ctx": settings.brain.num_ctx,
                "num_predict": settings.brain.num_predict,
                "temperature": settings.brain.temperature,
                "allow_remote": settings.brain.allow_remote,
            },
            "ollama": {
                "reachable": model_status.reachable,
                "model_available": model_status.model_available,
                "models": list(model_status.models),
                "error": model_status.error,
            },
            "database": {
                "path": health.path,
                "ok": health.ok,
                "schema_version": health.schema_version,
                "memories": health.memory_count,
                "interpretations": health.interpretation_count,
                "error": health.error,
            },
            "mood": mood.as_dict(),
        }
        ctx.renderer.write_raw(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        render_status(ctx.renderer, settings, model_status, health, mood)

    if not health.ok:
        return 4
    if not model_status.reachable:
        return 3
    if not model_status.model_available:
        return 3
    return 0
