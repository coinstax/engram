"""Tests for garbage collection."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engram.gc import GarbageCollector
from engram.models import Event, EventType
from engram.store import EventStore


@pytest.fixture
def gc_store(tmp_path):
    """Store with old and new events for GC testing."""
    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    db_path = engram_dir / "events.db"
    store = EventStore(db_path)
    store.initialize()
    store.set_meta("project_name", "gc-test")

    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=120)).isoformat()
    recent = (now - timedelta(days=10)).isoformat()

    events = [
        # Old events (should be archived for mutations/outcomes, kept for warnings/decisions)
        Event(id="", timestamp=old, event_type=EventType.MUTATION,
              agent_id="test", content="Old mutation"),
        Event(id="", timestamp=old, event_type=EventType.OUTCOME,
              agent_id="test", content="Old outcome"),
        Event(id="", timestamp=old, event_type=EventType.WARNING,
              agent_id="test", content="Old warning — should be preserved"),
        Event(id="", timestamp=old, event_type=EventType.DECISION,
              agent_id="test", content="Old decision — should be preserved"),
        # Recent events (should never be archived)
        Event(id="", timestamp=recent, event_type=EventType.MUTATION,
              agent_id="test", content="Recent mutation"),
        Event(id="", timestamp=recent, event_type=EventType.OUTCOME,
              agent_id="test", content="Recent outcome"),
    ]
    store.insert_batch(events)
    yield store, engram_dir
    store.close()


class TestGarbageCollector:

    def test_dry_run_shows_count(self, gc_store):
        store, engram_dir = gc_store
        gc = GarbageCollector(store, engram_dir)
        result = gc.collect(max_age_days=90, dry_run=True)

        assert result["would_archive"] == 2  # old mutation + old outcome
        assert result["archived"] == 0
        assert store.count() == 6  # nothing actually removed

    def test_archives_old_mutations_and_outcomes(self, gc_store):
        store, engram_dir = gc_store
        gc = GarbageCollector(store, engram_dir)
        result = gc.collect(max_age_days=90)

        assert result["archived"] == 2
        assert "archive" in result["archive_path"]
        assert store.count() == 4  # 2 archived, 4 remain

    def test_preserves_old_warnings_and_decisions(self, gc_store):
        store, engram_dir = gc_store
        gc = GarbageCollector(store, engram_dir)
        gc.collect(max_age_days=90)

        warnings = store.recent_by_type(EventType.WARNING, limit=10)
        decisions = store.recent_by_type(EventType.DECISION, limit=10)
        assert len(warnings) == 1
        assert "preserved" in warnings[0].content
        assert len(decisions) == 1
        assert "preserved" in decisions[0].content

    def test_archive_db_contains_events(self, gc_store):
        store, engram_dir = gc_store
        gc = GarbageCollector(store, engram_dir)
        result = gc.collect(max_age_days=90)

        archive_path = Path(result["archive_path"])
        assert archive_path.exists()

        archive_store = EventStore(archive_path)
        assert archive_store.count() == 2
        archive_store.close()

    def test_no_events_to_archive(self, tmp_path):
        engram_dir = tmp_path / ".engram"
        engram_dir.mkdir()
        db_path = engram_dir / "events.db"
        store = EventStore(db_path)
        store.initialize()

        gc = GarbageCollector(store, engram_dir)
        result = gc.collect(max_age_days=90)
        assert result["archived"] == 0
        store.close()

    def test_gc_appends_to_existing_archive(self, gc_store):
        """Running GC twice in same month should accumulate in the archive."""
        store, engram_dir = gc_store
        gc = GarbageCollector(store, engram_dir)
        result1 = gc.collect(max_age_days=90)
        assert result1["archived"] == 2

        # Add more old events
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        store.insert_batch([
            Event(id="", timestamp=old, event_type=EventType.MUTATION,
                  agent_id="test", content="Another old mutation"),
            Event(id="", timestamp=old, event_type=EventType.OUTCOME,
                  agent_id="test", content="Another old outcome"),
        ])

        result2 = gc.collect(max_age_days=90)
        assert result2["archived"] == 2

        # Archive should contain all 4 events total
        archive_store = EventStore(Path(result2["archive_path"]))
        assert archive_store.count() == 4
        archive_store.close()

    def test_recent_events_preserved(self, gc_store):
        store, engram_dir = gc_store
        gc = GarbageCollector(store, engram_dir)
        gc.collect(max_age_days=90)

        mutations = store.recent_by_type(EventType.MUTATION, limit=10)
        outcomes = store.recent_by_type(EventType.OUTCOME, limit=10)
        assert len(mutations) == 1
        assert "Recent mutation" in mutations[0].content
        assert len(outcomes) == 1
        assert "Recent outcome" in outcomes[0].content
