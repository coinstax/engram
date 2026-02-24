# Session Intent — Final Implementation Spec (Feature #6)

*Validated via consultation conv-63e0f33c4097 with GPT-4o, Gemini Flash, and Grok. Unanimous consensus on all design decisions.*

## Problem

No way to declare "I'm working on X this session." Briefings, conflict detection, and multi-agent awareness all need to know what agents are currently focused on. Without session tracking:
- Briefings can't auto-detect scope (must pass `--focus` manually every time)
- No visibility into concurrent agent activity
- Conflict detection (#7) and multi-agent awareness (#11) are blocked

## Data Model

```python
@dataclass
class Session:
    id: str                          # "sess-" + 8-char hex
    agent_id: str                    # e.g. "claude-code", "cursor", "aider"
    focus: str                       # free-text: "refactoring auth module"
    scope: list[str] | None = None   # file paths: ["src/auth/"], unvalidated
    started_at: str = ""             # ISO 8601 UTC
    ended_at: str | None = None      # None while active
    description: str | None = None   # optional longer context
```

## Schema (v5 Migration)

### New table

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    focus TEXT NOT NULL,
    scope TEXT,                       -- JSON array of paths (unvalidated, consistent with events)
    description TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE INDEX idx_sessions_active ON sessions(ended_at) WHERE ended_at IS NULL;
CREATE INDEX idx_sessions_agent ON sessions(agent_id);
```

### New column on events table

```sql
ALTER TABLE events ADD COLUMN session_id TEXT;
```

Add `session_id: str | None = None` to the Event dataclass.

**Rationale** (unanimous from all 3 models): Direct linkage between events and sessions is foundational for session summaries, conflict detection by actual files modified (not just intended scope), and briefing relevance. The migration cost is a one-time single-column ALTER on a local SQLite DB.

## Store Methods (store.py)

```python
def insert_session(self, session: Session) -> Session
def get_session(self, session_id: str) -> Session | None
def end_session(self, session_id: str, ended_at: str | None = None) -> Session
def list_sessions(self, active_only: bool = True, agent_id: str | None = None) -> list[Session]
def get_active_session(self, agent_id: str) -> Session | None
def cleanup_stale_sessions(self, timeout_hours: int = 24) -> int  # returns count ended
```

The existing `insert()` method for events should accept the optional `session_id`.

## CLI Commands (cli.py)

```
engram session start --focus "refactoring auth module" --scope src/auth/
engram session end [SESSION_ID]           # ends most recent active if no ID
engram session ls [--all]                 # active only by default
engram session show [SESSION_ID]          # details of specific or current session
```

**No `update` command.** If focus changes, end the old session and start a new one. This keeps the API simple and maintains clear session boundaries.

## MCP Tools (mcp_server.py)

```python
@mcp.tool()
def session_start(focus: str, scope: list[str] | None = None,
                  agent_id: str = "claude-code", description: str | None = None) -> str

@mcp.tool()
def session_end(session_id: str | None = None, agent_id: str = "claude-code") -> str

@mcp.tool()
def list_sessions(active_only: bool = True) -> str
```

The existing `post_event` tool gains an optional `session_id` parameter, defaulting to the active session for the agent if not provided.

## Hook Integration (hooks.py)

### SessionStart hook (`handle_session_start`)

- Auto-register a session when Claude Code starts
- If an active session exists for this agent, end it first (single-session-per-agent)
- Focus defaults to project name; scope defaults to None (not project root — too broad)
- Generate briefing after session registration (existing behavior)

### PostToolUse hook (`handle_post_tool_use`)

- When creating mutation/outcome events, look up the active session for the agent
- If found, set `session_id` on the event
- If no active session, leave `session_id` as None (don't block event creation)

## Briefing Integration (briefing.py)

### New field on BriefingResult

```python
active_sessions: list[Session] = field(default_factory=list)
```

### Auto-focus from session

In `generate()`:
- If `focus` param not provided, look up active session for the calling agent
- If session has `scope`, use session `scope` as briefing scope for relevance scoring
- If session has `focus` (free-text), note it in the briefing header
- Always indicate in output when briefing is auto-scoped: "Briefing scoped to session: refactoring auth module [src/auth/]"

### Active Sessions section

Show between critical warnings and focus-relevant sections:

```
## Active Sessions (2)
[sess-a1b2c3d4] claude-code: "refactoring auth module" (src/auth/) — started 2h ago
[sess-e5f6g7h8] cursor: "adding tests" (tests/) — started 30m ago
```

## Stale Session Cleanup

**Trigger:** On any session-related command (`session start`, `session end`, `session ls`, `session show`) and during briefing generation.

**Behavior:** Sessions older than 24h with `ended_at IS NULL` are auto-ended with `ended_at` set to `started_at + 24h`.

**Threshold:** 24h constant for v1. Not exposed as config yet, but isolated in a constant (`STALE_SESSION_HOURS = 24`) for easy future configuration.

## Edge Cases

1. **Multiple active sessions per agent**: Not allowed. Starting a new session auto-ends the previous one.
2. **No scope**: Valid. Focus is free-text and useful alone for briefing context.
3. **Agent crash**: Stale cleanup handles it (24h auto-end on next session command).
4. **Agent ID collisions**: Acceptable for v1. Multi-agent awareness (#11) will add richer identity.
5. **Session during event creation**: If no active session exists, `session_id` is None — never block event creation.
6. **Empty scope list `[]`**: Treated same as None (no scope).

## What This Enables

- **Conflict Detection (#7)**: Compare active session scopes AND actual events tagged to sessions
- **Multi-Agent Awareness (#11)**: `engram who` shows active sessions
- **Smarter Briefing Ranking (#12)**: Session scope for relevance scoring
- **Subscriptions (#14)**: Watch session scopes for relevant events

## Files to Modify

| File | Changes |
|------|---------|
| `models.py` | Add `Session` dataclass, add `session_id` to `Event` |
| `store.py` | Schema v5 migration (sessions table + events.session_id), session CRUD, stale cleanup |
| `cli.py` | `session` command group (start/end/ls/show) |
| `mcp_server.py` | `session_start`, `session_end`, `list_sessions` tools; add `session_id` to `post_event` |
| `hooks.py` | Auto-register session on SessionStart; tag events with session_id in PostToolUse |
| `briefing.py` | Active sessions section, auto-focus from session |
| `formatting.py` | Session formatting helpers |
| `tests/test_sessions.py` | New test module |
| `tests/conftest.py` | Session fixtures |

## Build Order

1. Models + Schema (Session dataclass, Event.session_id, v5 migration)
2. Store methods (CRUD + stale cleanup)
3. Tests for store layer
4. CLI commands
5. MCP tools
6. Hook integration (auto-register + auto-tag)
7. Briefing integration (active sessions section + auto-focus)
8. Formatting
9. Integration tests

## Test Plan

1. **Store tests**: insert, get, end, list (active/all), get_active_session, stale cleanup, session_id on events
2. **CLI tests**: session start/end/ls/show with various options
3. **MCP tests**: session_start, session_end, list_sessions
4. **Hook tests**: auto-register on session start, auto-end previous, auto-tag events
5. **Briefing tests**: active sessions section, auto-focus from session, indicator message
6. **Edge cases**: multiple sessions per agent (auto-end), no scope, stale cleanup threshold, empty scope list
