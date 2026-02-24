"""Tests for the MCP server tool functions."""

import json
import os
from unittest.mock import patch

import pytest

from engram.store import EventStore
from engram.models import Event, EventType


@pytest.fixture
def mcp_project(tmp_path):
    """Set up a project with initialized Engram for MCP testing."""
    project = tmp_path / "mcp-test"
    project.mkdir()
    engram_dir = project / ".engram"
    engram_dir.mkdir()

    store = EventStore(engram_dir / "events.db")
    store.initialize()
    store.set_meta("project_name", "mcp-test-project")

    # Seed some events
    events = [
        Event(id="", timestamp="2026-02-23T10:00:00+00:00",
              event_type=EventType.WARNING, agent_id="test",
              content="Don't modify the schema", scope=["src/db/schema.sql"]),
        Event(id="", timestamp="2026-02-23T10:05:00+00:00",
              event_type=EventType.MUTATION, agent_id="test",
              content="Added user authentication",
              scope=["src/auth/login.ts"]),
        Event(id="", timestamp="2026-02-23T10:10:00+00:00",
              event_type=EventType.DECISION, agent_id="test",
              content="Using JWT for session management",
              scope=["src/auth/"]),
    ]
    store.insert_batch(events)
    store.close()

    # Set env var for MCP server
    old_env = os.environ.get("ENGRAM_PROJECT_DIR")
    os.environ["ENGRAM_PROJECT_DIR"] = str(project)
    yield project
    if old_env is None:
        del os.environ["ENGRAM_PROJECT_DIR"]
    else:
        os.environ["ENGRAM_PROJECT_DIR"] = old_env


class TestMCPTools:

    def test_post_event(self, mcp_project):
        from engram.mcp_server import post_event
        result = post_event(
            event_type="discovery",
            content="Found a performance bottleneck",
            scope=["src/api/handler.ts"]
        )
        assert "[discovery]" in result
        assert "performance bottleneck" in result

    def test_post_event_truncates(self, mcp_project):
        from engram.mcp_server import post_event
        result = post_event(
            event_type="discovery",
            content="x" * 2500,
        )
        assert "[discovery]" in result

    def test_query_text(self, mcp_project):
        from engram.mcp_server import query
        result = query(text="JWT")
        assert "JWT" in result

    def test_query_by_type(self, mcp_project):
        from engram.mcp_server import query
        result = query(event_type="warning")
        assert "[warning]" in result
        assert "schema" in result

    def test_query_json(self, mcp_project):
        from engram.mcp_server import query
        result = query(event_type="warning", format="json")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["event_type"] == "warning"

    def test_query_no_results(self, mcp_project):
        from engram.mcp_server import query
        result = query(text="nonexistent_xyz_query")
        assert "(no events)" in result

    def test_briefing_compact(self, mcp_project):
        from engram.mcp_server import briefing
        result = briefing()
        assert "# Engram Briefing" in result
        assert "mcp-test-project" in result

    def test_briefing_json(self, mcp_project):
        from engram.mcp_server import briefing
        result = briefing(format="json")
        data = json.loads(result)
        assert data["project_name"] == "mcp-test-project"
        assert data["total_events"] == 3

    def test_briefing_scoped(self, mcp_project):
        from engram.mcp_server import briefing
        result = briefing(scope="src/auth")
        assert "JWT" in result or "authentication" in result

    def test_status(self, mcp_project):
        from engram.mcp_server import status
        result = status()
        data = json.loads(result)
        assert data["project_name"] == "mcp-test-project"
        assert data["total_events"] == 3
        assert data["db_size_bytes"] > 0

    def test_post_event_with_related_ids(self, mcp_project):
        from engram.mcp_server import post_event
        result = post_event(
            event_type="outcome",
            content="Linked outcome",
            related_ids=["evt-abc123"],
        )
        assert "[outcome]" in result
        assert "(links: 1)" in result

        # Verify persisted
        store = EventStore(mcp_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.OUTCOME, limit=1)
        assert events[0].related_ids == ["evt-abc123"]
        store.close()

    def test_query_related_to(self, mcp_project):
        from engram.mcp_server import post_event, query
        # Post an event that links to an existing one
        post_event(
            event_type="outcome",
            content="Outcome linking to warning",
            related_ids=["evt-existing"],
        )
        result = query(related_to="evt-existing")
        assert "Outcome linking to warning" in result

    def test_query_related_to_with_type_filter(self, mcp_project):
        from engram.mcp_server import post_event, query
        post_event(
            event_type="outcome",
            content="Linked outcome",
            related_ids=["evt-target"],
        )
        post_event(
            event_type="decision",
            content="Linked decision",
            related_ids=["evt-target"],
        )
        result = query(related_to="evt-target", event_type="decision")
        assert "Linked decision" in result
        assert "Linked outcome" not in result


class TestMCPConsultation:

    def test_start_consultation(self, mcp_project):
        from engram.mcp_server import start_consultation
        result = start_consultation(topic="Test topic", models="gpt-4o")
        assert "Started consultation" in result
        assert "conv-" in result
        assert "Test topic" in result

    @patch("engram.consult.providers.send_message", return_value="Model says hello")
    def test_start_consultation_with_message(self, mock_send, mcp_project):
        from engram.mcp_server import start_consultation
        result = start_consultation(
            topic="Test", models="gpt-4o",
            initial_message="What do you think?"
        )
        assert "What do you think?" in result
        assert "Model says hello" in result
        assert "gpt-4o" in result

    @patch("engram.consult.providers.send_message", return_value="Response text")
    def test_consult_say(self, mock_send, mcp_project):
        from engram.mcp_server import start_consultation, consult_say
        start_result = start_consultation(topic="Test", models="gpt-4o")
        # Extract conv_id
        conv_id = start_result.split("Started consultation ")[1].split("\n")[0].strip()

        result = consult_say(conv_id=conv_id, message="Follow-up question")
        assert "Follow-up question" in result
        assert "Response text" in result

    def test_consult_show(self, mcp_project):
        from engram.mcp_server import start_consultation, consult_show
        start_result = start_consultation(topic="Show test", models="gpt-4o")
        conv_id = start_result.split("Started consultation ")[1].split("\n")[0].strip()

        result = consult_show(conv_id=conv_id)
        assert "Show test" in result
        assert "[active]" in result

    def test_consult_done(self, mcp_project):
        from engram.mcp_server import start_consultation, consult_done
        start_result = start_consultation(topic="Done test", models="gpt-4o")
        conv_id = start_result.split("Started consultation ")[1].split("\n")[0].strip()

        result = consult_done(conv_id=conv_id, summary="Decided X")
        assert "Completed" in result
        assert "Decided X" in result
