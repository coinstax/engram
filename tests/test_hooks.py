"""Tests for Claude Code hooks integration."""

import json
import time
import pytest
from pathlib import Path

from engram.hooks import (
    handle_post_tool_use,
    handle_session_start,
    install_hooks,
    _extract_command_name,
    _should_debounce,
)
from engram.models import EventType
from engram.store import EventStore


@pytest.fixture
def hook_project(tmp_path):
    """Project directory with initialized Engram store."""
    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    db_path = engram_dir / "events.db"
    store = EventStore(db_path)
    store.initialize()
    store.set_meta("project_name", "test-project")
    store.close()
    return tmp_path


def _get_events(project_dir):
    """Helper to read all events from the store."""
    store = EventStore(project_dir / ".engram" / "events.db")
    events = store.query_fts("*", limit=100)
    # Fallback: if FTS doesn't match *, query all
    if not events:
        from engram.models import QueryFilter
        events = store.query_structured(QueryFilter(limit=100))
    count = store.count()
    store.close()
    return count


class TestFileMutationHook:

    def test_write_tool_creates_mutation_event(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(hook_project / "src" / "foo.py")},
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.MUTATION, limit=10)
        assert len(events) == 1
        assert "src/foo.py" in events[0].content
        assert events[0].scope == ["src/foo.py"]
        assert events[0].agent_id.startswith("hook-")
        store.close()

    def test_edit_tool_creates_mutation_event(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {"file_path": str(hook_project / "src" / "bar.py")},
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.MUTATION, limit=10)
        assert len(events) == 1
        assert "src/bar.py" in events[0].content
        store.close()

    def test_edit_tool_with_description(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "auth.py"),
                "description": "Refactored auth logic",
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.MUTATION, limit=10)
        assert len(events) == 1
        assert "Refactored auth logic" in events[0].content
        assert "src/auth.py" in events[0].content
        store.close()

    def test_edit_tool_long_description_truncated(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "big.py"),
                "description": "x" * 2500,
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.MUTATION, limit=10)
        assert len(events) == 1
        assert len(events[0].content) <= 2000
        store.close()

    def test_debounce_skips_rapid_writes(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(hook_project / "src" / "rapid.py")},
            "tool_response": {"success": True},
        }
        # First write should go through
        handle_post_tool_use(stdin_data, hook_project)
        # Second write within debounce window should be skipped
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.MUTATION, limit=10)
        assert len(events) == 1  # Only one, not two
        store.close()


class TestBashOutcomeHook:

    def test_bash_creates_outcome_event(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/ -v"},
            "tool_response": {"stdout": "all passed"},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        events = store.recent_by_type(EventType.OUTCOME, limit=10)
        assert len(events) == 1
        assert "pytest" in events[0].content
        store.close()

    def test_trivial_commands_skipped(self, hook_project):
        for cmd in ["ls", "cat foo.txt", "pwd", "echo hello", "head -5 file"]:
            stdin_data = {
                "session_id": "sess-abc12345",
                "cwd": str(hook_project),
                "tool_name": "Bash",
                "tool_input": {"command": cmd},
                "tool_response": {},
            }
            handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        assert store.count() == 0
        store.close()

    def test_non_trivial_commands_recorded(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Bash",
            "tool_input": {"command": "npm install express"},
            "tool_response": {},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        assert store.count() == 1
        store.close()


class TestSessionStartHook:

    def test_session_start_returns_briefing(self, hook_project):
        # Add a warning event so briefing has content
        store = EventStore(hook_project / ".engram" / "events.db")
        from engram.models import Event
        store.insert(Event(
            id="", timestamp="",
            event_type=EventType.WARNING,
            agent_id="test",
            content="Don't touch the database schema",
        ))
        store.close()

        output = handle_session_start(
            {"session_id": "sess-abc", "cwd": str(hook_project)},
            hook_project,
        )
        assert "Engram Briefing" in output
        assert "database schema" in output

    def test_session_start_no_engram_returns_empty(self, tmp_path):
        output = handle_session_start(
            {"session_id": "sess-abc", "cwd": str(tmp_path)},
            tmp_path,
        )
        assert output == ""


class TestInstallHooks:

    def test_install_creates_settings(self, hook_project):
        result = install_hooks(hook_project)
        assert result["status"] == "installed"

        settings_path = hook_project / ".claude" / "settings.json"
        assert settings_path.exists()

        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "PostToolUse" in settings["hooks"]
        assert "SessionStart" in settings["hooks"]

    def test_install_is_idempotent(self, hook_project):
        install_hooks(hook_project)
        result = install_hooks(hook_project)
        assert result["status"] == "exists"

        # Verify no duplicate entries
        settings = json.loads(
            (hook_project / ".claude" / "settings.json").read_text()
        )
        post_hooks = settings["hooks"]["PostToolUse"]
        engram_count = sum(
            1 for entry in post_hooks
            for h in entry.get("hooks", [])
            if "engram" in h.get("command", "")
        )
        assert engram_count == 2  # Write|Edit + Bash

    def test_install_preserves_existing_settings(self, hook_project):
        # Pre-existing settings
        claude_dir = hook_project / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text(json.dumps({
            "model": "claude-sonnet-4-6",
            "hooks": {
                "PostToolUse": [{
                    "matcher": "CustomTool",
                    "hooks": [{"type": "command", "command": "custom-script.sh"}],
                }]
            }
        }))

        install_hooks(hook_project)

        settings = json.loads(
            (claude_dir / "settings.json").read_text()
        )
        assert settings["model"] == "claude-sonnet-4-6"
        # Custom hook preserved
        custom_hooks = [
            e for e in settings["hooks"]["PostToolUse"]
            if e.get("matcher") == "CustomTool"
        ]
        assert len(custom_hooks) == 1


class TestAutoCheckpoint:

    def test_write_to_context_dir_creates_checkpoint(self, hook_project):
        # Create context dir and file
        ctx_dir = hook_project / ".claude" / "context"
        ctx_dir.mkdir(parents=True)
        ctx_file = ctx_dir / "session.md"
        ctx_file.write_text("# Context\n\n## Key Design Decisions\n\nSome decision\n")

        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(ctx_file)},
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        checkpoint = store.get_latest_checkpoint()
        assert checkpoint is not None
        assert "session.md" in checkpoint.file_path
        store.close()

    def test_write_to_non_context_dir_no_checkpoint(self, hook_project):
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(hook_project / "src" / "foo.py")},
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        store = EventStore(hook_project / ".engram" / "events.db")
        checkpoint = store.get_latest_checkpoint()
        assert checkpoint is None
        store.close()

    def test_auto_checkpoint_enriches_file(self, hook_project):
        # Seed a decision event
        store = EventStore(hook_project / ".engram" / "events.db")
        from engram.models import Event
        store.insert(Event(
            id="", timestamp="", event_type=EventType.DECISION,
            agent_id="cli", content="Use SQLite for zero-config local storage",
        ))
        store.close()

        # Create context file with a matching section
        ctx_dir = hook_project / ".claude" / "context"
        ctx_dir.mkdir(parents=True)
        ctx_file = ctx_dir / "session.md"
        ctx_file.write_text("# Context\n\n## Key Design Decisions\n\nOld stuff\n\n## Other\n")

        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {"file_path": str(ctx_file)},
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)

        content = ctx_file.read_text()
        assert "engram:start" in content
        assert "SQLite" in content


class TestExtractCommandName:

    def test_simple_command(self):
        assert _extract_command_name("pytest") == "pytest"

    def test_command_with_args(self):
        assert _extract_command_name("npm install express") == "npm"

    def test_command_with_path(self):
        assert _extract_command_name("/usr/bin/python3 script.py") == "python3"

    def test_command_with_env_var(self):
        assert _extract_command_name("NODE_ENV=prod node server.js") == "node"
