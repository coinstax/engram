"""Claude Code hooks — passive observation of agent activity."""

import json
import time
from pathlib import Path

from engram.models import Event, EventType
from engram.store import EventStore
from engram.briefing import BriefingGenerator
from engram.formatting import format_briefing_compact

ENGRAM_DIR = ".engram"
DB_NAME = "events.db"
HOOK_STATE_FILE = ".hook_state"
DEBOUNCE_SECONDS = 5

# Commands too trivial to log as outcomes
TRIVIAL_COMMANDS = frozenset({
    "ls", "cat", "pwd", "echo", "head", "tail", "wc", "which",
    "whoami", "date", "cd", "true", "false", "type", "file",
    "stat", "realpath", "dirname", "basename", "env", "printenv",
})

# Hook configuration for .claude/settings.json
HOOK_CONFIG = {
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Write|Edit",
                "hooks": [{
                    "type": "command",
                    "command": "engram hook post-tool-use",
                    "timeout": 10,
                }],
            },
            {
                "matcher": "Bash",
                "hooks": [{
                    "type": "command",
                    "command": "engram hook post-tool-use",
                    "timeout": 10,
                }],
            },
        ],
        "SessionStart": [
            {
                "matcher": "startup",
                "hooks": [{
                    "type": "command",
                    "command": "engram hook session-start",
                    "timeout": 15,
                }],
            },
        ],
    }
}


def _get_store(project_dir: Path) -> EventStore | None:
    """Get EventStore if Engram is initialized, else None."""
    db_path = project_dir / ENGRAM_DIR / DB_NAME
    if not db_path.exists():
        return None
    return EventStore(db_path)


def _read_hook_state(project_dir: Path) -> dict:
    """Read debounce state file."""
    state_path = project_dir / ENGRAM_DIR / HOOK_STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_hook_state(project_dir: Path, state: dict) -> None:
    """Write debounce state file."""
    state_path = project_dir / ENGRAM_DIR / HOOK_STATE_FILE
    try:
        state_path.write_text(json.dumps(state))
    except OSError:
        pass  # Non-fatal — worst case we log a duplicate


def _should_debounce(project_dir: Path, filepath: str) -> bool:
    """Check if a file mutation should be debounced (same file within window)."""
    state = _read_hook_state(project_dir)
    last_time = state.get(filepath)
    now = time.time()

    if last_time and (now - last_time) < DEBOUNCE_SECONDS:
        return True

    state[filepath] = now
    # Clean old entries (older than 60s)
    state = {k: v for k, v in state.items() if (now - v) < 60}
    _write_hook_state(project_dir, state)
    return False


def _extract_command_name(command: str) -> str:
    """Extract the first meaningful command from a shell command string."""
    cmd = command.strip()
    # Handle leading env vars like VAR=val cmd
    for token in cmd.split():
        if "=" not in token:
            # Strip path prefix
            return token.split("/")[-1]
    return cmd.split()[0] if cmd else ""


def handle_post_tool_use(stdin_data: dict, project_dir: Path) -> None:
    """Handle PostToolUse hook events from Claude Code."""
    store = _get_store(project_dir)
    if not store:
        return

    try:
        tool_name = stdin_data.get("tool_name", "")
        tool_input = stdin_data.get("tool_input", {})

        if tool_name in ("Write", "Edit"):
            _handle_file_mutation(tool_input, stdin_data, project_dir, store)
        elif tool_name == "Bash":
            _handle_bash_outcome(tool_input, stdin_data, store)
    finally:
        store.close()


def _handle_file_mutation(tool_input: dict, stdin_data: dict,
                          project_dir: Path, store: EventStore) -> None:
    """Record a file write/edit as a mutation event."""
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return

    # Make path relative to project if possible
    try:
        rel_path = str(Path(file_path).relative_to(project_dir))
    except ValueError:
        rel_path = file_path

    if _should_debounce(project_dir, rel_path):
        return

    session_id = stdin_data.get("session_id", "unknown")
    content = f"Modified {rel_path}"

    # Add description from Edit tool if available
    description = tool_input.get("description", "")
    if description:
        content = f"Modified {rel_path}: {description}"

    if len(content) > 2000:
        content = content[:2000]

    event = Event(
        id="", timestamp="",
        event_type=EventType.MUTATION,
        agent_id=f"hook-{session_id[:8]}",
        content=content,
        scope=[rel_path],
    )
    store.insert(event)


def _handle_bash_outcome(tool_input: dict, stdin_data: dict,
                         store: EventStore) -> None:
    """Record a bash command execution as an outcome event."""
    command = tool_input.get("command", "")
    if not command:
        return

    cmd_name = _extract_command_name(command)
    if cmd_name in TRIVIAL_COMMANDS:
        return

    session_id = stdin_data.get("session_id", "unknown")

    # Truncate long commands
    cmd_summary = command if len(command) <= 200 else command[:200] + "..."
    content = f"Ran: {cmd_summary}"

    if len(content) > 2000:
        content = content[:2000]

    event = Event(
        id="", timestamp="",
        event_type=EventType.OUTCOME,
        agent_id=f"hook-{session_id[:8]}",
        content=content,
    )
    store.insert(event)


def handle_session_start(stdin_data: dict, project_dir: Path) -> str:
    """Handle SessionStart hook. Returns briefing text for context injection."""
    store = _get_store(project_dir)
    if not store:
        return ""

    try:
        gen = BriefingGenerator(store)
        result = gen.generate()
        return format_briefing_compact(result)
    finally:
        store.close()


def install_hooks(project_dir: Path) -> dict:
    """Install Claude Code hooks into .claude/settings.json.

    Returns dict with 'message' key describing what happened.
    """
    claude_dir = project_dir / ".claude"
    settings_path = claude_dir / "settings.json"

    # Read existing settings or start fresh
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings = {}

    # Check if hooks are already installed
    existing_hooks = settings.get("hooks", {})
    if "PostToolUse" in existing_hooks and "SessionStart" in existing_hooks:
        # Check if our hooks are already there
        has_engram = any(
            "engram" in str(h)
            for hook_list in existing_hooks.get("PostToolUse", [])
            for h in hook_list.get("hooks", [])
        )
        if has_engram:
            return {"message": "Engram hooks already installed.", "status": "exists"}

    # Merge hooks — preserve existing hooks, add ours
    if "hooks" not in settings:
        settings["hooks"] = {}

    for event_name, hook_entries in HOOK_CONFIG["hooks"].items():
        if event_name not in settings["hooks"]:
            settings["hooks"][event_name] = []
        # Add our hooks (avoid duplicates)
        existing_commands = set()
        for entry in settings["hooks"][event_name]:
            for h in entry.get("hooks", []):
                existing_commands.add(h.get("command", ""))

        for entry in hook_entries:
            cmd = entry["hooks"][0]["command"]
            if cmd not in existing_commands:
                settings["hooks"][event_name].append(entry)

    # Write settings
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    return {
        "message": f"Engram hooks installed in {settings_path}",
        "status": "installed",
    }
