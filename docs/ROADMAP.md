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

---

## Planned

### P1 — High

#### 4. Hierarchical Summarization
**Problem:** As events grow into thousands, briefings become too long for context windows. GC helps but loses information.

**Solution:** Periodic summarization that compresses old events:
- Daily summaries: compress a day's mutations/outcomes into a paragraph
- Weekly summaries: roll up daily summaries
- Project-level summary: maintained incrementally, captures the "story so far"

Summaries are stored as special events (new type: `summary`) with links to the events they compress. Briefings use summaries for older periods, raw events for recent activity. Could use the consultation system to generate summaries via external models, or keep it heuristic-based.

#### 5. Richer Mutation Capture
**Problem:** Hooks log "wrote auth.py" but not what changed. "Modified auth.py" is far less useful than "added JWT validation, changed token expiry from 1h to 24h."

**Solution:** Enhance the PostToolUse hook to:
- Capture the `tool_input` diff when available (Write tool includes content)
- For Edit tool, capture old_string → new_string summary
- Auto-generate a one-line description of the change
- Store the diff summary in the event content, file path in scope

Keep the 2000-char limit — this is a summary, not a full diff.

#### 7. Conflict Detection
**Problem:** Two agents can modify the same file or make contradictory decisions without knowing. This is the "isolation" problem from Engram's README.

**Solution:** Check for conflicts on:
- File write: if another agent has a recent mutation on the same file, warn
- Decision post: if an existing active decision covers the same scope, surface it
- Conflict warnings are surfaced in briefings and optionally as hook output

Builds on session intent (#6, shipped in v1.4) to know what agents are currently active.

#### 8. Context Save/Restore Integration
**Problem:** Context save/restore tools (e.g., Claude Code's `/tools:context-save` and `/tools:context-restore`) write static markdown snapshots to `.claude/context/`. Meanwhile, Engram already accumulates rich, structured, searchable context throughout every session — but the two systems are completely disconnected. Agents manually duplicate work that Engram already does.

**Solution:** Integrate Engram as the primary backend for context save/restore:
- **Context Save** (`engram checkpoint`): Post a `checkpoint` event (new type) summarizing session work, key decisions, current state, and next steps. Optionally still write a markdown file for offline/non-MCP access. The checkpoint event links to the session's decisions, warnings, and discoveries via `related_ids`.
- **Context Restore** (`engram briefing` as primary): Restore calls `engram briefing` first for structured project state. Falls back to markdown files only if Engram isn't available.
- **CLI**: `engram checkpoint --summary "Shipped v1.2, planned P0 features" --next "Implement event lifecycle"`
- **MCP**: `save_checkpoint` tool, and `briefing` already serves as restore

This closes the loop — agents that use Engram don't need a separate context persistence mechanism. The briefing *is* the restored context.

Standalone — no dependencies on other features, though benefits from session intent (#6) for auto-populating checkpoint scope.

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

Context Save/Restore (#8)       ── standalone (benefits from ✅ #6)
Hierarchical Summarization (#4) ── standalone
Richer Mutation Capture (#5)    ── standalone
Outcome Tracking (#9)           ── standalone (uses existing related_ids)
Cross-Project Knowledge (#10)   ── standalone
Semantic Search (#13)           ── standalone
Subscriptions (#14)             ── depends on ✅ Session Intent (#6)
```

## Suggested Build Order

All dependencies are now shipped (✅ #1, #2, #3, #6). Remaining features can be built in any order based on impact:

1. **Richer Mutation Capture** (#5) — standalone, improves data quality at the source
2. **Context Save/Restore** (#8) — standalone, closes the context persistence gap
3. **Conflict Detection** (#7) — all deps shipped (#6), solves multi-agent isolation
4. **Hierarchical Summarization** (#4) — standalone, needed when event count grows
5. **Outcome Tracking** (#9) — convention + briefing logic, no schema change
6. **Multi-Agent Awareness** (#11) — all deps shipped (#6)
7. **Smarter Briefing Ranking** (#12) — all deps shipped (#1, #2, #3, #6)
8. **Cross-Project Knowledge** (#10) — standalone but lower urgency
9-12. P3 items as needed
