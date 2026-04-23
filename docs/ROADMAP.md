# Engram Roadmap

Comprehensive feature roadmap from the perspective of an AI agent that uses Engram daily. Prioritized by impact on real-world usefulness.

## Priority Legend

- **P0** — Critical. Without these, Engram's core value (briefings) degrades as usage grows.
- **P1** — High. Solves real scaling or data quality problems.
- **P2** — Medium. Valuable for multi-agent and long-term use cases.
- **P3** — Low. Nice-to-have, deferred until core is solid.

---

## Shipped

### v1.0 (2026-02-23)
- SQLite event store with WAL mode
- 5 event types: discovery, decision, warning, mutation, outcome
- FTS5 full-text search
- CLI: init, post, query, briefing, status
- MCP server: post_event, query, briefing, status
- Git bootstrap (cold-start from git history + README/CLAUDE.md)
- CLAUDE.md auto-write

### v1.1 (2026-02-23)
- Passive observation via Claude Code hooks (auto-capture file writes, bash outcomes)
- Event linking (related_ids field, schema v2)
- Smarter briefings: dedup, staleness detection, time-windowed summaries
- Garbage collection (archive old mutations/outcomes, preserve warnings/decisions)

### v1.2 (2026-02-24)
- Multi-turn AI consultation system (ConsultationEngine)
- Provider abstraction: OpenAI, Google GenAI, Anthropic via httpx
- Schema v3 (conversations + conversation_messages tables)
- CLI: consult start/say/show/ls/done/extract
- MCP: start_consultation, consult_say, consult_show, consult_done
- Markdown audit trail for all consultations

### v1.3 (2026-02-24)
- Event Lifecycle: resolve, supersede, reopen commands and status field (active/resolved/superseded)
- Event Priority: critical/high/normal/low with briefing sort order
- Scope-Aware Briefings: 4-section structure (Critical Warnings, Focus-Relevant, Other Active, Recently Resolved), relevance scoring (exact=3, parent=2, child=1)
- Schema v4 migration (status, priority, resolved_reason, superseded_by_event_id columns)
- Auto-context assembly for consultations (context.py)

### v1.4 (2026-02-24)
- Session Intent: declare agent focus and scope per session
- Session-event linking via session_id column on events table
- Auto-scoped briefings from active session scope
- Hook auto-registration of sessions (SessionStart hook)
- Single-session-per-agent with auto-end, stale cleanup (24h)
- Schema v5 migration (sessions table, session_id on events)
- Consult File: `--file` flag on CLI, `start_consultation_file` MCP tool, `/consult` slash command

### v1.5 (2026-02-25)
- Context Save/Restore Integration (#8): `engram checkpoint <file>` records checkpoint and enriches markdown
- CheckpointEngine: enriches markdown sections with matching Engram events via HTML comment markers
- Full Briefing mode: `engram briefing --full` combines latest checkpoint static context with dynamic activity
- Checkpoint data stored in meta table as JSON (no schema migration)
- Auto-checkpoint via PostToolUse hook on `.claude/context/*.md` writes
- MCP: `save_checkpoint` tool, `briefing` tool gains `full` parameter

### v1.6 (2026-02-25)
- Richer Mutation Capture (#5): PostToolUse hook now produces informative summaries instead of "Modified <path>" messages
- Edit tool: inline `'old' -> 'new'` format for short changes, compact unified diff for longer ones
- Write tool: `Created path (N lines): Sym1, Sym2, ...` with structural symbol extraction (class/def) for `.py/.js/.ts/.rs/.go`
- No schema migration — summaries fit inside the existing 2000-char content limit
- Design validated via consultation conv-b21aeabe959e (GPT-4o, Gemini Flash, Grok)

### v1.6.1 (2026-04-21)
- Maintenance release, no behaviour changes to briefings, queries, or consultations
- Consistent `agent_id="claude-code"` on all hook-captured events (previously `hook-{session_id[:8]}`)
- Atomic `.claude/settings.json` writes via tempfile + `os.replace` (`_write_json_atomic` helper)
- New CLI: `engram hooks uninstall` and `engram hooks show`
- Pinned `mcp>=1.0,<2.0` in optional deps
- Relative-timestamp test fixtures (`tests/conftest.py::ts_offset`) so the suite doesn't rot when the default briefing window shifts

---

## Planned

### P0 — In Progress (branch `v1.7-plugin`)

#### 17. Claude Code Plugin Packaging — v1.7.0

**Problem:** Getting Engram wired into a project currently takes three manual steps: `pip install engram[mcp]`, `engram hooks install`, and adding an MCP server entry to `.claude/settings.json`. Each is a friction point; users drop off.

**Solution:** Ship a Claude Code plugin bundle at `plugin/` that auto-wires the MCP server, hooks, and a set of user-invokable slash-command skills. One `/plugin install` replaces the three manual steps.

**Scope (MVP):**

1. **Plugin skeleton** (shipped in branch) — `.claude-plugin/plugin.json` manifest, `.mcp.json` registering `engram-mcp` with `ENGRAM_PROJECT_DIR=${PWD}`, `hooks/hooks.json` mirroring the CLI's `HOOK_CONFIG`.
2. **MVP skill set** — five skills, each a thin wrapper over the corresponding CLI command:
   - `/engram:briefing` — show the project briefing
   - `/engram:post-decision` — record a decision with rationale
   - `/engram:query` — search prior events
   - `/engram:checkpoint-save` — explicit context checkpoint
   - `/engram:checkpoint-restore` — load latest checkpoint via `briefing --full`
3. **Configurable auto-checkpoint dirs** — `ENGRAM_CONTEXT_DIRS` env var replaces the hard-coded `.claude/context/` path check so other save-context tools can trigger auto-enrichment.
4. **Version alignment** — `pyproject.toml`, `src/engram/__init__.py`, and `plugin/.claude-plugin/plugin.json` all carry `1.7.0`.

**Design decisions (recorded in Engram):**
- **v1.7.0, not v2.0** — CLI/MCP/hook APIs stay compatible. Purely additive packaging.
- **Monorepo** — plugin ships inside the Engram repo; one release cadence.
- **Dual-channel distribution** — `pip install engram` for the binary, Claude Code plugin for the wiring. Plugin shells out to the pip-installed `engram`/`engram-mcp` via PATH.
- **MCP + skills coexist** — no MCP deprecation in v1.7. Skills serve user-invoked workflows; MCP serves programmatic/autonomous use. Revisit after 3–6 months of real use.
- **Detect-and-skip existing CLI hooks** — users who ran `engram hooks install` before installing the plugin should not get duplicate events. Target behavior; exact mechanism depends on Claude Code's hook merge semantics (under test).
- **GitHub-first distribution** — ship the plugin via repo URL, defer marketplace submission until a real-world usage period surfaces bugs.

**Phase 2b — verification results (completed 2026-04-23, Claude Code 2.1.118):**

1. **`${PWD}` expansion in `.mcp.json` env vars** — ✓ VERIFIED. Expands to the user's CWD. Current `plugin/.mcp.json` is correct; no code change needed.
2. **Hook merge/dedup** — ✗ DOUBLE-FIRE. When plugin hooks and `.claude/settings.json` CLI hooks both register `Write|Edit`, both fire per edit. Engram's internal 5s debounce (hooks.py:261) prevents duplicate events in the DB, so no data corruption — but every tool use pays 2x hook-spawn latency. **Action for v1.7.0 release notes:** users who previously ran `engram hooks install` must run `engram hooks uninstall` before installing the plugin. Phase 4 should teach the CLI installer to detect plugin presence.
3. **Skills can pre-approve MCP tools** — ✓ VERIFIED. `allowed-tools: mcp__engram__<tool>` in SKILL.md frontmatter alone suppresses the permission prompt (no `permissions.allow` entry required). Plugin skills can use native MCP invocation. Current `plugin/skills/briefing/SKILL.md` still uses Bash shell-out; candidate for migration in Phase 4 or v1.8.
4. **Symlink survival across plugin cache copy** — ⚠ N/A for dev mode. `claude --plugin-dir` runs the plugin in-place and does not copy files into `~/.claude/plugins/cache/`. Symlink survival for production install (marketplace or `/plugin install`) remains untested; deferred beyond Phase 2b.

**Phase 2b — new findings (not in original four):**

5. **Onboarding gap: plugin does not auto-init.** A user installing the plugin and invoking `/engram:briefing` or `mcp__engram__status` gets "Engram not initialized" until they manually run `engram init`. Needs a decision before v1.7.0 release: (A) document manual init in plugin README/skill, (B) SessionStart hook auto-inits without git seeding, (C) SessionStart hook runs full `engram init`. Recorded as HIGH discovery in Engram.
6. **Ambient `engram-mcp` duplicate process observed.** Alongside the plugin's engram-mcp, a second engram-mcp spawns without CLAUDE_PLUGIN env vars. Non-blocking (non-hook context). Source untraced. Worth fixing for release polish so setup isn't confusing.

Full details and decisions in Engram (scope `plugin/`, 2026-04-23 discoveries) and in `docs/superpowers/specs/2026-04-23-phase-2b-plugin-verification-design.md`.

**Not in v1.7:**
- MCP deprecation
- Subscription to new hook events (PreCompact/PostCompact, TaskCreated, etc.) — deferred to v1.8+
- Per-subagent event capture
- Marketplace submission

---

### P1 — High

#### 4. Hierarchical Summarization
**Problem:** As events grow into thousands, briefings become too long for context windows. GC helps but loses information.

**Solution:** Periodic summarization that compresses old events:
- Daily summaries: compress a day's mutations/outcomes into a paragraph
- Weekly summaries: roll up daily summaries
- Project-level summary: maintained incrementally, captures the "story so far"

Summaries are stored as special events (new type: `summary`) with links to the events they compress. Briefings use summaries for older periods, raw events for recent activity. Could use the consultation system to generate summaries via external models, or keep it heuristic-based.

#### ~~5. Richer Mutation Capture~~ — Shipped in v1.6

#### 7. Conflict Detection
**Problem:** Two agents can modify the same file or make contradictory decisions without knowing. This is the "isolation" problem from Engram's README.

**Solution:** Check for conflicts on:
- File write: if another agent has a recent mutation on the same file, warn
- Decision post: if an existing active decision covers the same scope, surface it
- Conflict warnings are surfaced in briefings and optionally as hook output

Builds on session intent (#6, shipped in v1.4) to know what agents are currently active.

#### ~~8. Context Save/Restore Integration~~ — Shipped in v1.5

---

### P2 — Medium

#### 9. Outcome Tracking / Decision-Outcome Linking
**Problem:** Decisions are recorded but their outcomes aren't systematically linked. "We chose bcrypt" → later "bcrypt caused performance issues" should be a connected chain.

**Solution:** Formalize the decision→outcome pattern:
- When posting an outcome, prompt/require linking to the triggering decision via related_ids
- Briefings show decisions with their outcomes: "Decision: use bcrypt (outcome: 3 sessions ago, caused 200ms latency)"
- Surface decisions that have no recorded outcome (open loops)

The related_ids infrastructure exists — this is about conventions and briefing logic.

#### 10. Cross-Project Knowledge
**Problem:** Knowledge is siloed per project. If I learn "pytest-xdist breaks with SQLite in-memory DBs" in project A, I'll rediscover it in project B.

**Solution:** Global event store at `~/.engram/global.db`:
- New event type or tag: `transferable: true`
- `engram post -t discovery -c "..." --global` writes to global store
- Briefings optionally include relevant global events
- Global events are matched by scope patterns or keywords

Keep it optional — most events are project-specific, and that's correct.

#### 11. Multi-Agent Awareness
**Problem:** No visibility into what other agents are currently doing in the same project.

**Solution:** Build on session intent (#6):
- `engram who` shows active sessions (agent, focus, scope, started)
- Briefings include "Currently active: agent-X working on src/auth, agent-Y working on tests"
- Foundation for conflict detection (#7)

Uses sessions table from #6 (shipped in v1.4).

#### 12. Smarter Briefing Ranking
**Problem:** Events are listed chronologically within sections. More relevant events should surface higher.

**Solution:** Relevance scoring combining:
- Scope match to current focus (from session intent or --focus flag)
- Recency (exponential decay)
- Priority level
- Event type weight (warnings > decisions > discoveries > mutations)
- Link density (events with many related events are more significant)

This is an evolution of scope-aware briefings (#2) and priority (#3), both shipped in v1.3. All dependencies met.

---

### P3 — Low / Deferred

#### 13. Semantic Search with Embeddings
**Problem:** FTS5 keyword matching misses conceptually related results (searching "auth" doesn't find events about "login" or "JWT").

**Solution:** Optional embedding layer:
- Use a lightweight model (e.g., `all-MiniLM-L6-v2` via sentence-transformers)
- Store vectors in a separate `vectors.db` or use sqlite-vec extension
- Hybrid search: FTS5 for keyword hits + cosine similarity for semantic hits
- Only activate if `engram[semantic]` extra is installed

Deferred because FTS5 covers 95%+ of queries under 10k events, and the dependency cost (torch, sentence-transformers) contradicts the zero-dep philosophy. Revisit when projects regularly exceed 10k events.

#### 14. Subscription / Notification System
**Problem:** Agents have no way to be alerted when a relevant event is posted (e.g., a warning on a file they're editing).

**Solution:** Watch/subscribe mechanism:
- `engram watch --scope src/auth/ --types warning,decision`
- New events matching a watch are queued as notifications
- Agents poll via `engram notifications` or receive via MCP push
- File-based delivery (JSONL per subscriber) or MCP notification protocol

Deferred because it requires agents to have a polling loop or MCP push support, neither of which is standard today. Session intent (#6) and conflict detection (#7) solve the most urgent case (concurrent edits) without requiring subscriptions.

#### 15. PyPI Publishing
Package and publish to PyPI so users can `pip install engram` instead of cloning. Requires:
- Finalize package metadata
- Set up CI/CD (GitHub Actions)
- Publish to PyPI with `twine` or `flit`

#### 16. Auto-Update README/CHANGELOG
Auto-generate CHANGELOG.md entries from git commits and event history on version bumps. Low priority — manual updates are fine for now.

---

## Dependencies Between Features

```
✅ Session Intent (#6) ──► Multi-Agent Awareness (#11)
       │                         │
       ▼                         ▼
✅ Scope-Aware Briefings (#2) ◄── Conflict Detection (#7)
       │
       ▼
Smarter Briefing Ranking (#12) ◄── ✅ Event Priority (#3)
                                ◄── ✅ Event Lifecycle (#1)

✅ Context Save/Restore (#8)    ── shipped v1.5
Hierarchical Summarization (#4) ── standalone
Richer Mutation Capture (#5)    ── standalone
Outcome Tracking (#9)           ── standalone (uses existing related_ids)
Cross-Project Knowledge (#10)   ── standalone
Semantic Search (#13)           ── standalone
Subscriptions (#14)             ── depends on ✅ Session Intent (#6)
```

## Suggested Build Order

All dependencies are now shipped (✅ #1, #2, #3, #5, #6, #8). Remaining features can be built in any order based on impact:

1. **Claude Code Plugin Packaging** (#17) — in progress, biggest UX improvement available
2. **Conflict Detection** (#7) — all deps shipped (#6), solves multi-agent isolation
3. **Hierarchical Summarization** (#4) — standalone, needed when event count grows
4. **Outcome Tracking** (#9) — convention + briefing logic, no schema change
5. **Multi-Agent Awareness** (#11) — all deps shipped (#6)
6. **Smarter Briefing Ranking** (#12) — all deps shipped (#1, #2, #3, #6)
7. **Cross-Project Knowledge** (#10) — standalone but lower urgency
8-11. P3 items as needed
