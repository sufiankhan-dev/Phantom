from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

import pytest

from core.memory import (
    AmbiguousMemoryError,
    InvalidMemoryError,
    MAX_MEMORY_CHARS,
    MAX_TAGS_PER_MEMORY,
    MemoryDatabaseError,
    MemoryNotFoundError,
    MemoryStore,
    SCHEMA_VERSION,
    SchemaVersionError,
    default_db_path,
    normalize_tag,
    normalize_tags,
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
    assert health.schema_version == SCHEMA_VERSION
    assert health.memory_count == 1
    assert health.interpretation_count == 0
    assert health.tag_count == 0
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
    conn.execute(
        "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
        (str(SCHEMA_VERSION + 1),),
    )
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


# -- tags --------------------------------------------------------------


def test_tags_are_normalized_deduplicated_and_sorted(store):
    record = store.remember(
        "I prefer pytest.",
        tags=["Python", "#CLI", "python"],
    )

    assert record.tags == ("cli", "python")
    assert store.get_memory(record.short_id).tags == ("cli", "python")
    listed = store.list_memories()
    assert listed[0].tags == ("cli", "python")
    assert record.as_dict()["tags"] == ["cli", "python"]


def test_tag_validation_rejects_unsafe_or_oversized_values():
    assert normalize_tag("#Python") == "python"
    assert normalize_tags(["b", "a", "b"]) == ("a", "b")
    assert normalize_tags(None) == ()
    assert normalize_tags("Python") == ("python",)

    for bad in ("", "   ", "#", "two words", "bad!", "a" * 33, "café"):
        with pytest.raises(InvalidMemoryError):
            normalize_tag(bad)

    too_many = [f"tag{index}" for index in range(MAX_TAGS_PER_MEMORY + 1)]
    with pytest.raises(InvalidMemoryError):
        normalize_tags(too_many)


def test_tag_filtering_counts_and_search(store):
    pytest_memory = store.remember(
        "I prefer pytest.",
        tags=["python", "testing"],
    )
    store.remember("Deploy with kubectl.", tags=["devops"])

    assert [item.id for item in store.list_memories(tag="python")] == [
        pytest_memory.id
    ]
    assert store.count_memories(tag="python") == 1
    assert store.count_memories() == 2
    assert store.search_memories("pytest", tag="python")[0].id == pytest_memory.id
    assert store.list_memories(tag="missing") == []


def test_search_finds_a_tag_even_when_content_does_not_match(store):
    tagged = store.remember("A deployment note.", tags=["kubernetes"])
    store.remember("Unrelated content.")

    results = store.search_memories("kubernetes")
    assert [item.id for item in results] == [tagged.id]


def test_add_and_remove_tags_never_changes_content(store):
    record = store.remember("Exact words.", tags=["one"])

    updated = store.tag_memory(record.short_id, ["Two", "#three"])
    assert updated.tags == ("one", "three", "two")
    assert updated.content == record.content

    trimmed = store.tag_memory(record.id, ["one", "missing"], remove=True)
    assert trimmed.tags == ("three", "two")
    assert trimmed.content == record.content

    unchanged = store.tag_memory(record.id, ["three"])
    assert unchanged.tags == ("three", "two")


def test_tag_limit_is_enforced_without_partial_writes(store):
    full = [f"tag{index}" for index in range(MAX_TAGS_PER_MEMORY)]
    record = store.remember("At the limit.", tags=full)

    with pytest.raises(InvalidMemoryError):
        store.tag_memory(record.id, ["one-more"])
    assert store.get_memory(record.id).tags == tuple(sorted(full))

    with pytest.raises(InvalidMemoryError):
        store.remember("Too many.", tags=[*full, "one-more"])
    assert store.count_memories() == 1


def test_list_tags_counts_and_orders_by_use(store):
    store.remember("First.", tags=["python", "cli"])
    store.remember("Second.", tags=["python"])

    assert [(item.tag, item.count) for item in store.list_tags()] == [
        ("python", 2),
        ("cli", 1),
    ]


def test_forget_removes_its_tags_only(store):
    removed = store.remember("Delete me.", tags=["gone", "shared"])
    survivor = store.remember("Keep me.", tags=["shared"])

    store.forget(removed.id)

    assert store.get_memory(survivor.id).tags == ("shared",)
    assert [(item.tag, item.count) for item in store.list_tags()] == [
        ("shared", 1)
    ]


def test_tags_persist_across_connections(tmp_path):
    path = tmp_path / "tagged.db"
    first = MemoryStore(path)
    first.initialize()
    record = first.remember("Carry this.", tags=["portable"])
    first.close()

    second = MemoryStore(path)
    second.initialize()
    try:
        loaded = second.get_memory(record.id)
        assert loaded.tags == ("portable",)
        assert second.count_memories(tag="portable") == 1
    finally:
        second.close()


def test_incomplete_version_one_archive_is_not_migrated(tmp_path):
    path = tmp_path / "broken-v1.db"
    original = MemoryStore(path)
    original.initialize()
    original.close()

    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE memory_tags")
    conn.execute("DROP TABLE mood_events")
    conn.execute("PRAGMA user_version = 1")
    conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionError):
        MemoryStore(path).initialize()

    conn = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert "memory_tags" not in tables
    assert "mood_events" not in tables


def test_version_one_archive_is_upgraded_without_losing_memories(tmp_path):
    path = tmp_path / "v1.db"
    original = MemoryStore(path)
    original.initialize()
    record = original.remember("A row from schema version one.")
    original.close()

    # Recreate the on-disk shape of a version 1 archive.
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE memory_tags")
    conn.execute("PRAGMA user_version = 1")
    conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    upgraded = MemoryStore(path)
    upgraded.initialize()
    try:
        health = upgraded.health()
        assert health.ok is True
        assert health.schema_version == SCHEMA_VERSION
        restored = upgraded.get_memory(record.id)
        assert restored.content == "A row from schema version one."
        assert restored.tags == ()
        assert upgraded.tag_memory(restored.id, ["migrated"]).tags == ("migrated",)
    finally:
        upgraded.close()
