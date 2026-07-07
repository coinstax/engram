# Changelog

## v1.8.0 — 2026-07-07

Consultation models are refreshed to current frontier flagships and the curated set is now extensible per project, so it never goes fully stale. Fixes a latent break: the Anthropic provider still requested extended thinking with `budget_tokens`, which current Claude models reject with a 400 — every Claude consult would have failed once the model IDs advanced.

### Added
- **Per-project model overrides** — `.engram/models.json` (`{"models": {"<key>": {"provider", "model_id", "env_key", "base_url"?, "thinking"?, "reasoning_effort"?}}}`) adds new models or overrides builtins by key. Best-effort loading: a missing/malformed file or a bad entry is skipped, never fatal (mirrors `areas.json`). `providers.resolve_models()` merges builtins with overrides (overrides win) and threads through `ConsultationEngine` for both validation and dispatch.
- **Model discovery** — `engram consult models` (CLI, `--format compact|json`) and `list_models` (MCP tool) list every available model key, its provider/model ID, whether its API key is present in the environment, and whether it's a builtin or a project custom. Closes the gap where a user had to read source to learn the valid `--models` keys.
- **Actionable missing-SDK errors** — the provider SDKs (`openai`, `google-genai`, `httpx`) are optional extras; when one is absent a consult now fails with `pip install "engram[consult]"` guidance instead of a bare `ModuleNotFoundError`. README documents the `[consult]` / `[all]` extras and adds a provider table mapping each model key to its env var, API-key signup page, and SDK.

### Changed
- **Refreshed default models to current frontier flagships** (verified mid-2026), with version-agnostic keys so future ID bumps never rename a key: `gpt` → `gpt-5.5`, `claude-opus` → `claude-opus-4-8`, `claude-sonnet` → `claude-sonnet-5`, `gemini-pro` → `gemini-3.1-pro-preview`, `gemini-flash` → `gemini-3.5-flash`, `grok` → `grok-4.3`. The old `gpt-4o` and `o3` keys are retained as deprecated aliases (→ `gpt-5.5`) so stored conversations and existing muscle memory keep resolving.
- **Gemini thinking** — dropped the explicit `thinking_budget` on the Google path; Gemini 3.x reasons by default and the budget/level parameter shape changed across SDK versions. Thinking models still get the longer request timeout.

### Fixed
- **Anthropic thinking uses adaptive mode** — `_send_anthropic` now sends `thinking: {"type": "adaptive"}` instead of `{"type": "enabled", "budget_tokens": 10000}`. `budget_tokens` is removed on Opus 4.8 / Sonnet 5 and returns a 400; adaptive is the only on-mode and lets the model pace its own depth. Without this fix, refreshing the Claude model IDs alone would have broken every Claude consultation.
- **Discovery reflects `.env`** — `model_summary` now loads the project `.env` before checking key presence, so `engram consult models` / `list_models` report a key as present when it lives in `.env` (which the consult path itself loads via dotenv). Previously it checked only the raw process environment and showed false `no-key` for `.env`-based setups.

### Stats
- 338 tests passing (+14); schema unchanged at v6
- Version bumped to `1.8.0` across `pyproject.toml`, `src/engram/__init__.py`, `plugin/.claude-plugin/plugin.json`

## v1.7.0 — 2026-07-06

Engram ships as a Claude Code plugin bundle at `plugin/`. One `/plugin install` replaces the previous three-step setup (`pip install`, `engram hooks install`, manual MCP config). The Python CLI and `engram-mcp` binary remain first-class — the plugin shells out to them, keeping a single release surface for headless/automation use. This release also closes lifecycle gaps in the MCP surface and adds an `area` tag for grouping events by concept.

### Added
- `plugin/.claude-plugin/plugin.json` — plugin manifest
- `plugin/.mcp.json` — registers `engram-mcp` with `ENGRAM_PROJECT_DIR=${PWD}`
- `plugin/hooks/hooks.json` — PostToolUse (Write/Edit/Bash) + SessionStart, mirroring CLI `HOOK_CONFIG`
- `plugin/skills/briefing/SKILL.md` — `/engram:briefing` proof-of-bundling skill
- `.gitignore` exception for `plugin/.mcp.json`
- **Plugin auto-init on SessionStart** — when the Engram Claude Code plugin is installed into a project that has not yet been initialized, the SessionStart hook now runs the equivalent of `engram init` automatically (creating `.engram/`, seeding from git history, setting project meta) so `/engram:briefing` and the MCP tools work on first launch. CLAUDE.md is intentionally not modified from the plugin path — agent guidance is already delivered via the FastMCP `instructions` field and plugin SKILL.md frontmatter.
- `src/engram/init.py` — shared `perform_init()` helper extracted from the `engram init` CLI; used by both the CLI command and the SessionStart hook.
- **MCP event-lifecycle tools** — `resolve_event`, `supersede_event`, and `reopen_event` are now exposed over MCP, mirroring the existing `engram resolve` / `supersede` / `reopen` CLI commands. Previously agents using the MCP server could only append events, so a superseded decision or fixed warning kept surfacing in briefings as if live. The underlying store/status logic already existed (`Event.status`, `Event.superseded_by`, `store.update_status`); this wires it to the MCP surface. Same validation as the CLI (only active events resolve/supersede; superseded events cannot reopen).
- **Expanded MCP `instructions`** — the FastMCP server description now tells agents to use `query` for targeted recall instead of scrolling the whole briefing, and to keep event status current via the lifecycle tools. Addresses discoverability feedback that `query` and the lifecycle ops were going unused.
- **Event `area` tag (schema v6)** — events now carry an optional single-string `area`/component tag (e.g. `billing`, `email-change`) that is independent of `scope` (file paths). Set it explicitly (`engram post -A billing`, or `area=` on the MCP `post_event` tool) or let it default from an optional `.engram/areas.json` path→area prefix map. `query --area` / MCP `query(area=...)` filter by it, FTS indexes it, and briefing `focus` now matches an area name as well as file paths. Schema v6 auto-migrates: it adds the column, rebuilds the FTS index, and backfills existing events from the map where a rule matches — `scope` is never modified.

### Fixed
- **MCP `post_event` no longer silently truncates** — content over 2000 chars now raises a clear `ValueError` (with the actual length and guidance to summarize or split into linked events) instead of quietly slicing to `content[:2000]` and persisting a truncated record. Matches the CLI's DB-level `CHECK(length(content) <= 2000)` which fails loudly.

### Stats
- 324 tests passing; schema at v6 (auto-migration from any prior version)
- Version bumped to `1.7.0` across `pyproject.toml`, `src/engram/__init__.py`, `plugin/.claude-plugin/plugin.json`

### Next after v1.7.0
- Remaining MVP skills: `/engram:post-decision`, `/engram:query`, `/engram:checkpoint-save`, `/engram:checkpoint-restore` (plugin currently ships `/engram:briefing`)
- `ENGRAM_CONTEXT_DIRS` env var to make auto-checkpoint dirs configurable
- Live `claude --plugin-dir` smoke test and resolution of the open design items flagged in the project's Engram store
- MCP server deprecation; subscription to new hook events (PreCompact/PostCompact, TaskCreated, etc.); per-subagent event capture; plugin marketplace submission

---

## v1.6.1 — 2026-04-21

Maintenance release: hook/packaging hygiene ahead of v2.0 plugin work. No behaviour changes to briefing, query, or consultation.

### Fixed

- **Consistent `agent_id` for hook-captured events** (`src/engram/hooks.py`) — `PostToolUse` handlers now tag mutation/outcome events with `agent_id="claude-code"`, matching the session registered by `SessionStart`. Previously events were tagged `hook-{session_id[:8]}`, which fragmented event history when queried by agent. The `session_id` field still disambiguates individual runs.
- **Atomic `.claude/settings.json` writes** — `install_hooks` / `uninstall_hooks` now write via tempfile + `os.replace` so a crash mid-write can no longer corrupt the settings file. Shared `_write_json_atomic()` helper.
- **`mcp` optional dependency upper bound** (`pyproject.toml`) — pinned to `mcp>=1.0,<2.0` in both `mcp` and `all` extras. Prevents silent breakage when MCP ships a 2.x major release.
- **Test-fixture time rot** — `conftest.py` now exposes a `ts_offset(minutes)` helper anchored to "now minus 3 hours". Fixtures in `test_briefing.py`, `test_context.py`, `test_mcp_server.py`, and `test_store.py` switched from hardcoded `2026-02-23T...` timestamps to relative ones so the default 7-day briefing window no longer bit-rots the suite.

### Added

- **`engram hooks uninstall`** — removes Engram's hook entries from `.claude/settings.json`, preserves other hooks and settings, and drops empty event keys / an empty top-level `hooks` block if Engram was the only occupant.
- **`engram hooks show`** — reports which of Engram's expected hook events (`PostToolUse`, `SessionStart`) are currently wired up in `.claude/settings.json`, plus the settings file path.

### Stats

- 285 tests across 14 test modules (7 new: uninstall + show coverage)
- 15 source modules

---

## v1.6.0 — 2026-02-25

### Added

- **Richer Mutation Capture (#5)** — PostToolUse hook now generates informative summaries instead of bare "Modified filepath" messages:
  - **Edit tool**: Extracts `old_string`/`new_string` from tool input. Short changes (≤3 lines per side) produce inline format: `Edited src/auth.py: 'return False' -> 'return True'`. Longer changes produce compact unified diffs with `@@` hunk markers.
  - **Write tool**: Generates `Created path (N lines): Foo, bar` or `Wrote path (N lines): Foo, bar` with structural symbol extraction (class/function names) via lightweight regex.
  - **Language support**: Symbol extraction for `.py`, `.js`, `.ts`, `.rs`, `.go` files. Unknown extensions gracefully fall back to line count only.
  - **Truncation**: Content exceeding 2000 chars is truncated with a visible `[truncated]` marker.
  - **Graceful degradation**: Missing `old_string`/`new_string` or `content` fields handled without errors.
- **`_extract_symbols()` utility** — Regex-based top-level symbol extraction (classes, functions, structs, enums, interfaces) scanning first 100 lines of file content.

### Changed

- `_handle_file_mutation` in hooks.py now dispatches to `_summarize_edit` or `_summarize_write` based on tool name, instead of generating a generic "Modified" message.
- ROADMAP.md updated: Context Save/Restore (#8) moved to Shipped section (v1.5).

### Stats

- 278 tests across 14 test modules (15 new: 6 for symbol extraction, 9 for mutation capture)
- 15 source modules

---

## v1.5.0 — 2026-02-25

### Added

- **Context Save/Restore Integration** — `engram checkpoint <file>` records a context checkpoint and enriches the markdown file with recent Engram events (decisions, warnings, discoveries) that aren't already present. Uses HTML comment markers (`<!-- engram:start -->` / `<!-- engram:end -->`) for injected content that's invisible in rendered markdown and replaceable on re-enrichment.
- **Full briefing mode** — `engram briefing --full` combines the latest checkpoint's static context file with dynamic recent activity since the checkpoint. One command gives you the complete project picture.
- **Checkpoint MCP tool** — `save_checkpoint` exposed via MCP server. Auto-links to active session. `briefing` tool gains `full` parameter.
- **Checkpoint data model** — `Checkpoint` dataclass in models.py. Checkpoints stored in the meta table as JSON (no schema migration needed).
- **Consult File feature** — `engram consult start --file <path>` includes file contents in consultation messages. `start_consultation_file` MCP tool. `/consult` slash command for quick consultations.

### Stats

- 260 tests across 14 test modules
- 15 source modules

---

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
