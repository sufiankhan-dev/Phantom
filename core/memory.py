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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
MAX_MEMORY_CHARS = 4000
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

_REQUIRED_TABLES = {
    "schema_meta",
    "memories",
    "interpretations",
    "mood_state",
    "mood_events",
}
_ID_PREFIX_RE = re.compile(r"^[0-9a-fA-F-]{4,36}$")
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

    @property
    def short_id(self) -> str:
        return self.id[:8]

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "short_id": self.short_id,
            "content": self.content,
            "origin": self.origin,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


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
            conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
            version = SCHEMA_VERSION
            tables = _table_names(conn)

        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"The database schema is version {version}, newer than this build ({SCHEMA_VERSION}).",
                hint="Upgrade PHANTOM or use a different database path.",
            )
        if version < SCHEMA_VERSION:
            raise SchemaVersionError(
                f"The database schema is version {version}; this build expects {SCHEMA_VERSION}.",
                hint="No automatic migration exists yet. Use a different database path.",
            )
        if not _REQUIRED_TABLES.issubset(tables):
            missing = ", ".join(sorted(_REQUIRED_TABLES - tables))
            raise SchemaVersionError(
                f"The database schema is incomplete (missing: {missing}).",
                hint="Use a different database path; PHANTOM will not guess at repairs.",
            )

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

    def remember(self, content: str) -> MemoryRecord:
        """Store one explicit user-supplied memory."""

        text = _validate_content(content)
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
        )

    def list_memories(self, limit: int | None = None) -> list[MemoryRecord]:
        """Return user memories, newest first."""

        _validate_limit(limit)
        query = (
            "SELECT id, content, origin, created_at, updated_at "
            "FROM memories ORDER BY created_at DESC, rowid DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        try:
            rows = self._connect().execute(query, params).fetchall()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError(
                "The memory archive could not be read.",
                hint="Check the database path and run a health check.",
            ) from exc
        return [_row_to_memory(row) for row in rows]

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
                return _row_to_memory(row)

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
        return _row_to_memory(rows[0])

    def find_memories(self, prefix: str) -> list[MemoryRecord]:
        """Return every memory matching a prefix, without deleting anything."""

        value = _validate_id(prefix)
        try:
            rows = self._connect().execute(
                "SELECT id, content, origin, created_at, updated_at "
                "FROM memories WHERE id LIKE ? ORDER BY created_at DESC, rowid DESC",
                (f"{value}%",),
            ).fetchall()
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The memory lookup failed.") from exc
        return [_row_to_memory(row) for row in rows]

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

    def count_memories(self) -> int:
        try:
            row = self._connect().execute("SELECT COUNT(*) AS n FROM memories").fetchone()
            return int(row["n"]) if row is not None else 0
        except sqlite3.Error as exc:
            raise MemoryDatabaseError("The memory count could not be read.") from exc

    def search_memories(
        self,
        query: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[MemoryRecord]:
        """Find memories with deterministic keyword overlap.

        This is deliberately simple: no embeddings, no hidden model calls, and
        no AI-generated memories. Ties are broken by recency.
        """

        _validate_limit(limit)
        if not isinstance(query, str):
            raise InvalidMemoryError("Search text must be a string.")
        tokens = {token for token in _TOKEN_RE.findall(query.lower()) if len(token) > 1}
        records = self.list_memories(limit=MAX_SEARCH_SCAN)
        if not tokens:
            return records[:limit]

        scored: list[tuple[int, int, MemoryRecord]] = []
        for index, record in enumerate(records):
            haystack = record.content.lower()
            score = sum(2 for token in tokens if token in haystack)
            if score:
                scored.append((score, -index, record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in scored[:limit]]

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
            return MemoryHealth(
                path=self.path,
                ok=integrity == "ok",
                schema_version=version,
                memory_count=memory_count,
                interpretation_count=interpretation_count,
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
    "MemoryDatabaseError",
    "MemoryHealth",
    "MemoryNotFoundError",
    "MemoryRecord",
    "MemoryStore",
    "PhantomMemoryError",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "default_db_path",
    "utc_now",
]
