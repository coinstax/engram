"""Tests for the MCP server tool functions."""

import json
import os
from unittest.mock import patch

import pytest

from engram.store import EventStore
from engram.models import Event, EventType
from tests.conftest import ts_offset


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
        Event(id="", timestamp=ts_offset(0),
              event_type=EventType.WARNING, agent_id="test",
              content="Don't modify the schema", scope=["src/db/schema.sql"]),
        Event(id="", timestamp=ts_offset(5),
              event_type=EventType.MUTATION, agent_id="test",
              content="Added user authentication",
              scope=["src/auth/login.ts"]),
        Event(id="", timestamp=ts_offset(10),
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

    def test_post_event_explicit_area(self, mcp_project):
        from engram.mcp_server import post_event, query
        import json as _json
        post_event(event_type="decision", content="cooldown rule",
                   scope=["src/x.py"], area="email-change")
        row = _json.loads(query(text="cooldown", format="json"))[0]
        assert row["area"] == "email-change"

    def test_post_event_infers_area_from_map(self, mcp_project):
        from engram.mcp_server import post_event, query
        import json as _json
        # Write an area map into the project the fixture set up.
        (mcp_project / ".engram" / "areas.json").write_text(
            _json.dumps({"rules": [{"prefix": "src/billing/", "area": "billing"}]}))
        post_event(event_type="decision", content="switch processor",
                   scope=["src/billing/pay.py"])
        row = _json.loads(query(text="processor", format="json"))[0]
        assert row["area"] == "billing"

    def test_post_event_rejects_oversized_content(self, mcp_project):
        from engram.mcp_server import post_event, query
        with pytest.raises(ValueError, match="2500 chars"):
            post_event(
                event_type="discovery",
                content="x" * 2500,
            )
        # Nothing persisted — no silent truncation.
        assert "xxxx" not in query(text="xxxx")

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

    def test_query_by_area(self, mcp_project):
        from engram.mcp_server import post_event, query
        post_event(event_type="decision", content="billing thing", area="billing")
        post_event(event_type="decision", content="account thing", area="account")
        result = query(area="billing")
        assert "billing thing" in result
        assert "account thing" not in result

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


class TestMCPLifecycle:
    """MCP must expose the same resolve/supersede/reopen lifecycle as the CLI,
    so agents can flip stale events instead of only appending."""

    def _first_id(self, text=None, event_type=None):
        from engram.mcp_server import query
        rows = json.loads(query(text=text, event_type=event_type, format="json"))
        return rows[0]["id"]

    def test_resolve_event(self, mcp_project):
        from engram.mcp_server import resolve_event, query
        eid = self._first_id(text="schema")
        result = resolve_event(eid, reason="Fixed in PR #1")
        assert eid in result or "schema" in result
        row = json.loads(query(text="schema", format="json"))[0]
        assert row["status"] == "resolved"
        assert row["resolved_reason"] == "Fixed in PR #1"

    def test_resolve_non_active_rejected(self, mcp_project):
        from engram.mcp_server import resolve_event
        eid = self._first_id(text="schema")
        resolve_event(eid, reason="once")
        with pytest.raises(ValueError, match="not active"):
            resolve_event(eid, reason="twice")

    def test_resolve_missing_event(self, mcp_project):
        from engram.mcp_server import resolve_event
        with pytest.raises(ValueError, match="not found"):
            resolve_event("evt-nope", reason="x")

    def test_supersede_event(self, mcp_project):
        from engram.mcp_server import post_event, supersede_event, query
        old_id = self._first_id(event_type="decision")
        post_event(event_type="decision", content="Now using sessions, not JWT")
        new_id = json.loads(
            query(text="sessions", event_type="decision", format="json")
        )[0]["id"]
        supersede_event(old_id, superseded_by=new_id)
        rows = json.loads(query(event_type="decision", format="json"))
        old = next(r for r in rows if r["id"] == old_id)
        assert old["status"] == "superseded"
        assert old["superseded_by"] == new_id

    def test_supersede_missing_new_event(self, mcp_project):
        from engram.mcp_server import supersede_event
        old_id = self._first_id(event_type="decision")
        with pytest.raises(ValueError, match="Superseding event not found"):
            supersede_event(old_id, superseded_by="evt-nope")

    def test_reopen_event(self, mcp_project):
        from engram.mcp_server import resolve_event, reopen_event, query
        eid = self._first_id(text="schema")
        resolve_event(eid, reason="fixed")
        reopen_event(eid)
        assert json.loads(query(text="schema", format="json"))[0]["status"] == "active"

    def test_reopen_superseded_rejected(self, mcp_project):
        from engram.mcp_server import post_event, supersede_event, reopen_event, query
        old_id = self._first_id(event_type="decision")
        post_event(event_type="decision", content="replacement decision")
        new_id = json.loads(
            query(text="replacement", event_type="decision", format="json")
        )[0]["id"]
        supersede_event(old_id, superseded_by=new_id)
        with pytest.raises(ValueError, match="cannot be reopened"):
            reopen_event(old_id)

    def test_reopen_active_rejected(self, mcp_project):
        from engram.mcp_server import reopen_event
        eid = self._first_id(text="schema")
        with pytest.raises(ValueError, match="already active"):
            reopen_event(eid)


class TestMCPAutoInit:
    """MCP tools must auto-init if invoked before SessionStart fires,
    mirroring the hook behavior so the plugin's two entry points agree."""

    def test_get_store_auto_inits_missing_db(self, tmp_path):
        from engram.mcp_server import _get_store

        old_env = os.environ.get("ENGRAM_PROJECT_DIR")
        os.environ["ENGRAM_PROJECT_DIR"] = str(tmp_path)
        try:
            store = _get_store()
            try:
                assert (tmp_path / ".engram" / "events.db").exists()
                assert store.get_meta("project_name") is not None
            finally:
                store.close()
            # CLAUDE.md invariant — same as the hook path.
            assert not (tmp_path / "CLAUDE.md").exists()
        finally:
            if old_env is None:
                del os.environ["ENGRAM_PROJECT_DIR"]
            else:
                os.environ["ENGRAM_PROJECT_DIR"] = old_env

    def test_get_store_rejects_unexpanded_project_dir(self, monkeypatch):
        """A literal '${PWD}' (unexpanded on Windows) must fail loudly, not
        silently create a junk dir and read an empty DB."""
        from engram.mcp_server import _get_store
        monkeypatch.setenv("ENGRAM_PROJECT_DIR", "${PWD}")
        with pytest.raises(ValueError, match="unexpanded shell variable"):
            _get_store()

    def test_get_store_auto_init_failure_raises_filenotfound(self, tmp_path, monkeypatch):
        """If perform_init fails, the legacy FileNotFoundError surfaces —
        user experience matches the pre-auto-init behavior for error cases."""
        from engram import mcp_server

        def boom(_project_dir):
            raise OSError("simulated filesystem denial")

        # mcp_server imports perform_init lazily inside _get_store, so patch
        # the init module directly.
        from engram import init as init_mod
        monkeypatch.setattr(init_mod, "perform_init", boom)

        old_env = os.environ.get("ENGRAM_PROJECT_DIR")
        os.environ["ENGRAM_PROJECT_DIR"] = str(tmp_path)
        try:
            with pytest.raises(FileNotFoundError, match="Engram not initialized"):
                mcp_server._get_store()
        finally:
            if old_env is None:
                del os.environ["ENGRAM_PROJECT_DIR"]
            else:
                os.environ["ENGRAM_PROJECT_DIR"] = old_env


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


class TestMCPSafeMode:
    """Safe mode (ENGRAM_SAFE_MODE) must keep local project-memory tools but
    drop every tool that can reach an external LLM provider or read API keys."""

    _CONSULT = {
        "start_consultation", "start_consultation_file", "consult_say",
        "consult_show", "consult_done", "list_models",
    }
    _MEMORY = {
        "post_event", "query", "briefing", "status", "resolve_event",
        "session_start",
    }

    @staticmethod
    def _registered_tool_names(module):
        import asyncio
        return {t.name for t in asyncio.run(module.mcp.list_tools())}

    def test_normal_mode_registers_consult_tools(self, monkeypatch):
        import importlib
        from engram import mcp_server
        monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
        importlib.reload(mcp_server)
        try:
            names = self._registered_tool_names(mcp_server)
            assert self._CONSULT <= names
            assert self._MEMORY <= names
            assert mcp_server.SAFE_MODE is False
        finally:
            monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
            importlib.reload(mcp_server)

    def test_safe_mode_omits_consult_tools(self, monkeypatch):
        import importlib
        from engram import mcp_server
        monkeypatch.setenv("ENGRAM_SAFE_MODE", "1")
        importlib.reload(mcp_server)
        try:
            names = self._registered_tool_names(mcp_server)
            assert not (self._CONSULT & names)   # no external-LLM tools advertised
            assert self._MEMORY <= names          # local memory tools intact
            assert mcp_server.SAFE_MODE is True
        finally:
            monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
            importlib.reload(mcp_server)

    def test_status_reports_external_llm_flag(self, mcp_project, monkeypatch):
        import importlib
        from engram import mcp_server
        # Normal mode: flag true.
        monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
        importlib.reload(mcp_server)
        assert json.loads(mcp_server.status())["external_llm_tools"] is True
        # Safe mode: flag false.
        monkeypatch.setenv("ENGRAM_SAFE_MODE", "1")
        importlib.reload(mcp_server)
        try:
            assert json.loads(mcp_server.status())["external_llm_tools"] is False
        finally:
            monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
            importlib.reload(mcp_server)

    def test_safe_entry_forces_env_before_delegating(self, monkeypatch):
        import importlib
        from engram import mcp_server, mcp_safe
        monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
        seen = {}

        def fake_server_main():
            seen["env"] = os.environ.get("ENGRAM_SAFE_MODE")

        monkeypatch.setattr(mcp_server, "main", fake_server_main)
        mcp_safe.main()
        assert seen["env"] == "1"
        monkeypatch.delenv("ENGRAM_SAFE_MODE", raising=False)
        importlib.reload(mcp_server)
