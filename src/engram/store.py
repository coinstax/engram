"""EventStore — SQLite persistence layer with WAL mode and FTS5 search."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engram.models import Event, EventType, QueryFilter

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL
                CHECK(event_type IN ('discovery','decision','warning','mutation','outcome')),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL
                CHECK(length(content) <= 2000),
    scope       TEXT,
    related_ids TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_agent     ON events(agent_id);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content,
    scope,
    content=events,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, content, scope)
    VALUES (new.rowid, new.content, new.scope);
END;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class EventStore:
    """SQLite-backed event store with FTS5 full-text search."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._migrated = False

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        if not self._migrated:
            self._migrate()
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def initialize(self) -> None:
        """Create tables, indexes, and FTS5 triggers."""
        self.conn.executescript(SCHEMA_SQL)

    def _migrate(self) -> None:
        """Run schema migrations if needed."""
        self._migrated = True
        # Check if meta table exists (may not for brand-new DBs before initialize)
        tables = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        if not tables:
            return  # DB not yet initialized, nothing to migrate

        current = self.get_meta("schema_version")
        version = int(current) if current else 1

        if version < 2:
            # Add related_ids column if missing
            columns = {
                row[1] for row in
                self._conn.execute("PRAGMA table_info(events)").fetchall()
            }
            if "related_ids" not in columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN related_ids TEXT"
                )
            self.set_meta("schema_version", str(SCHEMA_VERSION))

    @staticmethod
    def _generate_id() -> str:
        return f"evt-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        scope_raw = row["scope"]
        scope = json.loads(scope_raw) if scope_raw else None
        # Handle both v1.0 (no related_ids column) and v1.1 databases
        try:
            related_raw = row["related_ids"]
            related = json.loads(related_raw) if related_raw else None
        except (IndexError, KeyError):
            related = None
        return Event(
            id=row["id"],
            timestamp=row["timestamp"],
            event_type=EventType(row["event_type"]),
            agent_id=row["agent_id"],
            content=row["content"],
            scope=scope,
            related_ids=related,
        )

    def insert(self, event: Event) -> Event:
        """Insert a single event. Generates id/timestamp if not set."""
        if not event.id:
            event.id = self._generate_id()
        if not event.timestamp:
            event.timestamp = self._now_iso()

        scope_json = json.dumps(event.scope) if event.scope else None
        related_json = json.dumps(event.related_ids) if event.related_ids else None

        with self.conn:
            self.conn.execute(
                "INSERT INTO events (id, timestamp, event_type, agent_id, content, scope, related_ids) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event.id, event.timestamp, event.event_type.value,
                 event.agent_id, event.content, scope_json, related_json),
            )
        return event

    def insert_batch(self, events: list[Event]) -> int:
        """Insert multiple events in a single transaction. Returns count."""
        rows = []
        for e in events:
            if not e.id:
                e.id = self._generate_id()
            if not e.timestamp:
                e.timestamp = self._now_iso()
            scope_json = json.dumps(e.scope) if e.scope else None
            related_json = json.dumps(e.related_ids) if e.related_ids else None
            rows.append((e.id, e.timestamp, e.event_type.value,
                         e.agent_id, e.content, scope_json, related_json))

        with self.conn:
            self.conn.executemany(
                "INSERT INTO events (id, timestamp, event_type, agent_id, content, scope, related_ids) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)

    def query_fts(self, text: str, limit: int = 50) -> list[Event]:
        """Full-text search via FTS5 MATCH."""
        sql = (
            "SELECT e.* FROM events e "
            "JOIN events_fts ON events_fts.rowid = e.rowid "
            "WHERE events_fts MATCH ? "
            "ORDER BY e.timestamp DESC LIMIT ?"
        )
        rows = self.conn.execute(sql, (text, limit)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def query_structured(self, filters: QueryFilter) -> list[Event]:
        """Query with optional FTS + structured filters."""
        if filters.text and not filters.event_types and not filters.agent_id \
                and not filters.scope and not filters.since:
            return self.query_fts(filters.text, filters.limit)

        conditions = []
        params: list = []

        if filters.text:
            conditions.append(
                "e.rowid IN (SELECT rowid FROM events_fts WHERE events_fts MATCH ?)"
            )
            params.append(filters.text)

        if filters.event_types:
            placeholders = ",".join("?" for _ in filters.event_types)
            conditions.append(f"e.event_type IN ({placeholders})")
            params.extend(t.value for t in filters.event_types)

        if filters.agent_id:
            conditions.append("e.agent_id = ?")
            params.append(filters.agent_id)

        if filters.scope:
            conditions.append("e.scope LIKE ?")
            params.append(f"%{filters.scope}%")

        if filters.since:
            conditions.append("e.timestamp >= ?")
            params.append(filters.since)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT e.* FROM events e WHERE {where} ORDER BY e.timestamp DESC LIMIT ?"
        params.append(filters.limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def recent_by_type(self, event_type: EventType, limit: int = 10,
                       since: str | None = None, scope: str | None = None) -> list[Event]:
        """Fetch recent events of a specific type."""
        conditions = ["event_type = ?"]
        params: list = [event_type.value]

        if since:
            conditions.append("timestamp >= ?")
            params.append(since)

        if scope:
            conditions.append("scope LIKE ?")
            params.append(f"%{scope}%")

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def query_related(self, event_id: str, limit: int = 50) -> list[Event]:
        """Find all events that reference the given event_id in their related_ids."""
        sql = (
            "SELECT * FROM events "
            "WHERE related_ids LIKE ? "
            "ORDER BY timestamp DESC LIMIT ?"
        )
        rows = self.conn.execute(sql, (f'%"{event_id}"%', limit)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def count(self) -> int:
        """Total event count."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()
        return row["cnt"]

    def last_activity(self) -> str | None:
        """Timestamp of most recent event."""
        row = self.conn.execute(
            "SELECT timestamp FROM events ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"] if row else None

    def get_meta(self, key: str) -> str | None:
        """Read from meta table."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Write to meta table (upsert)."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
