"""Tests for the Engram CLI."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from engram.cli import cli
from engram.models import Event, EventType
from engram.store import EventStore


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def git_project(tmp_path):
    """Create a minimal git project for CLI testing."""
    project = tmp_path / "cli-test"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=project, capture_output=True)
    (project / "main.py").write_text("print('hello')")
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=project, capture_output=True)
    (project / "auth.py").write_text("def login(): pass")
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Fix login bug"], cwd=project, capture_output=True)
    return project


class TestInit:

    def test_init_creates_engram_dir(self, runner, git_project):
        result = runner.invoke(cli, ["-p", str(git_project), "init"])
        assert result.exit_code == 0
        assert (git_project / ".engram" / "events.db").exists()
        assert "Engram initialized" in result.output
        assert "events seeded" in result.output

    def test_init_already_initialized(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, ["-p", str(git_project), "init"])
        assert "already initialized" in result.output

    def test_init_writes_claude_md(self, runner, git_project):
        result = runner.invoke(cli, ["-p", str(git_project), "init"])
        assert "CLAUDE.md" in result.output
        claude_md = git_project / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "engram briefing" in content
        assert "## Project Memory (Engram)" in content


class TestPost:

    def test_post_event(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, [
            "-p", str(git_project), "post",
            "-t", "warning", "-c", "Don't touch the database"
        ])
        assert result.exit_code == 0
        assert "[warning]" in result.output

    def test_post_with_scope(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, [
            "-p", str(git_project), "post",
            "-t", "mutation", "-c", "Added validation",
            "-s", "src/api.py"
        ])
        assert result.exit_code == 0
        assert "src/api.py" in result.output

    def test_post_json_format(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, [
            "-p", str(git_project), "post",
            "-t", "discovery", "-c", "Found a bug",
            "-f", "json"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["event_type"] == "discovery"


class TestQuery:

    def test_query_text(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        runner.invoke(cli, [
            "-p", str(git_project), "post",
            "-t", "warning", "-c", "JWT tokens expire too fast"
        ])
        result = runner.invoke(cli, ["-p", str(git_project), "query", "JWT"])
        assert result.exit_code == 0
        assert "JWT" in result.output

    def test_query_by_type(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        runner.invoke(cli, [
            "-p", str(git_project), "post",
            "-t", "warning", "-c", "Watch out"
        ])
        result = runner.invoke(cli, [
            "-p", str(git_project), "query", "-t", "warning"
        ])
        assert result.exit_code == 0
        assert "[warning]" in result.output

    def test_query_no_results(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, [
            "-p", str(git_project), "query", "nonexistent_xyz_term"
        ])
        assert "(no events)" in result.output


class TestBriefing:

    def test_briefing_compact(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        runner.invoke(cli, [
            "-p", str(git_project), "post",
            "-t", "warning", "-c", "Migration pending"
        ])
        result = runner.invoke(cli, ["-p", str(git_project), "briefing"])
        assert result.exit_code == 0
        assert "# Engram Briefing" in result.output

    def test_briefing_json(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, [
            "-p", str(git_project), "briefing", "-f", "json"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "project_name" in data


class TestStatus:

    def test_status(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, ["-p", str(git_project), "status"])
        assert result.exit_code == 0
        assert "Events:" in result.output
        assert "DB size:" in result.output

    def test_status_json(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, ["-p", str(git_project), "status", "-f", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total_events" in data
        assert "db_size_bytes" in data


class TestGC:

    def test_gc_dry_run(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        # Insert an old mutation
        store = EventStore(git_project / ".engram" / "events.db")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        store.insert(Event(
            id="", timestamp=old_ts, event_type=EventType.MUTATION,
            agent_id="test", content="Old mutation",
        ))
        store.close()

        result = runner.invoke(cli, ["-p", str(git_project), "gc", "--dry-run"])
        assert result.exit_code == 0
        assert "Would archive" in result.output

    def test_gc_archives(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        store = EventStore(git_project / ".engram" / "events.db")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        store.insert(Event(
            id="", timestamp=old_ts, event_type=EventType.MUTATION,
            agent_id="test", content="Old mutation",
        ))
        store.close()

        result = runner.invoke(cli, ["-p", str(git_project), "gc"])
        assert result.exit_code == 0
        assert "Archived" in result.output

    def test_gc_nothing_to_archive(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, ["-p", str(git_project), "gc"])
        assert result.exit_code == 0
        assert "No events to archive" in result.output


class TestHooksInstall:

    def test_hooks_install(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        result = runner.invoke(cli, ["-p", str(git_project), "hooks", "install"])
        assert result.exit_code == 0
        settings_path = git_project / ".claude" / "settings.json"
        assert settings_path.exists()


class TestHookCommands:

    def test_hook_post_tool_use_write(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        stdin_json = json.dumps({
            "session_id": "sess-test123",
            "cwd": str(git_project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(git_project / "src" / "foo.py")},
            "tool_response": {"success": True},
        })
        result = runner.invoke(
            cli, ["-p", str(git_project), "hook", "post-tool-use"],
            input=stdin_json,
        )
        assert result.exit_code == 0

        store = EventStore(git_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.MUTATION, limit=10)
        assert len(events) >= 1
        assert "src/foo.py" in events[0].content
        store.close()

    def test_hook_session_start(self, runner, git_project):
        runner.invoke(cli, ["-p", str(git_project), "init"])
        # Add a warning so briefing has content
        store = EventStore(git_project / ".engram" / "events.db")
        store.insert(Event(
            id="", timestamp="",
            event_type=EventType.WARNING, agent_id="test",
            content="Don't touch the schema",
        ))
        store.close()

        stdin_json = json.dumps({
            "session_id": "sess-test123",
            "cwd": str(git_project),
        })
        result = runner.invoke(
            cli, ["-p", str(git_project), "hook", "session-start"],
            input=stdin_json,
        )
        assert result.exit_code == 0
        assert "Engram Briefing" in result.output
