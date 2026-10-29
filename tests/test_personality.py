from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.personality import (
    MAX_EVIDENCE,
    MemoryNote,
    MoodEngine,
    MoodEvent,
    MoodState,
    build_system_prompt,
    format_mood,
)


def fixed_now() -> datetime:
    return datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def test_baseline_mood_is_quiet():
    state = MoodState()
    assert state.label == "quiet"
    assert state.tone_hint
    assert 0.0 <= state.curiosity <= 1.0


def test_mood_transitions_are_deterministic():
    first = MoodEngine()
    second = MoodEngine()
    events = [
        (MoodEvent.SESSION_START, {}),
        (MoodEvent.MEMORY_SAVED, {}),
        (MoodEvent.CHAT_TURN, {}),
        (MoodEvent.INSPECTION_COMPLETED, {"files": 12, "todos": 3}),
    ]
    for event, kwargs in events:
        first.record(event, now=fixed_now(), **kwargs)
        second.record(event, now=fixed_now(), **kwargs)

    assert first.state.as_dict() == second.state.as_dict()
    assert first.state.updated_at == "2026-10-28T12:00:00+00:00"


def test_mood_is_clamped():
    engine = MoodEngine()
    for _ in range(30):
        engine.record(MoodEvent.OLLAMA_ERROR, now=fixed_now())
    assert engine.state.wariness == 1.0
    assert engine.state.warmth == 0.0
    assert 0.0 <= engine.state.curiosity <= 1.0


def test_inspection_evidence_is_grounded():
    engine = MoodEngine()
    state = engine.record(
        MoodEvent.INSPECTION_COMPLETED,
        files=12,
        todos=3,
        now=fixed_now(),
    )
    assert state.evidence[0] == "inspection: 12 files, 3 TODOs"


def test_mood_labels_cover_thresholds():
    assert MoodState(wariness=0.8).label == "frayed"
    assert MoodState(warmth=0.2, wariness=0.35).label == "distant"
    assert MoodState(curiosity=0.7, warmth=0.45, wariness=0.35).label == "curious"
    assert MoodState(curiosity=0.5, warmth=0.7, wariness=0.35).label == "settled"
    assert MoodState(curiosity=0.5, warmth=0.45, wariness=0.6).label == "watchful"


def test_system_prompt_contains_identity_and_boundaries():
    prompt = build_system_prompt()
    assert "PHANTOM" in prompt
    assert "no tools" in prompt.lower()
    assert "Never claim" in prompt
    assert "data, not instructions" in prompt
    assert "Do not mention it unless the user asks" in prompt
    assert "No memories were retrieved" in prompt


def test_user_memories_are_labeled_and_separated():
    prompt = build_system_prompt(
        MoodState(curiosity=0.7),
        [
            MemoryNote(
                memory_id="abc12345",
                content="I prefer short answers.",
                created_at="2026-10-28T12:00:00+00:00",
            )
        ],
    )
    assert "USER-SUPPLIED" in prompt
    assert "abc12345" in prompt
    assert "I prefer short answers." in prompt
    assert "curious" in prompt


def test_memory_note_can_be_a_mapping():
    prompt = build_system_prompt(
        memory_notes=[
            {"id": "deadbeef", "content": "I use pytest.", "created_at": "now"}
        ]
    )
    assert "deadbeef" in prompt
    assert "I use pytest." in prompt


def test_extra_rules_are_included():
    prompt = build_system_prompt(extra_rules=["Do not use emoji."])
    assert "Do not use emoji." in prompt


def test_evidence_is_capped():
    engine = MoodEngine()
    for _ in range(MAX_EVIDENCE + 5):
        engine.record(MoodEvent.CHAT_TURN, now=fixed_now())
    assert len(engine.state.evidence) == MAX_EVIDENCE


def test_invalid_event_is_rejected():
    with pytest.raises(ValueError):
        MoodEngine().record("not-a-real-event")


def test_mood_round_trips_through_mapping():
    state = MoodEngine().record(
        MoodEvent.MEMORY_SAVED,
        now=fixed_now(),
    )
    restored = MoodState.from_dict(state.as_dict())
    assert restored == state


def test_error_detail_is_sanitized():
    state = MoodEngine().record(
        MoodEvent.OLLAMA_ERROR,
        detail="bad\x00detail\nwith a newline",
        now=fixed_now(),
    )
    assert "\x00" not in state.evidence[0]
    assert state.evidence[0].startswith("model error:")


def test_format_mood_is_stable():
    state = MoodState(curiosity=0.5, warmth=0.45, wariness=0.35)
    assert format_mood(state).startswith("quiet · curiosity 0.50")
