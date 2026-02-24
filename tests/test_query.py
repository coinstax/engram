"""Tests for the query engine and formatting."""

import json
from datetime import datetime, timedelta, timezone

from engram.models import EventType
from engram.query import QueryEngine, parse_since, parse_event_types
from engram.formatting import (
    format_compact, format_json, format_event_compact,
    format_briefing_compact, format_briefing_json,
)
from engram.models import BriefingResult


class TestParseSince:

    def test_hours(self):
        result = parse_since("24h")
        dt = datetime.fromisoformat(result)
        expected = datetime.now(timezone.utc) - timedelta(hours=24)
        assert abs((dt - expected).total_seconds()) < 5

    def test_days(self):
        result = parse_since("7d")
        dt = datetime.fromisoformat(result)
        expected = datetime.now(timezone.utc) - timedelta(days=7)
        assert abs((dt - expected).total_seconds()) < 5

    def test_minutes(self):
        result = parse_since("30m")
        dt = datetime.fromisoformat(result)
        expected = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert abs((dt - expected).total_seconds()) < 5

    def test_weeks(self):
        result = parse_since("2w")
        dt = datetime.fromisoformat(result)
        expected = datetime.now(timezone.utc) - timedelta(weeks=2)
        assert abs((dt - expected).total_seconds()) < 5

    def test_date(self):
        result = parse_since("2026-02-20")
        assert result.startswith("2026-02-20")

    def test_iso_datetime(self):
        result = parse_since("2026-02-20T14:00:00")
        assert "2026-02-20" in result

    def test_passthrough(self):
        result = parse_since("2026-02-20T14:00:00+00:00")
        assert "2026-02-20" in result


class TestParseEventTypes:

    def test_single(self):
        result = parse_event_types("warning")
        assert result == [EventType.WARNING]

    def test_multiple(self):
        result = parse_event_types("warning,mutation,decision")
        assert result == [EventType.WARNING, EventType.MUTATION, EventType.DECISION]

    def test_whitespace(self):
        result = parse_event_types(" warning , mutation ")
        assert result == [EventType.WARNING, EventType.MUTATION]


class TestQueryEngine:

    def test_query_with_since(self, seeded_store):
        engine = QueryEngine(seeded_store)
        results = engine.execute(since="2026-02-23T10:20:00+00:00")
        assert all(e.timestamp >= "2026-02-23T10:20:00" for e in results)

    def test_query_with_text(self, seeded_store):
        engine = QueryEngine(seeded_store)
        results = engine.execute(text="JWT")
        assert len(results) >= 1

    def test_query_combined(self, seeded_store):
        engine = QueryEngine(seeded_store)
        results = engine.execute(
            event_types=[EventType.WARNING],
            scope="src/db"
        )
        assert len(results) == 1
        assert "migration" in results[0].content

    def test_query_related_to_with_type_filter(self, store):
        from engram.models import Event
        store.insert(Event(
            id="evt-base", timestamp="2026-02-23T10:00:00+00:00",
            event_type=EventType.DECISION, agent_id="test",
            content="Base decision",
        ))
        store.insert(Event(
            id="", timestamp="2026-02-23T10:05:00+00:00",
            event_type=EventType.OUTCOME, agent_id="test",
            content="Related outcome",
            related_ids=["evt-base"],
        ))
        store.insert(Event(
            id="", timestamp="2026-02-23T10:06:00+00:00",
            event_type=EventType.DECISION, agent_id="test",
            content="Related decision",
            related_ids=["evt-base"],
        ))
        store.insert(Event(
            id="", timestamp="2026-02-23T10:07:00+00:00",
            event_type=EventType.DECISION, agent_id="test",
            content="Unrelated decision",
        ))

        engine = QueryEngine(store)
        results = engine.execute(
            related_to="evt-base",
            event_types=[EventType.DECISION],
        )
        assert len(results) == 1
        assert results[0].content == "Related decision"


class TestFormatting:

    def test_format_event_compact(self, seeded_store):
        events = seeded_store.query_structured(
            __import__("engram.models", fromlist=["QueryFilter"]).QueryFilter(limit=1)
        )
        line = format_event_compact(events[0])
        assert "[warning]" in line or "[mutation]" in line
        assert "[agent-" in line

    def test_format_compact_empty(self):
        assert format_compact([]) == "(no events)"

    def test_format_json(self, seeded_store):
        from engram.models import QueryFilter
        events = seeded_store.query_structured(QueryFilter(limit=3))
        result = format_json(events)
        data = json.loads(result)
        assert len(data) == 3
        assert "event_type" in data[0]

    def test_format_briefing_compact(self, seeded_store):
        warnings = seeded_store.recent_by_type(EventType.WARNING)
        decisions = seeded_store.recent_by_type(EventType.DECISION)
        mutations = seeded_store.recent_by_type(EventType.MUTATION)
        briefing = BriefingResult(
            project_name="test-project",
            generated_at="2026-02-23T14:30:00+00:00",
            total_events=8,
            time_range="2026-02-23",
            critical_warnings=warnings,
            other_active=decisions,
            recent_mutations=mutations,
        )
        output = format_briefing_compact(briefing)
        assert "# Engram Briefing" in output
        assert "## Critical Warnings (2)" in output
        assert "## Recent Changes (2)" in output

    def test_format_event_compact_with_related_ids(self):
        from engram.models import Event, EventType
        event = Event(
            id="evt-abc", timestamp="2026-02-23T10:00:00+00:00",
            event_type=EventType.OUTCOME, agent_id="test",
            content="Linked outcome",
            related_ids=["evt-111", "evt-222"],
        )
        line = format_event_compact(event)
        assert "(links: 2)" in line

    def test_format_event_compact_without_related_ids(self):
        from engram.models import Event, EventType
        event = Event(
            id="evt-abc", timestamp="2026-02-23T10:00:00+00:00",
            event_type=EventType.OUTCOME, agent_id="test",
            content="No links",
        )
        line = format_event_compact(event)
        assert "(links" not in line

    def test_format_event_compact_empty_related_ids(self):
        from engram.models import Event, EventType
        event = Event(
            id="evt-abc", timestamp="2026-02-23T10:00:00+00:00",
            event_type=EventType.OUTCOME, agent_id="test",
            content="Empty links",
            related_ids=[],
        )
        line = format_event_compact(event)
        assert "(links" not in line

    def test_format_briefing_json(self, seeded_store):
        briefing = BriefingResult(
            project_name="test-project",
            generated_at="2026-02-23T14:30:00+00:00",
            total_events=8,
            time_range="2026-02-23",
        )
        result = format_briefing_json(briefing)
        data = json.loads(result)
        assert data["project_name"] == "test-project"
