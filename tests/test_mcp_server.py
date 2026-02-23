"""Tests for the MCP server tool functions."""

import json
import os

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
