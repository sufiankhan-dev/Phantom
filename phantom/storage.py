"""Shared helpers for opening the archive and recording grounded mood."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from core.memory import MemoryStore, PhantomMemoryError
from core.personality import MoodEngine, MoodEvent, MoodState

from phantom.config import Settings


@contextmanager
def open_store(settings: Settings) -> Iterator[MemoryStore]:
    """Open and initialize the configured archive, then close it."""

    store = MemoryStore(settings.db_path)
    store.initialize()
    try:
        yield store
    finally:
        store.close()


def load_mood(store: MemoryStore) -> MoodState:
    """Load persisted mood, falling back to the neutral default."""

    try:
        data = store.load_mood()
    except PhantomMemoryError:
        return MoodState()
    if not data:
        return MoodState()
    try:
        return MoodState.from_dict(data)
    except (TypeError, ValueError):
        return MoodState()


def record_mood(
    store: MemoryStore,
    engine: MoodEngine,
    event: MoodEvent | str,
    *,
    files: int = 0,
    todos: int = 0,
    detail: str | None = None,
    renderer: object | None = None,
) -> MoodState:
    """Apply a real event, persist it, and never fail the command for it.

    Mood is auxiliary state. A write failure is reported as a warning but the
    primary operation is not undone.
    """

    state = engine.record(event, files=files, todos=todos, detail=detail)
    try:
        # Refuse to overwrite a mood record that exists but cannot be read.
        store.load_mood()
        store.save_mood(state.as_dict())
        store.record_mood_event(MoodEvent(event).value, detail)
    except PhantomMemoryError as exc:
        warning = getattr(renderer, "warning", None)
        if callable(warning):
            warning(f"Mood state could not be saved: {exc}")
    return state
