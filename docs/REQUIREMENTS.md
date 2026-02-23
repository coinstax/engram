# AgentBus — Inter-Agent Message Bus with Persistent Memory

## Vision

A lightweight, project-scoped communication and memory layer for AI agents. AgentBus enables agents to coordinate work, share discoveries, avoid conflicts, and build cumulative project knowledge across sessions — without requiring agents to be aware of each other's existence.

The primary users are AI agents. Humans are secondary consumers.

## Problem Statement

AI agents working on software projects suffer from four fundamental limitations:

1. **Amnesia** — Each session starts with zero memory of prior work
2. **Isolation** — No awareness of what other agents are doing concurrently
3. **Blindness** — No way to predict side effects of their actions on other agents' work
4. **No Learning** — Outcomes of past decisions are lost; mistakes repeat

These compound in multi-agent environments (parallel Claude Code sessions, mixed-model teams, CI/CD agents) into duplicated work, conflicting changes, stale assumptions, and wasted context window space.

## Design Principles

- **Agent-first** — CLI and API are primary interfaces; no UI required
- **Zero-config startup** — Drop into a project, it works
- **Local-first** — Everything runs locally; no cloud dependency
- **Minimal footprint** — SQLite + flat files; no servers required for basic usage
- **Flexible schema** — Agents can attach arbitrary metadata to events
- **Protocol-agnostic** — Works via CLI, HTTP, MCP, or direct file access
- **Non-intrusive** — Agents that don't know about AgentBus are unaffected

---

## Core Components

### 1. Event Store

The foundation. A structured, append-only log of agent activity.

#### Event Schema

```json
{
  "id": "evt-uuid",
  "agent_id": "claude-session-abc123",
  "agent_type": "claude-code",
  "timestamp": "2026-02-23T14:30:00Z",
  "event_type": "discovery | decision | warning | completion | blocker | assumption | question | mutation | outcome",
  "scope": ["src/auth/refresh.ts", "src/auth/middleware.ts"],
  "content": "Human-readable description of what happened or was found",
  "confidence": 0.9,
  "tags": ["auth", "bug", "jwt"],
  "references": {
    "files": ["src/auth/refresh.ts:47"],
    "events": ["evt-previous-uuid"],
    "tasks": ["task-1.2"],
    "urls": []
  },
  "metadata": {},
  "ttl": null,
  "supersedes": null
}
```

#### Event Types

| Type | Purpose | Example |
|------|---------|---------|
| `discovery` | Found something important about the codebase | "JWT refresh endpoint returns 401 instead of rotating token" |
| `decision` | Chose an approach; records rationale | "Using bcrypt over argon2 because existing infra uses it" |
| `warning` | Don't do X; records why | "Don't modify user_sessions table — migration pending" |
| `completion` | Finished a unit of work | "Auth middleware refactor complete, all tests passing" |
| `blocker` | Can't proceed; needs resolution | "Need DB credentials for staging environment" |
| `assumption` | Declaring something assumed true | "Assuming all API routes require auth unless decorated otherwise" |
| `question` | Needs input from human or agent | "Should we use soft deletes or hard deletes for user accounts?" |
| `mutation` | Changed files; records what and why | "Modified User model to add deletedAt field" |
| `outcome` | Records whether a prior action worked | "Fix from evt-789 broke session invalidation on password change" |

#### Event Lifecycle

- Events are **immutable** once written (append-only)
- Events can be **superseded** by newer events (soft invalidation)
- Events can have a **TTL** for ephemeral coordination signals
- Events can be **archived** after a configurable retention period

### 2. Semantic Query Interface

Agents need to ask questions in natural language and get relevant events back. Keyword search is insufficient — "what do we know about payments" must surface events about "Stripe webhook handling."

#### Query Modes

**Natural Language Query**
```
agent-bus query "What decisions were made about the auth system?"
agent-bus query "Has anything changed in src/api/ in the last 24h?"
agent-bus query "What was tried and failed for the payment bug?"
```

**Structured Query**
```
agent-bus query --scope="src/auth/*" --type=warning --since=24h
agent-bus query --tags=database --type=decision
agent-bus query --agent=claude-session-def --type=mutation
```

**Hybrid Query**
```
agent-bus query "auth problems" --type=warning,blocker --since=7d
```

#### Retrieval Strategy

1. **Exact match** on structured fields (scope, type, tags, agent_id)
2. **Embedding similarity** on content field for semantic search
3. **Recency weighting** — newer events rank higher by default
4. **Supersession filtering** — superseded events demoted unless explicitly requested
5. **Relevance scoring** — combined score from structure match + semantic similarity + recency

#### Embedding Storage

- Local embeddings generated on write (using a lightweight model like all-MiniLM-L6-v2 or similar)
- Stored in a vector-capable SQLite extension (sqlite-vss) or separate vector file
- No external API calls required for search
- Optional: use an LLM API for higher-quality embeddings if configured

### 3. Subscription / Watch System

Agents register interest in specific scopes, event types, or tags. When matching events arrive, they are surfaced.

#### Subscription Model

```json
{
  "subscriber_id": "claude-session-abc123",
  "watch_id": "watch-uuid",
  "filters": {
    "scope_patterns": ["src/db/schema/*", "src/types/shared.ts"],
    "event_types": ["mutation", "decision", "warning"],
    "tags": ["breaking-change"],
    "exclude_self": true
  },
  "delivery": {
    "method": "file | poll | webhook | mcp-notification",
    "target": ".agent-bus/notifications/abc123.jsonl"
  },
  "created_at": "2026-02-23T14:30:00Z",
  "expires_at": "2026-02-24T14:30:00Z"
}
```

#### Delivery Methods

1. **File-based** (default) — Notifications appended to a JSONL file the agent can check
2. **Polling** — Agent polls HTTP endpoint with a cursor/offset
3. **Webhook** — POST to a local endpoint when events match
4. **MCP notification** — For MCP-integrated agents, push via protocol

#### Notification Format

```json
{
  "notification_id": "notif-uuid",
  "watch_id": "watch-uuid",
  "event": { "...full event object..." },
  "priority": "normal | urgent",
  "summary": "Agent B modified the User type in src/types/shared.ts — added deletedAt field"
}
```

### 4. Conflict Detection

Automatic detection when agents are working on overlapping scopes or making contradictory decisions.

#### Conflict Types

| Conflict | Detection Method |
|----------|-----------------|
| **Scope overlap** | Two+ agents posting mutations to the same file paths |
| **Decision contradiction** | Two agents making opposing decisions on the same topic |
| **Stale assumption** | An assumption event references state that a subsequent mutation invalidated |
| **Dependency deadlock** | Agent A blocked on Agent B, and Agent B blocked on Agent A |

#### Conflict Response

- Generate a `conflict` event visible to all involved agents
- Include: which agents, what they're doing, what overlaps
- Do NOT attempt automatic resolution — just surface early
- Optionally escalate to human via notification

### 5. Project Briefing (Context Bootstrap)

A single-call summary that catches an agent up on project state. This is the "start of session" call.

#### Briefing Contents

```json
{
  "project_summary": {
    "last_activity": "2h ago",
    "total_events": 847,
    "active_period": "2026-02-15 to present"
  },
  "active_agents": [
    {
      "agent_id": "session-def",
      "agent_type": "claude-code",
      "working_on": "Auth refactor",
      "last_seen": "5m ago",
      "scope": ["src/auth/*"]
    }
  ],
  "recent_decisions": ["...last N decisions with rationale..."],
  "active_warnings": ["...unresolved warnings..."],
  "open_blockers": ["...things stuck..."],
  "open_questions": ["...unanswered questions..."],
  "recent_mutations": ["...files changed in last 24h with summaries..."],
  "stale_assumptions": ["...assumptions that may need revalidation..."],
  "recent_outcomes": ["...what worked and what didn't..."],
  "active_conflicts": ["...unresolved conflicts..."]
}
```

#### Briefing Options

```
agent-bus briefing                          # Full project briefing
agent-bus briefing --scope="src/auth/*"     # Scoped briefing
agent-bus briefing --since=24h              # Recent activity only
agent-bus briefing --compact                # Minimal token usage
agent-bus briefing --for-agent=frontend     # Filtered by relevance
```

### 6. Outcome Tracking

Links actions to their results, building project-specific knowledge about what works.

#### Outcome Event

```json
{
  "event_type": "outcome",
  "references": {
    "events": ["evt-789"]
  },
  "content": "Fix worked for JWT refresh but broke session invalidation on password change",
  "result": "partial_success | success | failure | regression",
  "lesson": "Refresh token rotation must also invalidate all active sessions",
  "tags": ["auth", "jwt", "lesson-learned"]
}
```

#### Lesson Extraction

Over time, outcome events accumulate into a queryable knowledge base:
```
agent-bus lessons "auth token handling"
agent-bus lessons --tag=database --result=failure
```

### 7. Channels / Scoping

Not every event is relevant to every agent.

#### Built-in Channels

- `#architecture` — System-level design decisions
- `#bugs` — Discovered issues and their status
- `#deployments` — What's deployed, what's pending
- `#questions` — Unanswered questions needing input

#### Automatic Scoping

- Events with `scope` fields are auto-indexed by file path
- Queries for `src/auth/*` automatically surface all events touching that path tree
- Agents can declare their working scope on connect, enabling automatic relevance filtering

---

## Interface Specifications

### CLI Interface

```bash
# Event Management
agent-bus post --type=discovery --scope="src/auth/*" --content="..." --tags=auth,bug
agent-bus post --type=decision --content="..." --confidence=0.8
agent-bus post --type=mutation --scope="src/api/users.ts" --content="Added email validation"

# Querying
agent-bus query "what do we know about auth?"
agent-bus query --type=warning --since=24h
agent-bus query --scope="src/db/*" --type=mutation,decision

# Session Management
agent-bus connect --agent-type=claude-code --scope="src/auth/*"
agent-bus disconnect
agent-bus heartbeat

# Subscriptions
agent-bus watch --scope="src/types/*" --type=mutation
agent-bus unwatch <watch-id>
agent-bus notifications                    # Check pending notifications

# Project Overview
agent-bus briefing
agent-bus briefing --compact
agent-bus lessons "topic"

# Administration
agent-bus init                             # Initialize in current project
agent-bus status                           # Bus health + active agents
agent-bus gc                               # Archive old events
agent-bus export --format=json             # Export event log
```

### MCP Server Interface

```
Tools:
  agent_bus_post_event       — Post an event to the bus
  agent_bus_query            — Query events (natural language or structured)
  agent_bus_briefing         — Get project briefing
  agent_bus_connect          — Register agent session
  agent_bus_disconnect       — Deregister agent session
  agent_bus_watch            — Subscribe to event patterns
  agent_bus_notifications    — Check pending notifications
  agent_bus_lessons          — Query outcome/lesson history
  agent_bus_status           — Bus health and active agents

Resources:
  agent-bus://briefing       — Current project briefing
  agent-bus://notifications  — Pending notifications for current agent
  agent-bus://conflicts      — Active conflicts
```

### HTTP API (Optional Local Server)

```
POST   /events              — Post event
GET    /events/query         — Query events
GET    /briefing             — Project briefing
POST   /agents/connect       — Register agent
DELETE /agents/{id}          — Deregister agent
POST   /watches              — Create subscription
GET    /notifications/{id}   — Poll notifications
GET    /lessons              — Query lessons
GET    /status               — Bus health
WebSocket /stream            — Real-time event stream
```

---

## Storage Architecture

### File Layout

```
.agent-bus/
├── events.db               # SQLite — event store + structured queries
├── vectors.db              # Vector store — embeddings for semantic search
├── subscriptions.json      # Active watches/subscriptions
├── sessions.json           # Active agent sessions
├── config.json             # Configuration
├── notifications/          # Per-agent notification files
│   ├── session-abc.jsonl
│   └── session-def.jsonl
├── archive/                # Archived old events
│   └── 2026-02.db
└── logs/                   # Bus operation logs
    └── bus.log
```

### SQLite Schema (events.db)

```sql
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    agent_type TEXT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL,
    tags TEXT,                    -- JSON array
    scope TEXT,                   -- JSON array of file paths/patterns
    references_json TEXT,         -- JSON object
    metadata_json TEXT,           -- JSON object
    ttl TEXT,                     -- ISO timestamp or NULL
    superseded_by TEXT,           -- event ID or NULL
    channel TEXT,
    embedding_id TEXT             -- FK to vectors.db
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(timestamp);
CREATE INDEX idx_events_agent ON events(agent_id);
CREATE INDEX idx_events_channel ON events(channel);
CREATE INDEX idx_events_superseded ON events(superseded_by);

-- Full-text search on content
CREATE VIRTUAL TABLE events_fts USING fts5(content, tags, scope);

CREATE TABLE sessions (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT,
    connected_at TEXT,
    last_heartbeat TEXT,
    working_scope TEXT,           -- JSON array
    status TEXT DEFAULT 'active'
);
```

---

## Configuration

### config.json

```json
{
  "version": "1.0",
  "project_name": "auto-detected from git or package.json",
  "storage": {
    "path": ".agent-bus",
    "max_events": 10000,
    "archive_after_days": 30,
    "ttl_cleanup_interval": "1h"
  },
  "embeddings": {
    "provider": "local",
    "model": "all-MiniLM-L6-v2",
    "fallback_provider": null,
    "dimensions": 384
  },
  "briefing": {
    "recent_window": "24h",
    "max_decisions": 10,
    "max_warnings": 10,
    "max_mutations": 20,
    "compact_max_tokens": 500
  },
  "conflicts": {
    "scope_overlap_detection": true,
    "stale_assumption_detection": true,
    "check_interval": "5m"
  },
  "sessions": {
    "heartbeat_interval": "2m",
    "stale_after": "10m",
    "auto_cleanup": true
  },
  "server": {
    "enabled": false,
    "port": 4242,
    "host": "127.0.0.1"
  }
}
```

---

## Non-Functional Requirements

### Performance
- Event posting: < 50ms
- Structured query: < 100ms for up to 10k events
- Semantic query: < 500ms (embedding generation + search)
- Briefing generation: < 1s
- Storage: < 100MB for 10k events with embeddings

### Reliability
- SQLite WAL mode for concurrent read/write safety
- Atomic event writes — no partial events
- Graceful handling of stale sessions (agent crashed without disconnect)
- No data loss on unexpected shutdown

### Compatibility
- Works with any AI agent that can run CLI commands or HTTP calls
- No dependency on specific AI provider APIs for core functionality
- Python 3.10+ (primary implementation)
- Optional: Node.js MCP server wrapper

---

## What This Is NOT

- **Not a task manager** — Use Task Master, Linear, Jira for task tracking
- **Not a git replacement** — Git handles code versioning; AgentBus handles agent coordination
- **Not a chat system** — Events are structured data, not conversation
- **Not a database** — It's a specialized event log with semantic search
- **Not cloud-dependent** — Runs entirely local; cloud sync is a future extension

---

## Open Questions

1. **Embedding model**: Should we bundle a model or require separate installation? Trade-off between ease of setup and package size.
2. **MCP vs CLI priority**: Build MCP server first (tighter agent integration) or CLI first (broader compatibility)?
3. **Event deduplication**: Should the bus detect and merge near-duplicate events from the same agent?
4. **Human interface**: Do we need a minimal TUI for humans to browse events, or is CLI + JSON output sufficient?
5. **Cross-project**: Should agents be able to query events from other projects? (e.g., shared libraries)
6. **Event size limits**: Should we cap content length? Agents might try to dump entire file contents.
7. **Auth model**: For multi-user environments, do we need agent identity verification?
8. **Garbage collection strategy**: Time-based archival vs. relevance-based retention?
