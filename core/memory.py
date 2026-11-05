"""SQLite persistence for PHANTOM's explicit memories.

Design rules:

* Only user-supplied memories live in ``memories``. AI interpretations live in
  a separate table and are never returned by memory recall.
* Conversation history is deliberately not persisted.
* Every user value is bound with a parameterized query.
* The database is never repaired, truncated, or deleted automatically.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 2
MAX_MEMORY_CHARS = 4000
MAX_TAGS_PER_MEMORY = 8
MAX_TAG_LENGTH = 32
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_SCAN = 500

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    origin TEXT NOT NULL DEFAULT 'user' CHECK (origin = 'user'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at DESC);

CREATE TABLE IF NOT EXISTS interpretations (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    source TEXT NOT NULL CHECK (source IN ('ai', 'system')),
    memory_id TEXT REFERENCES memories(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interpretations_created_at
    ON interpretations (created_at DESC);

CREATE TABLE IF NOT EXISTS mood_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mood_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL CHECK (length(trim(event)) > 0),
    detail TEXT,
    created_at TEXT NOT NULL
);
"""

_TAGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_tags (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tag TEXT NOT NULL CHECK (length(tag) BETWEEN 1 AND 32),
    PRIMARY KEY (memory_id, tag)
);
"""

_TAGS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_memory_tags_tag
    ON memory_tags (tag);
"""

_REQUIRED_TABLES = {
    "schema_meta",
    "memories",
    "memory_tags",
    "interpretations",
    "mood_state",
    "mood_events",
}
_V1_REQUIRED_TABLES = _REQUIRED_TABLES - {"memory_tags"}
_ID_PREFIX_RE = re.compile(r"^[0-9a-fA-F-]{4,36}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


class PhantomMemoryError(Exception):
    """Base class for memory failures with an actionable recovery hint."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message} {self.hint}"
        return self.message


class MemoryDatabaseError(PhantomMemoryError):
    """The SQLite database could not be opened, read, or written."""


class SchemaVersionError(MemoryDatabaseError):
    """The database schema is unknown, newer, or incomplete."""


class InvalidMemoryError(PhantomMemoryError):
    """A memory operation received invalid input."""


class MemoryNotFoundError(PhantomMemoryError):
    """No memory matched the supplied identifier."""


class AmbiguousMemoryError(PhantomMemoryError):
    """A memory prefix matched more than one record."""

    def __init__(self, prefix: str, candidates: Sequence[str]) -> None:
        self.prefix = prefix
        self.candidates = tuple(candidates)
        shown = ", ".join(self.candidates[:5])
        super().__init__(
            f"Memory prefix {prefix!r} is ambiguous; it matches {len(self.candidates)} records.",
            hint=f"Use a longer identifier. Matches: {shown}",
        )


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """An explicit, user-supplied memory."""

    id: str
    content: str
    created_at: str
    updated_at: str
    origin: str = "user"
    tags: tuple[str, ...] = ()

    @property
    def short_id(self) -> str:
        return self.id[:8]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "short_id": self.short_id,
            "content": self.content,
            "origin": self.origin,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class TagCount:
    """One tag and how many memories carry it."""

    tag: str
    count: int

    def as_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "count": self.count}


@dataclass(frozen=True, slots=True)
class InterpretationRecord:
    """An AI- or system-generated interpretation, stored separately."""

    id: str
    content: str
    source: str
    created_at: str
    memory_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryHealth:
    """Result of a database health check."""

    path: str
    ok: bool
    schema_version: int | None
    memory_count: int
    interpretation_count: int
    tag_count: int = 0
    error: str | None = None


def default_db_path(env: Mapping[str, str] | None = None) -> Path | str:
    """Return the configured database path without creating anything.

    ``PHANTOM_DB`` wins. Otherwise ``PHANTOM_HOME`` (default ``~/.phantom``)
    contains ``phantom.db``. ``:memory:`` is supported for tests.
    """

    values = os.environ if env is None else env
    explicit = (values.get("PHANTOM_DB") or "").strip()
    if explicit:
        return ":memory:" if explicit == ":memory:" else Path(explicit).expanduser()
    home = Path(values.get("PHANTOM_HOME") or (Path.home() / ".phantom")).expanduser()
    return home / "phantom.db"


class MemoryStore(AbstractContextManager["MemoryStore"]):
    """A small, explicit SQLite memory store.

    The connection is opened lazily by :meth:`initialize` or the first
    operation. Call :meth:`close` when finished, or use the store as a context
    manager.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        chosen = db_path if db_path is not None else default_db_path()
        if str(chosen) == ":memory:":
            self.db_path: Path | str = ":memory:"
        else:
            self.db_path = Path(chosen).expanduser()
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "MemoryStore":
        self.initialize()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @property
    def path(self) -> str:
        return str(self.db_path)

    def initialize(self) -> "MemoryStore":
        """Open the database and create/validate the schema."""

        self._connect()
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        try:
            if self.db_path != ":memory:":
                path = Path(self.db_path)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            if self.db_path != ":memory:":
                conn.execute("PRAGMA journal_mode = WAL").fetchone()
            self._conn = conn
            self._initialize_schema(conn)
            self._harden_permissions()
            return conn
        except PhantomMemoryError:
            self._safe_close()
            raise
        except (sqlite3.Error, OSError) as exc:
            self._safe_close()
            raise MemoryDatabaseError(
                f"Could not open the memory database at {self.path}.",
                hint=(
                    "Check that the path is writable and is a SQLite database. "
                    "PHANTOM will not overwrite or repair an existing file."
                ),
            ) from exc

    def _safe_close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def _initialize_schema(self, conn: sqlite3.Connection) -> None:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = _table_names(conn)

        if version == 0:
            if tables:
                raise SchemaVersionError(
                    f"The database at {self.path} has tables but no schema version.",
                    hint=(
                        "It may be from an older or unrelated program. "
                        "Move it aside and retry; PHANTOM will not modify it."
                    ),
                )
            conn.executescript(_SCHEMA_SQL)
            conn.executescript(_TAGS_TABLE_SQL)
            conn.executescript(_TAGS_INDEX_SQL)
            _write_schema_version(conn, SCHEMA_VERSION)
            conn.commit()
            version = SCHEMA_VERSION
            tables = _table_names(conn)

        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"The database schema is version {version}, newer than this build ({SCHEMA_VERSION}).",
                hint="Upgrade PHANTOM or use a different database path.",
            )

        # Validate both version markers before touching anything, so a
        # mismatched archive is never migrated on a guess.
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            ("schema_version",),
        ).fetchone()
        if row is None:
            raise SchemaVersionError(
                "The database is missing its schema_meta version marker.",
                hint="Use a different database path; PHANTOM will not guess at repairs.",
            )
        try:
            metadata_version = int(row["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaVersionError(
                "The database schema_meta version marker is malformed.",
                hint="Use a different database path; PHANTOM will not modify it.",
            ) from exc
        if metadata_version != version:
            raise SchemaVersionError(
                "The database version markers disagree "
                f"(user_version={version}, schema_meta={metadata_version}).",
                hint="Use a different database path; PHANTOM will not modify it.",
            )

        if version < SCHEMA_VERSION:
            # Refuse to "upgrade" a version 1 archive that is already missing
            # tables: a migration must never be used as a repair.
            if not _V1_REQUIRED_TABLES.issubset(tables):
                missing = ", ".join(sorted(_V1_REQUIRED_TABLES - tables))
                raise SchemaVersionError(
                    f"The database schema is incomplete (missing: {missing}).",
                    hint=(
                        "Use a different database path; PHANTOM will not guess "
                        "at repairs or migrate an incomplete archive."
                    ),
                )
            version = self._migrate_schema(conn, version)
            tables = _table_names(conn)

        if not _REQUIRED_TABLES.issubset(tables):
            missing = ", ".join(sorted(_REQUIRED_TABLES - tables))
            raise SchemaVersionError(
                f"The database schema is incomplete (missing: {missing}).",
                hint="Use a different database path; PHANTOM will not guess at repairs.",
            )

    def _migrate_schema(self, conn: sqlite3.Connection, version: int) -> int:
        """Upgrade an older archive in place, additively and atomically.

        Only schema version 1 is known, and its upgrade merely adds the
        ``memory_tags`` table and index. Existing rows are never rewritten or
        removed. If anything fails, the transaction is rolled back and the
        original archive is left untouched.
        """

        if version != 1:
            raise SchemaVersionError(
                f"The database schema is version {version}; this build expects {SCHEMA_VERSION}.",
                hint="Use a different database path; no migration exists for that version.",
            )

        try:
            with conn:
                conn.execute(_TAGS_TABLE_SQL)
                conn.execute(_TAGS_INDEX_SQL)
                _write_schema_version(conn, SCHEMA_VERSION)
        except sqlite3.Error as exc:
            raise SchemaVersionError(
                f"The archive at {self.path} could not be upgraded to schema "
                f"version {SCHEMA_VERSION}.",
                hint=(
                    "Nothing was changed. Check that the file is writable and "
                    "not corrupt, or use a different database path."
                ),
            ) from exc
        return SCHEMA_VERSION

    def _harden_permissions(self) -> None:
        if os.name != "posix" or self.db_path == ":memory:":
            return
        for suffix in ("", "-wal", "-shm"):
            sidecar = Path(f"{self.db_path}{suffix}")
            if not sidecar.exists():
                continue
            try:
                os.chmod(sidecar, 0o600)
            except OSError:
                # Permission hardening is best-effort; do not make the store unusable.
                pass

    def remember(
        self,
        content: str,
        *,
        tags: Sequence[str] | None = None,
    ) -> MemoryRecord:
        """Store one explicit user-supplied memory with optional tags."""

        text = _validate_content(content)
        normalized = normalize_tags(tags)
        memory_id = str(uuid.uuid4())
        now = utc_now()
        try:
            conn = self._connect()
            with conn:
                conn.execute(
                    "INSERT INTO memories (id, content, origin, created_at, updated_at) "
                    "VALUES (?, ?, 'user', ?, ?)",
                    (memory_id, text, now, now),
                )
                _insert_tags(conn, memory_id, normalized)
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The memory could not be saved.",
                hint="Check that the database is writable and not corrupt.",
            ) from exc
        return MemoryRecord(
            id=memory_id,
            content=text,
            created_at=now,
            updated_at=now,
            tags=normalized,
        )

    def list_memories(
        self,
        limit: int | None = None,
        *,
        tag: str | None = None,
    ) -> list[MemoryRecord]:
        """Return user memories, newest first, optionally filtered by tag."""

        _validate_limit(limit)
        normalized_tag = normalize_tag(tag) if tag is not None else None
        if normalized_tag is None:
            query = (
                "SELECT id, content, origin, created_at, updated_at "
                "FROM memories ORDER BY created_at DESC, rowid DESC"
            )
            params: tuple[Any, ...] = ()
        else:
            query = (
                "SELECT m.id, m.content, m.origin, m.created_at, m.updated_at "
                "FROM memories AS m "
                "JOIN memory_tags AS t ON t.memory_id = m.id "
                "WHERE t.tag = ? "
                "ORDER BY m.created_at DESC, m.rowid DESC"
            )
            params = (normalized_tag,)
        if limit is not None:
            query += " LIMIT ?"
            params = (*params, limit)
        try:
            conn = self._connect()
            rows = conn.execute(query, params).fetchall()
            return _attach_tags(conn, rows)
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The memory archive could not be read.",
                hint="Check the database path and run a health check.",
            ) from exc

    def get_memory(self, memory_id: str) -> MemoryRecord:
        """Find one memory by full ID or unique prefix."""

        prefix = _validate_id(memory_id)
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT id, content, origin, created_at, updated_at "
                "FROM memories WHERE id = ?",
                (prefix,),
            ).fetchone()
            if row is not None:
                return _attach_tags(conn, [row])[0]

            rows = conn.execute(
                "SELECT id, content, origin, created_at, updated_at "
                "FROM memories WHERE id LIKE ? ORDER BY created_at DESC, rowid DESC",
                (f"{prefix}%",),
            ).fetchall()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The memory could not be looked up.",
                hint="Check the database path and run a health check.",
            ) from exc

        if not rows:
            raise MemoryNotFoundError(
                f"No memory matches {memory_id!r}.",
                hint="Run the memories command to list available identifiers.",
            )
        if len(rows) > 1:
            raise AmbiguousMemoryError(prefix, [str(row["id"]) for row in rows])
        return _attach_tags(conn, [rows[0]])[0]

    def find_memories(self, prefix: str) -> list[MemoryRecord]:
        """Return every memory matching a prefix, without deleting anything."""

        value = _validate_id(prefix)
        try:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, content, origin, created_at, updated_at "
                "FROM memories WHERE id LIKE ? ORDER BY created_at DESC, rowid DESC",
                (f"{value}%",),
            ).fetchall()
            return _attach_tags(conn, rows)
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The memory lookup failed.") from exc

    def forget(self, memory_id: str) -> MemoryRecord:
        """Delete one explicitly identified memory and return it.

        A prefix is accepted only when it is unique. Nothing is ever deleted by
        a wildcard or a bulk operation.
        """

        record = self.get_memory(memory_id)
        try:
            conn = self._connect()
            with conn:
                cursor = conn.execute("DELETE FROM memories WHERE id = ?", (record.id,))
                if cursor.rowcount != 1:
                    raise MemoryNotFoundError(
                        f"Memory {record.id!r} disappeared before it could be removed."
                    )
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The memory could not be removed.",
                hint="Check the database path and run a health check.",
            ) from exc
        return record

    def count_memories(self, *, tag: str | None = None) -> int:
        """Count memories, optionally only those carrying one tag."""

        normalized_tag = normalize_tag(tag) if tag is not None else None
        try:
            conn = self._connect()
            if normalized_tag is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM memory_tags WHERE tag = ?",
                    (normalized_tag,),
                ).fetchone()
            return int(row["n"]) if row is not None else 0
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The memory count could not be read.") from exc

    def search_memories(
        self,
        query: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        *,
        tag: str | None = None,
    ) -> list[MemoryRecord]:
        """Find memories with deterministic keyword overlap.

        This is deliberately simple: no embeddings, no hidden model calls, and
        no AI-generated memories. Content matches score higher than tag
        matches, and ties are broken by recency.
        """

        _validate_limit(limit)
        if not isinstance(query, str):
            raise InvalidMemoryError("Search text must be a string.")
        tokens = {token for token in _TOKEN_RE.findall(query.lower()) if len(token) > 1}
        records = self.list_memories(limit=MAX_SEARCH_SCAN, tag=tag)
        if not tokens:
            return records[:limit]

        scored: list[tuple[int, int, MemoryRecord]] = []
        for index, record in enumerate(records):
            haystack = record.content.lower()
            score = sum(4 for token in tokens if token in haystack)
            score += sum(
                3
                for token in tokens
                if any(token in tag_name for tag_name in record.tags)
            )
            if score:
                scored.append((score, -index, record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in scored[:limit]]

    def tag_memory(
        self,
        memory_id: str,
        tags: Sequence[str],
        *,
        remove: bool = False,
    ) -> MemoryRecord:
        """Add or remove tags on one explicitly identified memory.

        Adding is capped at :data:`MAX_TAGS_PER_MEMORY`; removing accepts any
        currently stored tag. A tag that is already present, or already absent,
        is reported as no change rather than treated as an error.
        """

        record = self.get_memory(memory_id)
        normalized = normalize_tags(tags)
        if remove:
            requested = set(normalized)
            try:
                conn = self._connect()
                with conn:
                    if requested:
                        placeholders = ",".join("?" for _ in requested)
                        conn.execute(
                            f"DELETE FROM memory_tags WHERE memory_id = ? "
                            f"AND tag IN ({placeholders})",
                            (record.id, *sorted(requested)),
                        )
            except sqlite3.Error as exc:
                raise MemoryDatabaseError(
                    "The tags could not be removed.",
                    hint="Check the database path and run a health check.",
                ) from exc
            return self.get_memory(record.id)

        merged = tuple(sorted(set(record.tags) | set(normalized)))
        if len(merged) > MAX_TAGS_PER_MEMORY:
            raise InvalidMemoryError(
                f"A memory can hold at most {MAX_TAGS_PER_MEMORY} tags "
                f"(this would store {len(merged)}).",
                hint=(
                    "Remove a tag first, or choose a broader tag that "
                    "covers several narrower ones."
                ),
            )
        try:
            conn = self._connect()
            with conn:
                _insert_tags(conn, record.id, normalized)
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The tags could not be saved.",
                hint="Check the database path and run a health check.",
            ) from exc
        return self.get_memory(record.id)

    def list_tags(self) -> list[TagCount]:
        """Return every tag with its memory count, most used first."""

        try:
            rows = self._connect().execute(
                "SELECT tag, COUNT(*) AS n FROM memory_tags "
                "GROUP BY tag ORDER BY n DESC, tag ASC"
            ).fetchall()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The tags could not be read.",
                hint="Check the database path and run a health check.",
            ) from exc
        return [TagCount(tag=str(row["tag"]), count=int(row["n"])) for row in rows]

    def record_interpretation(
        self,
        content: str,
        *,
        memory_id: str | None = None,
        source: str = "ai",
    ) -> InterpretationRecord:
        """Store a model/system interpretation separately from user memories."""

        text = _validate_content(content)
        if source not in {"ai", "system"}:
            raise InvalidMemoryError("Interpretation source must be 'ai' or 'system'.")
        linked_id: str | None = None
        if memory_id is not None:
            linked_id = self.get_memory(memory_id).id

        interpretation_id = str(uuid.uuid4())
        now = utc_now()
        try:
            conn = self._connect()
            with conn:
                conn.execute(
                    "INSERT INTO interpretations "
                    "(id, content, source, memory_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (interpretation_id, text, source, linked_id, now),
                )
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The interpretation could not be saved.") from exc
        return InterpretationRecord(
            id=interpretation_id,
            content=text,
            source=source,
            created_at=now,
            memory_id=linked_id,
        )

    def list_interpretations(self, limit: int | None = None) -> list[InterpretationRecord]:
        """Return AI/system interpretations. Never mixed into memory recall."""

        _validate_limit(limit)
        query = (
            "SELECT id, content, source, memory_id, created_at "
            "FROM interpretations ORDER BY created_at DESC, rowid DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        try:
            rows = self._connect().execute(query, params).fetchall()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("Interpretations could not be read.") from exc
        return [
            InterpretationRecord(
                id=str(row["id"]),
                content=str(row["content"]),
                source=str(row["source"]),
                created_at=str(row["created_at"]),
                memory_id=str(row["memory_id"]) if row["memory_id"] is not None else None,
            )
            for row in rows
        ]

    def save_mood(self, state: Mapping[str, Any]) -> None:
        """Persist the small mood state as JSON."""

        if not isinstance(state, Mapping):
            raise InvalidMemoryError("Mood state must be a mapping.")
        try:
            payload = json.dumps(dict(state), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise InvalidMemoryError("Mood state must be JSON-serializable.") from exc
        now = utc_now()
        try:
            conn = self._connect()
            with conn:
                conn.execute(
                    "INSERT INTO mood_state (id, state_json, updated_at) VALUES (1, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "state_json = excluded.state_json, updated_at = excluded.updated_at",
                    (payload, now),
                )
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The mood state could not be saved.") from exc

    def load_mood(self) -> dict[str, Any] | None:
        """Load the persisted mood state, or ``None`` on a fresh database."""

        try:
            row = self._connect().execute(
                "SELECT state_json FROM mood_state WHERE id = 1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The mood state could not be read.") from exc
        if row is None:
            return None
        try:
            data = json.loads(row["state_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise MemoryDatabaseError(
                "The persisted mood state is malformed.",
                hint="Use a different database path; PHANTOM will not rewrite it.",
            ) from exc
        if not isinstance(data, dict):
            raise MemoryDatabaseError("The persisted mood state is not an object.")
        return data

    def record_mood_event(self, event: str, detail: str | None = None) -> None:
        """Record one grounded mood event for later inspection."""

        if not isinstance(event, str) or not event.strip():
            raise InvalidMemoryError("Mood event must be a non-empty string.")
        if detail is not None and not isinstance(detail, str):
            raise InvalidMemoryError("Mood event detail must be text or None.")
        try:
            conn = self._connect()
            with conn:
                conn.execute(
                    "INSERT INTO mood_events (event, detail, created_at) VALUES (?, ?, ?)",
                    (event.strip(), detail, utc_now()),
                )
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The mood event could not be saved.") from exc

    def recent_mood_events(self, limit: int = 20) -> list[dict[str, Any]]:
        _validate_limit(limit)
        try:
            rows = self._connect().execute(
                "SELECT event, detail, created_at FROM mood_events "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("Mood events could not be read.") from exc
        return [
            {
                "event": str(row["event"]),
                "detail": str(row["detail"]) if row["detail"] is not None else None,
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def health(self) -> MemoryHealth:
        """Return a non-fatal database health report."""

        try:
            conn = self._connect()
            integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
            integrity = str(integrity_row[0]) if integrity_row is not None else "unknown"
            version_row = conn.execute("PRAGMA user_version").fetchone()
            version = int(version_row[0]) if version_row is not None else None
            memory_count = self.count_memories()
            interpretation_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM interpretations").fetchone()["n"]
            )
            tag_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM memory_tags").fetchone()["n"]
            )
            return MemoryHealth(
                path=self.path,
                ok=integrity == "ok",
                schema_version=version,
                memory_count=memory_count,
                interpretation_count=interpretation_count,
                tag_count=tag_count,
                error=None if integrity == "ok" else integrity,
            )
        except PhantomMemoryError as exc:
            return MemoryHealth(
                path=self.path,
                ok=False,
                schema_version=None,
                memory_count=0,
                interpretation_count=0,
                error=str(exc),
            )
        except sqlite3.Error as exc:
            return MemoryHealth(
                path=self.path,
                ok=False,
                schema_version=None,
                memory_count=0,
                interpretation_count=0,
                error=f"Database health check failed: {exc}",
            )


def utc_now() -> str:
    """Return a stable UTC ISO-8601 timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _write_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """Write both schema version markers together."""

    number = int(version)
    conn.execute(f"PRAGMA user_version = {number}")
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("schema_version", str(number)),
    )


def _insert_tags(
    conn: sqlite3.Connection,
    memory_id: str,
    tags: Sequence[str],
) -> None:
    for tag in tags:
        conn.execute(
            "INSERT OR IGNORE INTO memory_tags (memory_id, tag) VALUES (?, ?)",
            (memory_id, tag),
        )


def _attach_tags(
    conn: sqlite3.Connection,
    rows: Sequence[sqlite3.Row],
) -> list[MemoryRecord]:
    """Convert rows to records and load their tags in bounded batches."""

    records = [_row_to_memory(row) for row in rows]
    if not records:
        return records
    tags_by_id = _tags_for(conn, [record.id for record in records])
    return [
        replace(record, tags=tags_by_id.get(record.id, ())) for record in records
    ]


def _tags_for(
    conn: sqlite3.Connection,
    memory_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    found: dict[str, list[str]] = {}
    unique = sorted(set(memory_ids))
    # Stay well below SQLite's default host-parameter limit.
    for start in range(0, len(unique), 400):
        chunk = unique[start : start + 400]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT memory_id, tag FROM memory_tags "
            f"WHERE memory_id IN ({placeholders})",
            tuple(chunk),
        ).fetchall()
        for row in rows:
            found.setdefault(str(row["memory_id"]), []).append(str(row["tag"]))
    return {
        memory_id: tuple(sorted(tags)) for memory_id, tags in found.items()
    }


def normalize_tag(value: str) -> str:
    """Normalize one tag, raising :class:`InvalidMemoryError` when invalid.

    Tags are lowercase, at most :data:`MAX_TAG_LENGTH` characters, and use
    letters, digits, hyphens, and underscores. A leading ``#`` is accepted so
    the CLI and chat can display tags that way.
    """

    if not isinstance(value, str):
        raise InvalidMemoryError("A tag must be text.")
    raw = value.strip()
    if raw.startswith("#"):
        raw = raw[1:]
    tag = raw.lower()
    if not tag:
        raise InvalidMemoryError(
            "A tag cannot be empty.",
            hint="Use a short label such as `python` or `client-work`.",
        )
    if len(tag) > MAX_TAG_LENGTH:
        raise InvalidMemoryError(
            f"Tag {value!r} is too long ({len(tag)} characters; "
            f"limit {MAX_TAG_LENGTH}).",
            hint="Use a short, reusable label.",
        )
    if not _TAG_RE.fullmatch(tag):
        raise InvalidMemoryError(
            f"{value!r} is not a valid tag.",
            hint=(
                "Tags start with a letter or digit and may contain lowercase "
                "letters, digits, hyphens, and underscores."
            ),
        )
    return tag


def normalize_tags(values: Sequence[str] | str | None) -> tuple[str, ...]:
    """Normalize and deduplicate a group of tags, sorted for stable output."""

    if values is None:
        return ()
    if isinstance(values, str):
        candidates: Sequence[Any] = (values,)
    else:
        try:
            candidates = list(iter(values))
        except TypeError as exc:
            raise InvalidMemoryError("Tags must be a sequence of strings.") from exc

    normalized = tuple(sorted({normalize_tag(value) for value in candidates}))
    if len(normalized) > MAX_TAGS_PER_MEMORY:
        raise InvalidMemoryError(
            f"A memory can hold at most {MAX_TAGS_PER_MEMORY} tags "
            f"(received {len(normalized)}).",
            hint="Choose a few broad tags instead of many narrow ones.",
        )
    return normalized


def _validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise InvalidMemoryError("Memory text must be a string.")
    text = content.strip()
    if not text:
        raise InvalidMemoryError(
            "Memory text cannot be empty.",
            hint="Provide the exact text you want PHANTOM to remember.",
        )
    if len(text) > MAX_MEMORY_CHARS:
        raise InvalidMemoryError(
            f"Memory text is too long ({len(text)} characters; limit {MAX_MEMORY_CHARS}).",
            hint="Store a shorter, more focused memory.",
        )
    return text


def _validate_id(memory_id: str) -> str:
    if not isinstance(memory_id, str):
        raise InvalidMemoryError("Memory ID must be a string.")
    value = memory_id.strip().lower()
    if not _ID_PREFIX_RE.fullmatch(value):
        raise InvalidMemoryError(
            f"{memory_id!r} is not a valid memory ID or prefix.",
            hint="Use at least 4 hexadecimal characters from the listed ID.",
        )
    return value


def _validate_limit(limit: int | None) -> None:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        raise InvalidMemoryError("Limit must be a positive integer or None.")


def _row_to_memory(row: sqlite3.Row) -> MemoryRecord:
    try:
        memory_id = str(row["id"])
        content = str(row["content"])
        origin = str(row["origin"])
        created_at = str(row["created_at"])
        updated_at = str(row["updated_at"])
        uuid.UUID(memory_id)
        if origin != "user":
            raise ValueError(f"unexpected origin {origin!r}")
        if not content.strip():
            raise ValueError("empty content")
        _parse_timestamp(created_at)
        _parse_timestamp(updated_at)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise MemoryDatabaseError(
            "A memory record is malformed.",
            hint=(
                "The database was not modified. Run a health check and restore "
                "from a known-good copy if needed."
            ),
        ) from exc
    return MemoryRecord(
        id=memory_id,
        content=content,
        origin=origin,
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed


__all__ = [
    "AmbiguousMemoryError",
    "DEFAULT_SEARCH_LIMIT",
    "InterpretationRecord",
    "InvalidMemoryError",
    "MAX_MEMORY_CHARS",
    "MAX_TAGS_PER_MEMORY",
    "MAX_TAG_LENGTH",
    "MemoryDatabaseError",
    "MemoryHealth",
    "MemoryNotFoundError",
    "MemoryRecord",
    "MemoryStore",
    "PhantomMemoryError",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "TagCount",
    "default_db_path",
    "normalize_tag",
    "normalize_tags",
    "utc_now",
]
