"""Tests for the EventStore."""

from engram.models import Event, EventType, QueryFilter
from engram.store import EventStore


class TestEventStore:

    def test_initialize_creates_tables(self, store):
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in tables}
        assert "events" in names
        assert "meta" in names

    def test_insert_and_retrieve(self, store):
        event = Event(
            id="", timestamp="", event_type=EventType.DISCOVERY,
            agent_id="test", content="Found a bug", scope=["src/foo.py"]
        )
        result = store.insert(event)
        assert result.id.startswith("evt-")
        assert result.timestamp != ""
        assert store.count() == 1

    def test_insert_batch(self, store):
        events = [
            Event(id="", timestamp="", event_type=EventType.MUTATION,
                  agent_id="test", content=f"Change {i}")
            for i in range(10)
        ]
        count = store.insert_batch(events)
        assert count == 10
        assert store.count() == 10

    def test_query_fts(self, seeded_store):
        results = seeded_store.query_fts("JWT refresh")
        assert len(results) >= 1
        assert any("JWT" in e.content for e in results)

    def test_query_fts_scope(self, seeded_store):
        results = seeded_store.query_fts("email validation")
        assert len(results) >= 1
        assert results[0].scope == ["src/api/users.ts"]

    def test_query_structured_by_type(self, seeded_store):
        filters = QueryFilter(event_types=[EventType.WARNING])
        results = seeded_store.query_structured(filters)
        assert len(results) == 2
        assert all(e.event_type == EventType.WARNING for e in results)

    def test_query_structured_by_agent(self, seeded_store):
        filters = QueryFilter(agent_id="agent-b")
        results = seeded_store.query_structured(filters)
        assert all(e.agent_id == "agent-b" for e in results)

    def test_query_structured_by_scope(self, seeded_store):
        filters = QueryFilter(scope="src/auth")
        results = seeded_store.query_structured(filters)
        assert len(results) >= 3
        for e in results:
            assert any("src/auth" in s for s in e.scope)

    def test_query_structured_by_since(self, seeded_store):
        filters = QueryFilter(since="2026-02-23T10:20:00+00:00")
        results = seeded_store.query_structured(filters)
        assert all(e.timestamp >= "2026-02-23T10:20:00" for e in results)

    def test_query_structured_combined(self, seeded_store):
        filters = QueryFilter(
            event_types=[EventType.MUTATION],
            scope="src/auth"
        )
        results = seeded_store.query_structured(filters)
        assert len(results) >= 1
        assert all(e.event_type == EventType.MUTATION for e in results)

    def test_query_with_text_and_filters(self, seeded_store):
        filters = QueryFilter(text="JWT", event_types=[EventType.DISCOVERY])
        results = seeded_store.query_structured(filters)
        assert len(results) >= 1
        assert all(e.event_type == EventType.DISCOVERY for e in results)

    def test_recent_by_type(self, seeded_store):
        results = seeded_store.recent_by_type(EventType.MUTATION, limit=5)
        assert len(results) == 2
        assert results[0].timestamp >= results[1].timestamp

    def test_recent_by_type_with_scope(self, seeded_store):
        results = seeded_store.recent_by_type(
            EventType.MUTATION, scope="src/auth"
        )
        assert len(results) == 1
        assert "JWT" in results[0].content

    def test_count(self, seeded_store):
        assert seeded_store.count() == 8

    def test_last_activity(self, seeded_store):
        assert seeded_store.last_activity() == "2026-02-23T10:35:00+00:00"

    def test_meta_get_set(self, store):
        assert store.get_meta("foo") is None
        store.set_meta("foo", "bar")
        assert store.get_meta("foo") == "bar"
        store.set_meta("foo", "baz")
        assert store.get_meta("foo") == "baz"

    def test_content_max_length(self, store):
        """Content over 2000 chars should be rejected by SQLite CHECK."""
        import sqlite3
        event = Event(
            id="", timestamp="", event_type=EventType.DISCOVERY,
            agent_id="test", content="x" * 2001
        )
        try:
            store.insert(event)
            assert False, "Should have raised"
        except sqlite3.IntegrityError:
            pass

    def test_scope_none(self, store):
        event = Event(
            id="", timestamp="", event_type=EventType.DISCOVERY,
            agent_id="test", content="No scope event"
        )
        store.insert(event)
        results = store.query_structured(QueryFilter(limit=10))
        assert results[0].scope is None

    def test_query_limit(self, store):
        events = [
            Event(id="", timestamp="", event_type=EventType.MUTATION,
                  agent_id="test", content=f"Change {i}")
            for i in range(20)
        ]
        store.insert_batch(events)
        results = store.query_structured(QueryFilter(limit=5))
        assert len(results) == 5

    def test_insert_and_retrieve_related_ids(self, store):
        event = Event(
            id="", timestamp="", event_type=EventType.OUTCOME,
            agent_id="test", content="Outcome with links",
            related_ids=["evt-aaa", "evt-bbb"],
        )
        result = store.insert(event)
        assert result.related_ids == ["evt-aaa", "evt-bbb"]

        retrieved = store.query_structured(QueryFilter(limit=1))
        assert retrieved[0].related_ids == ["evt-aaa", "evt-bbb"]

    def test_query_related_no_substring_false_match(self, store):
        """query_related should not match IDs that are prefixes of the target."""
        e1 = Event(
            id="", timestamp="", event_type=EventType.OUTCOME,
            agent_id="test", content="Links to short ID",
            related_ids=["evt-abc123"],
        )
        e2 = Event(
            id="", timestamp="", event_type=EventType.OUTCOME,
            agent_id="test", content="Links to longer ID",
            related_ids=["evt-abc123456"],
        )
        store.insert(e1)
        store.insert(e2)

        results = store.query_related("evt-abc123")
        assert len(results) == 1
        assert results[0].content == "Links to short ID"

    def test_query_structured_with_related_to(self, store):
        """related_to combined with other filters should filter both."""
        store.insert(Event(
            id="evt-target", timestamp="2026-02-23T10:00:00+00:00",
            event_type=EventType.DECISION, agent_id="test",
            content="The target decision",
        ))
        store.insert(Event(
            id="", timestamp="2026-02-23T10:05:00+00:00",
            event_type=EventType.OUTCOME, agent_id="test",
            content="Related outcome",
            related_ids=["evt-target"],
        ))
        store.insert(Event(
            id="", timestamp="2026-02-23T10:06:00+00:00",
            event_type=EventType.DECISION, agent_id="test",
            content="Related decision",
            related_ids=["evt-target"],
        ))
        store.insert(Event(
            id="", timestamp="2026-02-23T10:07:00+00:00",
            event_type=EventType.DECISION, agent_id="test",
            content="Unrelated decision",
        ))

        # related_to + type filter
        filters = QueryFilter(
            event_types=[EventType.DECISION],
            related_to="evt-target",
        )
        results = store.query_structured(filters)
        assert len(results) == 1
        assert results[0].content == "Related decision"
