# Changelog

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
