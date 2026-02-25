"""EventStore — SQLite persistence layer with WAL mode and FTS5 search."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engram.models import Checkpoint, Event, EventType, QueryFilter, Session

SCHEMA_VERSION = 5

STALE_SESSION_HOURS = 24

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
    related_ids TEXT,
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','resolved','superseded')),
    priority    TEXT NOT NULL DEFAULT 'normal'
                CHECK(priority IN ('critical','high','normal','low')),
    resolved_reason TEXT,
    superseded_by_event_id TEXT,
    session_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_agent     ON events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_status    ON events(status);

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

CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK(status IN ('active','paused','completed')),
    models        TEXT NOT NULL,
    system_prompt TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    summary       TEXT
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id    TEXT NOT NULL REFERENCES conversations(id),
    role       TEXT NOT NULL
               CHECK(role IN ('system','user','assistant')),
    sender     TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_messages_conv
    ON conversation_messages(conv_id, id);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    focus       TEXT NOT NULL,
    scope       TEXT,
    description TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(ended_at)
    WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
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
            self.set_meta("schema_version", "2")

        if version < 3:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id            TEXT PRIMARY KEY,
                    topic         TEXT NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'active'
                                  CHECK(status IN ('active','paused','completed')),
                    models        TEXT NOT NULL,
                    system_prompt TEXT,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL,
                    summary       TEXT
                );

                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    conv_id    TEXT NOT NULL REFERENCES conversations(id),
                    role       TEXT NOT NULL
                               CHECK(role IN ('system','user','assistant')),
                    sender     TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conv_messages_conv
                    ON conversation_messages(conv_id, id);
            """)
            self.set_meta("schema_version", "3")

        if version < 4:
            # Add event lifecycle and priority columns
            columns = {
                row[1] for row in
                self._conn.execute("PRAGMA table_info(events)").fetchall()
            }
            if "status" not in columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
                )
            if "priority" not in columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'"
                )
            if "resolved_reason" not in columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN resolved_reason TEXT"
                )
            if "superseded_by_event_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN superseded_by_event_id TEXT"
                )
            # Add index for status-based queries (briefing filters)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)"
            )
            self.set_meta("schema_version", "4")

        if version < 5:
            # Add sessions table
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id          TEXT PRIMARY KEY,
                    agent_id    TEXT NOT NULL,
                    focus       TEXT NOT NULL,
                    scope       TEXT,
                    description TEXT,
                    started_at  TEXT NOT NULL,
                    ended_at    TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(ended_at)
                    WHERE ended_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
            """)
            # Add session_id column to events
            columns = {
                row[1] for row in
                self._conn.execute("PRAGMA table_info(events)").fetchall()
            }
            if "session_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE events ADD COLUMN session_id TEXT"
                )
            self.set_meta("schema_version", "5")

    @staticmethod
    def _generate_id() -> str:
        return f"evt-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        scope_raw = row["scope"]
        scope = json.loads(scope_raw) if scope_raw else None
        # Handle older schema versions gracefully
        try:
            related_raw = row["related_ids"]
            related = json.loads(related_raw) if related_raw else None
        except (IndexError, KeyError):
            related = None
        try:
            status = row["status"]
        except (IndexError, KeyError):
            status = "active"
        try:
            priority = row["priority"]
        except (IndexError, KeyError):
            priority = "normal"
        try:
            resolved_reason = row["resolved_reason"]
        except (IndexError, KeyError):
            resolved_reason = None
        try:
            superseded_by = row["superseded_by_event_id"]
        except (IndexError, KeyError):
            superseded_by = None
        try:
            session_id = row["session_id"]
        except (IndexError, KeyError):
            session_id = None
        return Event(
            id=row["id"],
            timestamp=row["timestamp"],
            event_type=EventType(row["event_type"]),
            agent_id=row["agent_id"],
            content=row["content"],
            scope=scope,
            related_ids=related,
            status=status,
            priority=priority,
            resolved_reason=resolved_reason,
            superseded_by=superseded_by,
            session_id=session_id,
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
                "INSERT INTO events (id, timestamp, event_type, agent_id, content, scope, related_ids, status, priority, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event.id, event.timestamp, event.event_type.value,
                 event.agent_id, event.content, scope_json, related_json,
                 event.status, event.priority, event.session_id),
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
                         e.agent_id, e.content, scope_json, related_json,
                         e.status, e.priority, e.session_id))

        with self.conn:
            self.conn.executemany(
                "INSERT INTO events (id, timestamp, event_type, agent_id, content, scope, related_ids, status, priority, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                and not filters.scope and not filters.since and not filters.related_to:
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

        if filters.related_to:
            conditions.append(
                "(e.related_ids LIKE ? OR e.related_ids LIKE ?)"
            )
            params.append(f'%"{filters.related_to}"]%')
            params.append(f'%"{filters.related_to}",%')

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT e.* FROM events e WHERE {where} ORDER BY e.timestamp DESC LIMIT ?"
        params.append(filters.limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def recent_by_type(self, event_type: EventType, limit: int = 10,
                       since: str | None = None, scope: str | None = None,
                       status: str | None = "active") -> list[Event]:
        """Fetch recent events of a specific type. Defaults to active only."""
        conditions = ["event_type = ?"]
        params: list = [event_type.value]

        if status:
            conditions.append("status = ?")
            params.append(status)

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

    def recent_resolved(self, since: str, limit: int = 10) -> list[Event]:
        """Fetch recently resolved events within a time window."""
        sql = (
            "SELECT * FROM events WHERE status = 'resolved' AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?"
        )
        rows = self.conn.execute(sql, (since, limit)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def update_status(self, event_id: str, status: str,
                      resolved_reason: str | None = None,
                      superseded_by: str | None = None) -> Event:
        """Update an event's lifecycle status."""
        if status not in ("active", "resolved", "superseded"):
            raise ValueError(f"Invalid status: {status}. Must be active/resolved/superseded.")

        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Event not found: {event_id}")

        with self.conn:
            self.conn.execute(
                "UPDATE events SET status = ?, resolved_reason = ?, superseded_by_event_id = ? "
                "WHERE id = ?",
                (status, resolved_reason, superseded_by, event_id),
            )

        updated = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return self._row_to_event(updated)

    def get_event(self, event_id: str) -> Event | None:
        """Fetch a single event by ID."""
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        return self._row_to_event(row) if row else None

    def query_related(self, event_id: str, limit: int = 50) -> list[Event]:
        """Find all events that reference the given event_id in their related_ids."""
        # Match exact ID in JSON array: "id" followed by ] or ,
        sql = (
            "SELECT * FROM events "
            "WHERE (related_ids LIKE ? OR related_ids LIKE ?) "
            "ORDER BY timestamp DESC LIMIT ?"
        )
        # Match "id"] or "id",  — covers last element and non-last element
        rows = self.conn.execute(
            sql,
            (f'%"{event_id}"]%', f'%"{event_id}",%', limit),
        ).fetchall()
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

    # --- Session methods ---

    @staticmethod
    def _generate_session_id() -> str:
        return f"sess-{uuid.uuid4().hex[:8]}"

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        scope_raw = row["scope"]
        scope = json.loads(scope_raw) if scope_raw else None
        return Session(
            id=row["id"],
            agent_id=row["agent_id"],
            focus=row["focus"],
            scope=scope,
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            description=row["description"],
        )

    def insert_session(self, session: Session) -> Session:
        """Insert a new session. Generates id/started_at if not set."""
        if not session.id:
            session.id = self._generate_session_id()
        if not session.started_at:
            session.started_at = self._now_iso()

        scope_json = json.dumps(session.scope) if session.scope else None

        with self.conn:
            self.conn.execute(
                "INSERT INTO sessions (id, agent_id, focus, scope, description, started_at, ended_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session.id, session.agent_id, session.focus, scope_json,
                 session.description, session.started_at, session.ended_at),
            )
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Fetch a single session by ID."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return self._row_to_session(row) if row else None

    def end_session(self, session_id: str, ended_at: str | None = None) -> Session:
        """End an active session."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Session not found: {session_id}")
        if row["ended_at"] is not None:
            raise ValueError(f"Session {session_id} is already ended.")

        ended_at = ended_at or self._now_iso()
        with self.conn:
            self.conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ?",
                (ended_at, session_id),
            )

        updated = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return self._row_to_session(updated)

    def get_active_session(self, agent_id: str) -> Session | None:
        """Get the most recent active session for an agent."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE agent_id = ? AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(self, active_only: bool = True,
                      agent_id: str | None = None) -> list[Session]:
        """List sessions, optionally filtered."""
        conditions = []
        params: list = []

        if active_only:
            conditions.append("ended_at IS NULL")
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM sessions WHERE {where} ORDER BY started_at DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_session(r) for r in rows]

    # --- Checkpoint methods ---

    @staticmethod
    def _generate_checkpoint_id() -> str:
        return f"chk-{uuid.uuid4().hex[:8]}"

    def save_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Save a checkpoint record to meta table."""
        if not checkpoint.id:
            checkpoint.id = self._generate_checkpoint_id()
        if not checkpoint.created_at:
            checkpoint.created_at = self._now_iso()
        if not checkpoint.event_count_at_creation:
            checkpoint.event_count_at_creation = self.count()

        data = {
            "id": checkpoint.id,
            "file_path": checkpoint.file_path,
            "agent_id": checkpoint.agent_id,
            "created_at": checkpoint.created_at,
            "event_count_at_creation": checkpoint.event_count_at_creation,
            "enriched_sections": checkpoint.enriched_sections,
            "session_id": checkpoint.session_id,
        }
        self.set_meta(f"checkpoint:{checkpoint.id}", json.dumps(data))
        self.set_meta("checkpoint:latest", json.dumps(data))
        return checkpoint

    def get_latest_checkpoint(self) -> Checkpoint | None:
        """Get the most recent checkpoint, or None."""
        raw = self.get_meta("checkpoint:latest")
        if not raw:
            return None
        data = json.loads(raw)
        return Checkpoint(**data)

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a specific checkpoint by ID."""
        raw = self.get_meta(f"checkpoint:{checkpoint_id}")
        if not raw:
            return None
        data = json.loads(raw)
        return Checkpoint(**data)

    def cleanup_stale_sessions(self, timeout_hours: int = STALE_SESSION_HOURS) -> int:
        """Auto-end sessions older than timeout_hours. Returns count ended."""
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
        cutoff_iso = cutoff.isoformat()

        with self.conn:
            cursor = self.conn.execute(
                "UPDATE sessions SET ended_at = ? "
                "WHERE ended_at IS NULL AND started_at < ?",
                (self._now_iso(), cutoff_iso),
            )
        return cursor.rowcount
