"""Claude Code hooks — passive observation of agent activity."""

import difflib
import json
import re
import time
from pathlib import Path

from engram.models import Event, EventType, Session
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

# Structural symbol patterns by file extension (for Write tool summaries)
_STRUCT_PATTERNS: dict[str, re.Pattern] = {
    ".py": re.compile(r"^(?:async\s+)?(?:class|def)\s+(\w+)"),
    ".js": re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\()"
    ),
    ".ts": re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"(?:function\s+(\w+)|class\s+(\w+)|interface\s+(\w+)|type\s+(\w+)\s*=)"
    ),
    ".rs": re.compile(
        r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
        r"(?:fn\s+(\w+)|struct\s+(\w+)|enum\s+(\w+)|impl\s+(\w+))"
    ),
    ".go": re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)"),
}

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


def _extract_symbols(content: str, ext: str, max_lines: int = 100) -> list[str]:
    """Extract top-level symbol names from file content using lightweight regex."""
    pattern = _STRUCT_PATTERNS.get(ext.lower())
    if not pattern:
        return []
    symbols: list[str] = []
    for line in content.splitlines()[:max_lines]:
        m = pattern.match(line.strip())
        if m:
            name = next((g for g in m.groups() if g), None)
            if name and name not in symbols:
                symbols.append(name)
    return symbols


def _summarize_write(rel_path: str, tool_input: dict, tool_response: dict) -> str:
    """Generate a summary for a Write tool mutation."""
    content: str = tool_input.get("content") or ""
    lines = content.splitlines()
    line_count = len(lines)

    # Detect new vs overwrite from tool_response
    resp_text = ""
    if isinstance(tool_response, dict):
        # Claude Code may put result text in various fields
        for key in ("text", "stdout", "message"):
            val = tool_response.get(key, "")
            if val and isinstance(val, str):
                resp_text = val.lower()
                break
    elif isinstance(tool_response, str):
        resp_text = tool_response.lower()

    verb = "Created" if "created" in resp_text else "Wrote"
    header = f"{verb} {rel_path} ({line_count} lines)"

    ext = Path(rel_path).suffix.lower()
    symbols = _extract_symbols(content, ext) if content else []

    if symbols:
        max_syms = 8
        sym_str = ", ".join(symbols[:max_syms])
        if len(symbols) > max_syms:
            sym_str += f", +{len(symbols) - max_syms} more"
        return f"{header}: {sym_str}"

    return header


def _summarize_edit(rel_path: str, tool_input: dict) -> str:
    """Generate a summary for an Edit tool mutation."""
    old_string: str = tool_input.get("old_string") or ""
    new_string: str = tool_input.get("new_string") or ""
    description: str = tool_input.get("description") or ""

    header = f"Edited {rel_path}"
    if description:
        header = f"{header}: {description}"

    # If no old/new strings provided, return header only
    if not old_string and not new_string:
        return header

    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()

    # Build unified diff, strip file header lines
    raw_diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=1))
    diff_lines = [l for l in raw_diff if not l.startswith("---") and not l.startswith("+++")]

    # Count purely changed lines (not context)
    changed = [l for l in diff_lines if l.startswith("+") or l.startswith("-")]

    if not changed:
        return header

    if len(changed) <= 6:
        # Short inline format
        removed = [l[1:].strip() for l in changed if l.startswith("-")]
        added = [l[1:].strip() for l in changed if l.startswith("+")]
        r_str = "; ".join(removed) if removed else ""
        a_str = "; ".join(added) if added else ""
        if r_str and a_str:
            return f"{header} '{r_str}' -> '{a_str}'"
        elif a_str:
            return f"{header} +'{a_str}'"
        else:
            return f"{header} -'{r_str}'"
    else:
        # Compact diff format
        diff_str = "\n".join(diff_lines)
        return f"{header}\n{diff_str}"


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
    tool_name = stdin_data.get("tool_name", "")
    tool_response = stdin_data.get("tool_response") or {}

    if tool_name == "Edit":
        content = _summarize_edit(rel_path, tool_input)
    else:
        content = _summarize_write(rel_path, tool_input, tool_response)

    if len(content) > 2000:
        content = content[:1988] + "\n[truncated]"

    # Auto-tag with active session
    agent_id = f"hook-{session_id[:8]}"
    active_session = store.get_active_session(agent_id)
    if not active_session:
        # Try the base agent ID pattern too
        active_session = store.get_active_session("claude-code")

    event = Event(
        id="", timestamp="",
        event_type=EventType.MUTATION,
        agent_id=agent_id,
        content=content,
        scope=[rel_path],
        session_id=active_session.id if active_session else None,
    )
    store.insert(event)

    # Auto-checkpoint when a context file is written
    _maybe_auto_checkpoint(file_path, rel_path, agent_id, active_session, store, project_dir)


def _maybe_auto_checkpoint(file_path: str, rel_path: str, agent_id: str,
                           active_session, store: EventStore,
                           project_dir: Path) -> None:
    """Auto-run checkpoint when a context file is written to .claude/context/."""
    # Check if the file is a context markdown file
    if ".claude/context/" not in rel_path and ".claude/context/" not in file_path:
        return
    if not file_path.endswith(".md"):
        return

    abs_path = Path(file_path)
    if not abs_path.is_file():
        return

    try:
        from engram.checkpoint import CheckpointEngine
        engine = CheckpointEngine(store, project_dir=project_dir)
        engine.save(
            file_path=str(abs_path),
            agent_id=agent_id,
            enrich=True,
            session_id=active_session.id if active_session else None,
        )
    except Exception:
        pass  # Non-fatal — checkpoint is a bonus, not critical


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

    # Auto-tag with active session
    agent_id = f"hook-{session_id[:8]}"
    active_session = store.get_active_session(agent_id)
    if not active_session:
        active_session = store.get_active_session("claude-code")

    event = Event(
        id="", timestamp="",
        event_type=EventType.OUTCOME,
        agent_id=agent_id,
        content=content,
        session_id=active_session.id if active_session else None,
    )
    store.insert(event)


def handle_session_start(stdin_data: dict, project_dir: Path) -> str:
    """Handle SessionStart hook. Auto-registers session, returns briefing."""
    store = _get_store(project_dir)
    if not store:
        return ""

    try:
        agent_id = "claude-code"

        # Stale cleanup
        store.cleanup_stale_sessions()

        # Auto-end previous active session for this agent
        active = store.get_active_session(agent_id)
        if active:
            store.end_session(active.id)

        # Auto-register new session
        project_name = store.get_meta("project_name") or project_dir.name
        sess = Session(
            id="", agent_id=agent_id,
            focus=f"Working on {project_name}",
        )
        store.insert_session(sess)

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
