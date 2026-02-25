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
    _extract_symbols,
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


class TestExtractSymbols:

    def test_python_class_and_def(self):
        content = "class Foo:\n    pass\n\ndef bar():\n    pass\n\nasync def baz():\n    pass\n"
        assert _extract_symbols(content, ".py") == ["Foo", "bar", "baz"]

    def test_unknown_extension_returns_empty(self):
        assert _extract_symbols("key: value", ".yaml") == []

    def test_max_lines_limit(self):
        content = "\n".join(f"def func_{i}(): pass" for i in range(200))
        symbols = _extract_symbols(content, ".py", max_lines=5)
        assert len(symbols) == 5

    def test_deduplication(self):
        content = "def foo(): pass\ndef foo(): pass\n"
        assert _extract_symbols(content, ".py") == ["foo"]

    def test_go_func(self):
        content = "func main() {\n}\n\nfunc (s *Server) Handle() {\n}\n"
        assert _extract_symbols(content, ".go") == ["main", "Handle"]

    def test_rust_symbols(self):
        content = "pub struct Config {\n}\n\npub fn new() -> Config {\n}\n\nenum State {\n}\n"
        assert _extract_symbols(content, ".rs") == ["Config", "new", "State"]


class TestRicherMutationCapture:

    def test_edit_short_change_inline(self, hook_project):
        """Single-line edit produces inline 'old' -> 'new' format."""
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "math.py"),
                "old_string": "return x + 1",
                "new_string": "return x + 2",
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            content = events[0].content
            assert "Edited" in content
            assert "return x + 1" in content
            assert "return x + 2" in content
            assert "->" in content
        finally:
            store.close()

    def test_edit_with_description(self, hook_project):
        """Description is included in the Edit summary."""
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "auth.py"),
                "old_string": "return False",
                "new_string": "return True",
                "description": "Fix login bug",
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            content = events[0].content
            assert "Fix login bug" in content
            assert "src/auth.py" in content
        finally:
            store.close()

    def test_edit_long_change_diff_format(self, hook_project):
        """Multi-line edit produces unified diff format with @@ markers."""
        old = "\n".join(f"    x{i} = {i}" for i in range(10))
        new = "\n".join(f"    x{i} = {i * 10}" for i in range(10))
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "config.py"),
                "old_string": old,
                "new_string": new,
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            content = events[0].content
            assert "@@" in content
            assert "-" in content
            assert "+" in content
        finally:
            store.close()

    def test_edit_no_old_new_graceful(self, hook_project):
        """Edit with no old_string/new_string still creates an event."""
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "empty.py"),
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            assert "Edited" in events[0].content
            assert "src/empty.py" in events[0].content
        finally:
            store.close()

    def test_write_new_file_python_symbols(self, hook_project):
        """Write new Python file extracts class/def symbols."""
        content = "class Foo:\n    pass\n\ndef bar():\n    pass\n"
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(hook_project / "src" / "new_module.py"),
                "content": content,
            },
            "tool_response": {"text": "The file has been created successfully."},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            evt = events[0].content
            assert "Created" in evt
            assert "new_module.py" in evt
            assert "Foo" in evt
            assert "bar" in evt
            assert "(5 lines)" in evt
        finally:
            store.close()

    def test_write_overwrite_verb(self, hook_project):
        """Write overwrite uses 'Wrote' when response doesn't say 'created'."""
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(hook_project / "src" / "existing.py"),
                "content": "class Foo:\n    pass\n",
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            assert "Wrote" in events[0].content
            assert "Created" not in events[0].content
        finally:
            store.close()

    def test_write_no_content_graceful(self, hook_project):
        """Write with missing content field gives (0 lines)."""
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(hook_project / "src" / "nocon.py"),
            },
            "tool_response": {},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            assert "(0 lines)" in events[0].content
        finally:
            store.close()

    def test_write_non_code_file(self, hook_project):
        """Write to .yaml produces line count but no symbols."""
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(hook_project / "config.yaml"),
                "content": "key: value\nother: stuff\n",
            },
            "tool_response": {},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            content = events[0].content
            assert "config.yaml" in content
            assert "(2 lines)" in content
        finally:
            store.close()

    def test_huge_edit_truncated(self, hook_project):
        """Very large diff is truncated at 2000 chars with [truncated] marker."""
        old = "\n".join(f"line_{i} = {i}" for i in range(200))
        new = "\n".join(f"line_{i} = {i + 1}" for i in range(200))
        stdin_data = {
            "session_id": "sess-abc12345",
            "cwd": str(hook_project),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(hook_project / "src" / "huge.py"),
                "old_string": old,
                "new_string": new,
            },
            "tool_response": {"success": True},
        }
        handle_post_tool_use(stdin_data, hook_project)
        store = EventStore(hook_project / ".engram" / "events.db")
        try:
            events = store.recent_by_type(EventType.MUTATION, limit=10)
            assert len(events) == 1
            assert len(events[0].content) <= 2000
            assert "[truncated]" in events[0].content
        finally:
            store.close()
