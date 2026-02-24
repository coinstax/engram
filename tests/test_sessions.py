"""Tests for session intent feature."""

import pytest
from datetime import datetime, timezone, timedelta

from engram.models import Event, EventType, Session
from engram.store import EventStore


class TestSessionCRUD:
    """Test basic session operations."""

    def test_insert_session(self, store):
        session = Session(id="", agent_id="claude-code", focus="refactoring auth")
        result = store.insert_session(session)
        assert result.id.startswith("sess-")
        assert result.agent_id == "claude-code"
        assert result.focus == "refactoring auth"
        assert result.started_at != ""
        assert result.ended_at is None

    def test_insert_session_with_scope(self, store):
        session = Session(
            id="", agent_id="claude-code", focus="auth work",
            scope=["src/auth/"], description="Fixing JWT bugs",
        )
        result = store.insert_session(session)
        assert result.scope == ["src/auth/"]
        assert result.description == "Fixing JWT bugs"

    def test_get_session(self, store):
        session = store.insert_session(
            Session(id="", agent_id="claude-code", focus="test")
        )
        fetched = store.get_session(session.id)
        assert fetched is not None
        assert fetched.id == session.id
        assert fetched.focus == "test"

    def test_get_session_not_found(self, store):
        assert store.get_session("sess-nonexist") is None

    def test_end_session(self, store):
        session = store.insert_session(
            Session(id="", agent_id="claude-code", focus="work")
        )
        ended = store.end_session(session.id)
        assert ended.ended_at is not None
        assert ended.id == session.id

    def test_end_session_not_found(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.end_session("sess-nonexist")

    def test_end_session_already_ended(self, store):
        session = store.insert_session(
            Session(id="", agent_id="claude-code", focus="work")
        )
        store.end_session(session.id)
        with pytest.raises(ValueError, match="already ended"):
            store.end_session(session.id)

    def test_get_active_session(self, store):
        store.insert_session(
            Session(id="", agent_id="claude-code", focus="first")
        )
        active = store.get_active_session("claude-code")
        assert active is not None
        assert active.focus == "first"

    def test_get_active_session_none(self, store):
        assert store.get_active_session("claude-code") is None

    def test_get_active_session_returns_most_recent(self, store):
        s1 = store.insert_session(
            Session(id="", agent_id="claude-code", focus="first",
                    started_at="2026-02-24T10:00:00+00:00")
        )
        s2 = store.insert_session(
            Session(id="", agent_id="claude-code", focus="second",
                    started_at="2026-02-24T11:00:00+00:00")
        )
        active = store.get_active_session("claude-code")
        assert active.focus == "second"

    def test_get_active_session_skips_ended(self, store):
        s1 = store.insert_session(
            Session(id="", agent_id="claude-code", focus="ended-one")
        )
        store.end_session(s1.id)
        s2 = store.insert_session(
            Session(id="", agent_id="claude-code", focus="active-one")
        )
        active = store.get_active_session("claude-code")
        assert active.focus == "active-one"


class TestSessionList:
    """Test session listing."""

    def test_list_active_only(self, store):
        s1 = store.insert_session(
            Session(id="", agent_id="agent-a", focus="work-a")
        )
        s2 = store.insert_session(
            Session(id="", agent_id="agent-b", focus="work-b")
        )
        store.end_session(s1.id)

        active = store.list_sessions(active_only=True)
        assert len(active) == 1
        assert active[0].focus == "work-b"

    def test_list_all(self, store):
        s1 = store.insert_session(
            Session(id="", agent_id="agent-a", focus="work-a")
        )
        store.insert_session(
            Session(id="", agent_id="agent-b", focus="work-b")
        )
        store.end_session(s1.id)

        all_sessions = store.list_sessions(active_only=False)
        assert len(all_sessions) == 2

    def test_list_by_agent(self, store):
        store.insert_session(
            Session(id="", agent_id="agent-a", focus="a-work")
        )
        store.insert_session(
            Session(id="", agent_id="agent-b", focus="b-work")
        )
        a_sessions = store.list_sessions(active_only=True, agent_id="agent-a")
        assert len(a_sessions) == 1
        assert a_sessions[0].agent_id == "agent-a"

    def test_list_empty(self, store):
        assert store.list_sessions() == []


class TestStaleCleanup:
    """Test stale session auto-end."""

    def test_cleanup_stale_sessions(self, store):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        store.insert_session(
            Session(id="", agent_id="agent-a", focus="stale",
                    started_at=old_time)
        )
        store.insert_session(
            Session(id="", agent_id="agent-b", focus="fresh")
        )

        count = store.cleanup_stale_sessions(timeout_hours=24)
        assert count == 1

        # Stale session should now be ended
        sessions = store.list_sessions(active_only=True)
        assert len(sessions) == 1
        assert sessions[0].focus == "fresh"

    def test_cleanup_no_stale(self, store):
        store.insert_session(
            Session(id="", agent_id="agent-a", focus="fresh")
        )
        count = store.cleanup_stale_sessions(timeout_hours=24)
        assert count == 0

    def test_cleanup_custom_timeout(self, store):
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        store.insert_session(
            Session(id="", agent_id="agent-a", focus="recent",
                    started_at=two_hours_ago)
        )
        # 1-hour timeout should catch it
        count = store.cleanup_stale_sessions(timeout_hours=1)
        assert count == 1
        # 4-hour timeout should not
        store.insert_session(
            Session(id="", agent_id="agent-b", focus="recent2",
                    started_at=two_hours_ago)
        )
        count = store.cleanup_stale_sessions(timeout_hours=4)
        assert count == 0


class TestSessionIdOnEvents:
    """Test session_id field on events."""

    def test_event_with_session_id(self, store):
        session = store.insert_session(
            Session(id="", agent_id="claude-code", focus="work")
        )
        event = Event(
            id="", timestamp="", event_type=EventType.MUTATION,
            agent_id="claude-code", content="Changed auth.py",
            session_id=session.id,
        )
        result = store.insert(event)
        assert result.session_id == session.id

        fetched = store.get_event(result.id)
        assert fetched.session_id == session.id

    def test_event_without_session_id(self, store):
        event = Event(
            id="", timestamp="", event_type=EventType.DISCOVERY,
            agent_id="claude-code", content="Found a bug",
        )
        result = store.insert(event)
        assert result.session_id is None

    def test_scope_stored_as_json(self, store):
        session = store.insert_session(
            Session(id="", agent_id="claude-code", focus="work",
                    scope=["src/auth/", "src/api/"])
        )
        fetched = store.get_session(session.id)
        assert fetched.scope == ["src/auth/", "src/api/"]

    def test_empty_scope_list_treated_as_none(self, store):
        session = store.insert_session(
            Session(id="", agent_id="claude-code", focus="work", scope=[])
        )
        fetched = store.get_session(session.id)
        # Empty list serializes to "[]" which is truthy, so it round-trips
        # But per spec, empty scope is functionally same as None
        assert fetched.scope == [] or fetched.scope is None
