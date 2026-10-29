from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

import pytest

from core.memory import (
    AmbiguousMemoryError,
    InvalidMemoryError,
    MAX_MEMORY_CHARS,
    MemoryDatabaseError,
    MemoryNotFoundError,
    MemoryStore,
    SchemaVersionError,
    default_db_path,
)


@pytest.fixture()
def store(tmp_path):
    memory = MemoryStore(tmp_path / "phantom.db")
    memory.initialize()
    yield memory
    memory.close()


def test_remember_list_and_count(store):
    first = store.remember("I prefer pytest over unittest.")
    second = store.remember("My editor is Neovim.")

    assert uuid.UUID(first.id)
    assert first.short_id == first.id[:8]
    assert first.created_at.endswith("+00:00")
    datetime.fromisoformat(first.created_at)
    assert store.count_memories() == 2

    listed = store.list_memories()
    assert [item.id for item in listed] == [second.id, first.id]
    assert listed[0].origin == "user"


def test_persistence_across_connections(tmp_path):
    path = tmp_path / "phantom.db"
    first = MemoryStore(path)
    first.initialize()
    record = first.remember("Persist across processes.")
    first.close()

    second = MemoryStore(path)
    second.initialize()
    try:
        assert [item.id for item in second.list_memories()] == [record.id]
        assert second.get_memory(record.short_id).content == "Persist across processes."
    finally:
        second.close()


def test_unique_prefix_lookup_and_forget(store):
    record = store.remember("Delete only this one.")
    assert store.get_memory(record.short_id).id == record.id
    removed = store.forget(record.short_id)
    assert removed.id == record.id
    assert store.list_memories() == []


def test_ambiguous_prefix_refuses_lookup_and_delete(store):
    conn = store._connect()
    ids = [
        "abcd1111-1111-4111-8111-111111111111",
        "abcd2222-2222-4222-8222-222222222222",
    ]
    with conn:
        for memory_id in ids:
            conn.execute(
                "INSERT INTO memories (id, content, origin, created_at, updated_at) "
                "VALUES (?, ?, 'user', ?, ?)",
                (memory_id, f"content for {memory_id}", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )

    with pytest.raises(AmbiguousMemoryError) as exc:
        store.get_memory("abcd")
    assert len(exc.value.candidates) == 2

    with pytest.raises(AmbiguousMemoryError):
        store.forget("abcd")
    assert store.count_memories() == 2


def test_missing_and_invalid_ids(store):
    with pytest.raises(MemoryNotFoundError):
        store.get_memory("deadbeef")
    with pytest.raises(InvalidMemoryError):
        store.get_memory("not-a-memory-id")
    with pytest.raises(InvalidMemoryError):
        store.get_memory("abc")


def test_empty_and_oversized_text_rejected(store):
    for value in ("", "   ", "\n\t"):
        with pytest.raises(InvalidMemoryError):
            store.remember(value)
    with pytest.raises(InvalidMemoryError):
        store.remember("x" * (MAX_MEMORY_CHARS + 1))
    assert store.count_memories() == 0


def test_sql_injection_shaped_content_is_data(store):
    payload = "'); DROP TABLE memories; --"
    record = store.remember(payload)
    assert store.count_memories() == 1
    assert store.list_memories()[0].content == payload
    assert store.get_memory(record.id).content == payload
    assert store.health().ok is True


def test_interpretations_are_separate_from_user_memories(store):
    memory = store.remember("I prefer short answers.")
    interpretation = store.record_interpretation(
        "The user probably dislikes explanations.",
        memory_id=memory.id,
    )

    assert interpretation.source == "ai"
    assert interpretation.memory_id == memory.id
    assert [item.id for item in store.list_memories()] == [memory.id]
    assert [item.id for item in store.list_interpretations()] == [interpretation.id]
    assert store.search_memories("explanations") == []
    assert store.count_memories() == 1


def test_interpretation_source_is_validated(store):
    with pytest.raises(InvalidMemoryError):
        store.record_interpretation("bad source", source="user")
    with pytest.raises(MemoryNotFoundError):
        store.record_interpretation("orphan", memory_id="deadbeef")


def test_search_is_deterministic_and_relevant(store):
    store.remember("I prefer Python for scripting.")
    store.remember("My cat is named Miso.")
    results = store.search_memories("python")
    assert len(results) == 1
    assert "Python" in results[0].content
    assert store.search_memories("nonexistentterm") == []


def test_limit_validation(store):
    store.remember("one")
    with pytest.raises(InvalidMemoryError):
        store.list_memories(0)
    with pytest.raises(InvalidMemoryError):
        store.list_memories(-1)
    with pytest.raises(InvalidMemoryError):
        store.search_memories("one", limit=0)


def test_schema_version_and_health(store):
    store.remember("health check")
    health = store.health()
    assert health.ok is True
    assert health.schema_version == 1
    assert health.memory_count == 1
    assert health.interpretation_count == 0
    assert health.path.endswith("phantom.db")


def test_newer_schema_is_rejected(tmp_path):
    path = tmp_path / "newer.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionError):
        MemoryStore(path).initialize()


def test_schema_meta_mismatch_is_rejected(tmp_path):
    path = tmp_path / "mismatch.db"
    store = MemoryStore(path)
    store.initialize()
    store.remember("this row must survive")
    store.close()

    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionError):
        MemoryStore(path).initialize()


def test_missing_schema_meta_marker_is_rejected(tmp_path):
    path = tmp_path / "marker.db"
    store = MemoryStore(path)
    store.initialize()
    store.close()

    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM schema_meta WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionError):
        MemoryStore(path).initialize()


def test_unversioned_existing_database_is_rejected(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE legacy (id INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionError):
        MemoryStore(path).initialize()


def test_corrupt_database_is_reported_not_overwritten(tmp_path):
    path = tmp_path / "corrupt.db"
    original = b"this is not a sqlite database"
    path.write_bytes(original)

    store = MemoryStore(path)
    health = store.health()
    assert health.ok is False
    assert health.error
    with pytest.raises(MemoryDatabaseError):
        store.initialize()
    assert path.read_bytes() == original


def test_malformed_record_is_reported(store):
    conn = store._connect()
    with conn:
        conn.execute(
            "INSERT INTO memories (id, content, origin, created_at, updated_at) "
            "VALUES (?, ?, 'user', ?, ?)",
            (
                "11111111-1111-4111-8111-111111111111",
                "broken timestamp",
                "not-a-date",
                "not-a-date",
            ),
        )
    with pytest.raises(MemoryDatabaseError):
        store.list_memories()


def test_naive_timestamps_are_rejected(store):
    conn = store._connect()
    with conn:
        conn.execute(
            "INSERT INTO memories (id, content, origin, created_at, updated_at) "
            "VALUES (?, ?, 'user', ?, ?)",
            (
                "22222222-2222-4222-8222-222222222222",
                "not UTC",
                "2026-01-01T00:00:00",
                "2026-01-01T00:00:00",
            ),
        )
    with pytest.raises(MemoryDatabaseError):
        store.list_memories()


def test_no_conversation_history_table(store):
    conn = sqlite3.connect(store.path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert "conversations" not in tables
    assert "messages" not in tables


def test_mood_and_events_round_trip(store):
    store.save_mood(
        {
            "curiosity": 0.6,
            "warmth": 0.5,
            "wariness": 0.4,
            "evidence": ["memory archived"],
        }
    )
    loaded = store.load_mood()
    assert loaded["curiosity"] == 0.6
    assert loaded["evidence"] == ["memory archived"]

    store.record_mood_event("memory_saved", "one memory")
    events = store.recent_mood_events()
    assert events[0]["event"] == "memory_saved"
    assert events[0]["detail"] == "one memory"


def test_default_db_path_from_environment(monkeypatch):
    monkeypatch.setenv("PHANTOM_DB", "custom/phantom.db")
    assert str(default_db_path()) == str(default_db_path({"PHANTOM_DB": "custom/phantom.db"}))
    assert default_db_path({"PHANTOM_DB": ":memory:"}) == ":memory:"
    assert str(default_db_path({"PHANTOM_HOME": "C:/tmp/phantom-home"})).endswith(
        "phantom.db"
    )
