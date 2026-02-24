# Changelog

## v1.4.0 — 2026-02-24

### Added

- **Session Intent** — Agents can declare what they're working on via `engram session start --focus "..." --scope src/path/`. Sessions enable auto-scoped briefings, event tagging, and multi-agent visibility. Single-session-per-agent with auto-end of previous.
- **Session CLI** — `engram session start/end/ls/show` commands for managing agent sessions.
- **Session MCP tools** — `session_start`, `session_end`, `list_sessions` exposed via MCP server.
- **Event-session linking** — Events automatically tagged with `session_id` of the active session. MCP `post_event` auto-links to active session. Hooks auto-tag mutations and outcomes.
- **Active Sessions in briefings** — Briefings now show an "Active Sessions" section listing all currently active agent sessions.
- **Auto-focus from session** — Briefings auto-scope to the active session's scope when `--focus` is not explicitly provided.
- **Stale session cleanup** — Sessions older than 24h are auto-ended during session commands and briefing generation.
- **Hook auto-registration** — SessionStart hook automatically registers a new session, ending any previous one.

### Changed

- Schema v4→v5 migration: adds `sessions` table, `session_id` column on events, and session indexes. Auto-migrates on first connection.
- `post_event` MCP tool now accepts optional `session_id` parameter.
- Briefing output now includes active sessions between header and critical warnings.

### Stats

- 229 tests across 13 test modules
- 14 source modules

---

## v1.3.0 — 2026-02-24

### Added

- **Event lifecycle management** — Events now have a `status` field (active/resolved/superseded). New CLI commands: `engram resolve <id> --reason "..."`, `engram supersede <id> --by <new-id>`, `engram reopen <id>`. Resolved events move out of active briefing sections into a dedicated "Recently Resolved" section.
- **Event priority** — Events can be posted with `--priority` (critical/high/normal/low). Priority affects briefing sort order within sections. Critical and high priority events display `[CRITICAL]` or `[HIGH]` tags in compact output.
- **Scope-aware briefings** — `engram briefing --focus src/auth` partitions events into focus-relevant (matching the path) and other active. Scope relevance scoring: exact match > parent directory > child path. Critical warnings always appear regardless of focus.
- **4-section briefing structure** — Briefings restructured from flat type-grouped sections into ranked sections: Critical Warnings, Focus-Relevant (when --focus used), Other Active, Recently Resolved (within --resolved-window, default 48h).
- **Auto-context for consultations** — `consult start` now assembles project context (README, warnings, decisions, discoveries, source modules) into consultation system prompts automatically. Toggle with `--context/--no-context`.
- **Thinking model support** — Added o3 (OpenAI), claude-opus (Anthropic), and gemini-pro (Google) as thinking-enabled consultation models with provider-specific API handling.

### Changed

- Schema v3→v4 migration: adds `status`, `priority`, `resolved_reason`, `superseded_by_event_id` columns and `idx_events_status` index. Auto-migrates on first connection.
- `recent_by_type()` now filters by status (default: "active"), so resolved/superseded events no longer appear in active queries.
- Briefing compact output now shows priority tags, resolved reasons, and staleness markers inline.

### Stats

- 207 tests across 12 test modules
- 14 source modules

---

## v1.2.0 — 2026-02-23

### Added

- **Multi-turn AI consultation system** — `engram consult start "topic" --models gpt-4o,gemini-flash` opens a multi-model conversation. Models respond in parallel, host can send follow-up messages. Conversations persist in SQLite.
- **Consultation providers** — Support for OpenAI, Google GenAI, Anthropic, and xAI (Grok) via OpenAI-compatible API. Model registry with per-model configuration.
- **Consultation MCP tools** — `consult_start`, `consult_message`, `consult_end`, `consult_list` exposed via MCP server.
- **Consultation transcripts** — Conversations saved as markdown in `docs/consultations/`.

---

## v1.1.0 — 2026-02-23

### Added

- **Passive observation via Claude Code hooks** — Automatic capture of file mutations (Write/Edit tools) and bash command outcomes, plus session-start briefing injection. Install with `engram hooks install`. Debounce prevents duplicate events for rapid edits to the same file.
- **Event linking** — Events can reference related events via `related_ids`. Post an outcome linked to the decision it validates, or chain discoveries together. Query linked events with `--related-to` (CLI) or `related_to` (MCP/API).
- **Smarter briefings** — Mutation deduplication collapses rapid edits to the same file within 30-minute windows. Staleness detection flags warnings and decisions whose scoped files were modified after the event was posted.
- **Garbage collection** — `engram gc` archives old mutations and outcomes to `.engram/archive/YYYY-MM.db`. Warnings and decisions are always preserved regardless of age. Supports `--dry-run` and configurable `--max-age` (default 90 days).
- **CLAUDE.md auto-write** — `engram init` now creates or appends to CLAUDE.md with agent instructions automatically, instead of printing a snippet to copy.
- **Schema migration** — Automatic v1→v2 migration on first connection. Adds `related_ids` column to existing databases without data loss.

### Fixed

- `query_structured` now applies `related_to` filter in SQL when combined with other filters (previously silently dropped it)
- `query_related` uses exact JSON element matching to prevent substring false-matches (e.g., `evt-abc` no longer matches `evt-abc123`)

### Stats

- 127 tests across 10 test modules
- 11 source modules, ~1,800 lines

---

## v1.0.0 — 2026-02-23

### Added

- **Event store** — SQLite with WAL mode and FTS5 full-text search. Five event types: discovery, decision, warning, mutation, outcome.
- **CLI** — `engram init`, `post`, `query`, `briefing`, `status` commands via Click.
- **MCP server** — FastMCP server exposing `post_event`, `query`, `briefing`, `status` tools for Claude Code integration.
- **Git bootstrap** — `engram init` mines git history to seed the event store, solving the cold-start problem.
- **Briefing generator** — Time-windowed summaries grouped by event type, with compact and JSON output formats.
- **Full-text search** — FTS5 with auto-indexing triggers. Supports combined text + structured filters (type, agent, scope, since).

### Design decisions

- FTS5 only, no embeddings — sufficient for <10k events with zero dependencies
- 5 event types (reduced from 9 in original spec)
- Content capped at 2000 chars
- Single runtime dependency (click); MCP support optional
- Zero-config, local-first — no cloud, no servers
