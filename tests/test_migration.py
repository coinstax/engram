"""Tests for schema migration from v1.0 to v1.1."""

import json
import sqlite3
import pytest
from pathlib import Path

from engram.models import Event, EventType
from engram.store import EventStore, SCHEMA_VERSION


V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL
                CHECK(event_type IN ('discovery','decision','warning','mutation','outcome')),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL
                CHECK(length(content) <= 2000),
    scope       TEXT
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


def create_v1_db(path: Path) -> None:
    """Create a v1.0 database (no related_ids column, no schema_version)."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(V1_SCHEMA_SQL)
    # Insert a v1.0 event (no related_ids)
    conn.execute(
        "INSERT INTO events (id, timestamp, event_type, agent_id, content, scope) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("evt-v1-test", "2026-02-20T10:00:00+00:00", "decision",
         "test-agent", "A v1.0 decision", '["src/old.py"]'),
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        ("project_name", "test-project"),
    )
    conn.commit()
    conn.close()


class TestMigration:

    def test_v1_db_migrates_on_access(self, tmp_path):
        """Opening a v1.0 DB with v1.1 code should auto-migrate."""
        db_path = tmp_path / "events.db"
        create_v1_db(db_path)

        store = EventStore(db_path)
        # Accessing conn triggers migration
        count = store.count()
        assert count == 1

        # Verify related_ids column exists
        columns = {
            row[1] for row in
            store.conn.execute("PRAGMA table_info(events)").fetchall()
        }
        assert "related_ids" in columns

        # Verify schema version was set
        version = store.get_meta("schema_version")
        assert version == str(SCHEMA_VERSION)

        store.close()

    def test_v1_events_survive_migration(self, tmp_path):
        """Existing v1.0 events should be readable after migration."""
        db_path = tmp_path / "events.db"
        create_v1_db(db_path)

        store = EventStore(db_path)
        events = store.query_fts("decision", limit=10)
        assert len(events) == 1
        assert events[0].id == "evt-v1-test"
        assert events[0].content == "A v1.0 decision"
        assert events[0].related_ids is None
        store.close()

    def test_migration_is_idempotent(self, tmp_path):
        """Running migration twice should be a no-op."""
        db_path = tmp_path / "events.db"
        create_v1_db(db_path)

        store = EventStore(db_path)
        _ = store.count()  # triggers migration
        store.close()

        # Open again — should not error
        store2 = EventStore(db_path)
        count = store2.count()
        assert count == 1
        assert store2.get_meta("schema_version") == str(SCHEMA_VERSION)
        store2.close()

    def test_insert_with_related_ids_after_migration(self, tmp_path):
        """After migration, new events with related_ids should work."""
        db_path = tmp_path / "events.db"
        create_v1_db(db_path)

        store = EventStore(db_path)
        event = Event(
            id="", timestamp="",
            event_type=EventType.OUTCOME,
            agent_id="test",
            content="Outcome linked to v1 event",
            related_ids=["evt-v1-test"],
        )
        result = store.insert(event)
        assert result.related_ids == ["evt-v1-test"]

        # Query it back
        events = store.query_fts("Outcome linked", limit=10)
        assert len(events) == 1
        assert events[0].related_ids == ["evt-v1-test"]
        store.close()

    def test_query_related(self, tmp_path):
        """query_related should find events by their related_ids."""
        db_path = tmp_path / "events.db"
        create_v1_db(db_path)

        store = EventStore(db_path)
        # Insert event that links to the v1 event
        event = Event(
            id="", timestamp="",
            event_type=EventType.OUTCOME,
            agent_id="test",
            content="Test outcome",
            related_ids=["evt-v1-test"],
        )
        store.insert(event)

        related = store.query_related("evt-v1-test")
        assert len(related) == 1
        assert related[0].content == "Test outcome"

        # Query for non-existent ID
        empty = store.query_related("evt-nonexistent")
        assert len(empty) == 0
        store.close()
