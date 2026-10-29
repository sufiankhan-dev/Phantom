from __future__ import annotations

from types import SimpleNamespace

from core.brain import Brain, BrainConfig
from core.memory import MemoryStore
from core.personality import MemoryNote, MoodEngine, MoodEvent, MoodState, build_system_prompt


class RecordingClient:
    def __init__(self):
        self.calls = []

    def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model="qwen3:8b")])

    def show(self, model):
        return SimpleNamespace(capabilities=["completion"])

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return iter(
            [
                SimpleNamespace(
                    message=SimpleNamespace(content="A grounded answer.", thinking=None),
                    done=True,
                    eval_count=3,
                    eval_duration=1_000_000_000,
                )
            ]
        )


def test_user_memories_reach_the_prompt_but_interpretations_do_not(tmp_path):
    store = MemoryStore(tmp_path / "phantom.db")
    store.initialize()
    try:
        memory = store.remember("I prefer pytest and short answers.")
        store.record_interpretation(
            "The user probably hates explanations.",
            memory_id=memory.id,
        )

        relevant = store.search_memories("pytest")
        assert [item.id for item in relevant] == [memory.id]

        mood = MoodEngine().record(MoodEvent.MEMORY_SAVED)
        prompt = build_system_prompt(
            mood,
            [MemoryNote(item.id, item.content, item.created_at) for item in relevant],
        )
        assert "I prefer pytest and short answers." in prompt
        assert "The user probably hates explanations." not in prompt
        assert "USER-SUPPLIED" in prompt

        client = RecordingClient()
        brain = Brain(BrainConfig(model="qwen3:8b"), client=client)
        result = brain.complete_chat(
            [{"role": "user", "content": "What do you know about me?"}],
            system=prompt,
        )
        assert result.text == "A grounded answer."
        assert "I prefer pytest and short answers." in client.calls[0]["messages"][0]["content"]
        assert "The user probably hates explanations." not in client.calls[0]["messages"][0]["content"]
        assert "tools" not in client.calls[0]
    finally:
        store.close()


def test_mood_persists_through_memory_store(tmp_path):
    path = tmp_path / "phantom.db"
    first = MemoryStore(path)
    first.initialize()
    mood = MoodEngine()
    mood.record(MoodEvent.INSPECTION_COMPLETED, files=3, todos=1)
    first.save_mood(mood.state.as_dict())
    first.close()

    second = MemoryStore(path)
    second.initialize()
    try:
        loaded = second.load_mood()
        assert loaded is not None
        restored = MoodState.from_dict(loaded)
        assert restored.label == mood.state.label
        assert restored.evidence == mood.state.evidence
    finally:
        second.close()
