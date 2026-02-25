# Consultation: Review: ROADMAP.md
- ID: conv-98ac3a859aba
- Models: gemini-flash, gpt-4o
- Status: active
- Started: 2026-02-25T22:14:26.578253+00:00
- Updated: 2026-02-25T22:14:26.582429+00:00

## System Prompt
You are a technical reviewer consulting on the engram project. The host agent (Claude Code) is directing this conversation. Other models in this consultation: gemini-flash, gpt-4o. Be concise and specific. Disagree when you see issues.

---

# Project: engram
Total events in memory: 29

## Consultation Topic
Review: ROADMAP.md

## Project Overview (from README)
# Engram

**Project memory for AI coding agents.**
[...truncated]

## Source Modules
__init__.py, bootstrap.py, briefing.py, cli.py, consult.py, context.py, formatting.py, gc.py, hooks.py, mcp_server.py, models.py, providers.py, query.py, store.py

## Active Warnings (2)
[2026-02-24 18:33] [warning] [claude-code] pyproject.toml +1 more — Version numbers in pyproject.toml and src/engram/__init__.py were stuck at 1.2.0 while v1.3 features were shipped. Both must be updated together when releasing. Fixed to 1.3.0.
[2026-02-23 21:35] [warning] [cli] scripts/consult_agents.py — Don't commit API keys — they were passed via CLI args in session 1

## Recent Decisions (15)
[2026-02-25 21:56] [decision] [HIGH] [claude-code] src/engram/consult.py +3 more — Consult File feature shipped: CLI --file/-f option on `consult start`, MCP `start_consultation_file` tool with auto-context, and /consult slash command. File content goes into initial_message (not system_prompt). Default topic derived from filename. --message becomes custom prompt when combined with --file. MAX_FILE_CHARS=60k. 238 tests passing.
[2026-02-24 17:54] [decision] [HIGH] [cli] — Engram v1.3 P0 features shipped: event lifecycle (resolve/supersede/reopen), event priority (critical/high/normal/low), scope-aware briefings (--focus with relevance scoring), 4-section briefing structure. Schema v4 migration. 207 tests passing. README and CHANGELOG updated.
[2026-02-24 19:18] [decision] [claude-code] src/engram/ — Engram v1.4 shipped: Session Intent (#6). Schema v5 with sessions table and session_id on events. CLI session start/end/ls/show. MCP session_start/session_end/list_sessions. Hooks auto-register sessions and auto-tag events. Briefings show active sessions and auto-focus from session scope. 229 tests passing across 13 modules. Consultation conv-63e0f33c4097 validated design with GPT-4o, Gemini Flash, Grok.
[2026-02-24 18:53] [decision] [claude-code] docs/SESSION_INTENT_SPEC.md — Session Intent (#6) spec finalized via consultation conv-63e0f33c4097 (GPT-4o, Gemini Flash, Grok). Key decisions: (1) Add session_id column to events table — direct linkage for session summaries and conflict detection. (2) No update_session — end+start pattern sufficient. (3) Stale cleanup on session commands, not just briefing. (4) No scope validation — consistent with events. (5) Auto-tag events with session_id via hooks. (6) Single-session-per-agent for v1. Spec at docs/SESSION_INTENT_SPEC.md.
[2026-02-24 18:33] [decision] [claude-code] CLAUDE.md — Rewrote CLAUDE.md following best practices research. Key changes: (1) Added project overview, common commands, code conventions, architecture notes, known gotchas — all things Claude can't infer from code alone. (2) Condensed Engram usage from 24 lines to 9 focused lines. (3) Documented lazy-import pattern and consult.py naming gotcha. Per best practices: keep it concise, focus on what Claude can't infer, treat it like code.
[2026-02-24 18:28] [decision] [claude-code] src/engram/mcp_server.py +2 more — Updated all 3 CLAUDE.md locations (README suggested block, cli.py CLAUDE_MD_SNIPPET, live /home/cdm/CLAUDE.md) to cover v1.3 features: event lifecycle (resolve/supersede/reopen), event priority, scope-aware briefings, and consultation tools. Also fixed MCP post_event missing priority parameter. README MCP tool count corrected from "four" to "eight".
[2026-02-24 17:08] [decision] [cli] — Model selection for consultations: gpt-4o good for general review, gemini-flash for schema/technical detail (caught related_ids question), grok for edge cases and operational concerns (caught audit trail, 48h window, scope rigidity). For architecture reviews, all 3 complement well. For pure code review, a single strong model may suffice.

## Recent Discoveries (5)
[2026-02-25 21:56] [discovery] [claude-code] src/engram/mcp_server.py +1 more — MCP serve
[...truncated]

---

## Turn 1

**host** (2026-02-25T22:14:26.580266+00:00):
Review this file and provide feedback. Note any issues, suggest improvements, and highlight what works well.

**File: `ROADMAP.md`**

```md
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

---

## Planned

### P0 — Critical

#### 1. Event Lifecycle (resolve/supersede)
**Problem:** Warnings and decisions live forever or get GC'd — no middle ground. A resolved warning keeps polluting briefings. A reversed decision misleads future agents.

**Solution:** Add `status` field to events: `active` (default), `resolved`, `superseded`. New commands:
- `engram resolve <event-id> --reason "fixed in PR #42"`
- `engram supersede <event-id> --by <new-event-id>`

Briefings should only surface `active` events by default, but resolved/superseded events remain queryable for history. Schema v4 migration adds `status` and `resolved_by` columns.

#### 2. Scope-Aware Briefings
**Problem:** The briefing is a chronological dump by type. If I'm about to work on `src/auth/`, I need auth-related warnings and decisions surfaced first, not buried in a list of unrelated mutations.

**Solution:** Enhance `engram briefing --focus <path>` to:
- Rank events by relevance to the focus path (exact scope match > parent dir > unscoped)
- Show a "Relevant to your focus" section at the top
- Still include global warnings (they apply everywhere)
- Weight recent events higher than old ones

The MCP `briefing` tool already accepts `scope` but only filters — it should rank and prioritize instead.

#### 3. Event Priority
**Problem:** A critical warning about data loss and a minor naming convention discovery get equal treatment in briefings.

**Solution:** Add optional `priority` field: `critical`, `high`, `normal` (default), `low`. Briefings sort by priority within each section. Critical warnings always appear first regardless of age. Schema migration adds `priority` column with default `normal`.

---

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

#### 6. Session Intent
**Problem:** No way to declare "I'm working on X this session." Briefings, future notifications, and conflict detection would all benefit from knowing what the current agent is focused on.

**Solution:** Add session registration:
- `engram session start --focus "refactoring auth module" --scope src/auth/`
- `engram session end`
- Stored in a `sessions` table (id, agent_id, focus, scope, started_at, ended_at)
- Briefings auto-detect scope from active session if `--focus` not provided
- Foundation for multi-agent awareness (P2) and conflict detection (P2)

The SessionStart hook could auto-register sessions.

#### 7. Conflict Detection
**Problem:** Two agents can modify the same file or make contradictory decisions without knowing. This is the "isolation" problem from Engram's README.

**Solution:** Check for conflicts on:
- File write: if another agent has a recent mutation on the same file, warn
- Decision post: if an existing active decision covers the same scope, surface it
- Conflict warnings are surfaced in briefings and optionally as hook output

Depends on session intent (#6) to know what agents are currently active.

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

Requires sessions table from #6.

#### 12. Smarter Briefing Ranking
**Problem:** Events are listed chronologically within sections. More relevant events should surface higher.

**Solution:** Relevance scoring combining:
- Scope match to current focus (from session intent or --focus flag)
- Recency (exponential decay)
- Priority level
- Event type weight (warnings > decisions > discoveries > mutations)
- Link density (events with many related events are more significant)

This is an evolution of scope-aware briefings (#2) and priority (#3) — becomes possible once those land.

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
Session Intent (#6) ──► Multi-Agent Awareness (#11)
       │                         │
       ▼                         ▼
Scope-Aware Briefings (#2) ◄── Conflict Detection (#7)
       │
       ▼
Smarter Briefing Ranking (#12) ◄── Event Priority (#3)
                                ◄── Event Lifecycle (#1)

Context Save/Restore (#8)       ── standalone (benefits from #6)
Hierarchical Summarization (#4) ── standalone
Richer Mutation Capture (#5)    ── standalone
Outcome Tracking (#9)           ── standalone (uses existing related_ids)
Cross-Project Knowledge (#10)   ── standalone
Semantic Search (#13)           ── standalone
Subscriptions (#14)             ── depends on Session Intent (#6)
```

## Suggested Build Order

Based on dependencies and impact:

1. **Event Lifecycle** (#1) — standalone, immediately improves briefing quality
2. **Event Priority** (#3) — standalone, small schema change, big briefing improvement
3. **Scope-Aware Briefings** (#2) — builds on #1 and #3
4. **Context Save/Restore** (#8) — standalone, closes the context persistence gap
5. **Session Intent** (#6) — enables #7, #11, #12
6. **Richer Mutation Capture** (#5) — standalone, improves data quality at the source
7. **Hierarchical Summarization** (#4) — standalone, needed when event count grows
8. **Conflict Detection** (#7) — builds on #6
9. **Outcome Tracking** (#9) — convention + briefing logic, no schema change
10. **Cross-Project Knowledge** (#10) — standalone but lower urgency
11. **Multi-Agent Awareness** (#11) — builds on #6
12. **Smarter Briefing Ranking** (#12) — builds on #1, #2, #3, #6
13-16. P3 items as needed

```

**gemini-flash** (2026-02-25T22:14:26.582429+00:00):
This `ROADMAP.md` is exceptionally well-structured, clear, and comprehensive. The problem-solution format, clear priority legend, and explicit dependency graph are excellent.

However, the primary issue is that **the roadmap is significantly outdated relative to the project's recent progress.**

---

### **Critical Issue**

1.  **Outdated "Planned" Section**: Several items listed as "Planned" have already been shipped in v1.3 and v1.4, as indicated by the "Recent Decisions" in the project overview:
    *   **P0 — Critical**:
        *   **1. Event Lifecycle (resolve/supersede)**: **SHIPPED** in v1.3 (2026-02-24).
        *   **2. Scope-Aware Briefings**: **SHIPPED** in v1.3 (2026-02-24).
        *   **3. Event Priority**: **SHIPPED** in v1.3 (2026-02-24).
    *   **P1 — High**:
        *   **6. Session Intent**: **SHIPPED** in v1.4 (2026-02-24).

    **Action Needed**: Update the "Shipped" section to include v1.3 and v1.4, and move these items out of "Planned." This is crucial for the roadmap to be an accurate guide.

---

### **Strengths**

1.  **Clarity and Structure**: The roadmap is very easy to read and understand. The `Problem:` and `Solution:` format for planned features is excellent, framing the value proposition clearly.
2.  **AI-Centric Perspective**: Maintaining the perspective of an "AI agent that uses Engram daily" consistently throughout the problem descriptions is highly effective and aligns perfectly with the project's goals.
3.  **Detailed Solutions**: Solutions are well-articulated, often including specific commands, schema changes, and logic enhancements.
4.  **Priority Legend**: The priority definitions (P0-P3) are clear and directly tied to impact on "real-world usefulness" for an AI agent.
5.  **Dependency Mapping**: The "Dependencies Between Features" section is invaluable for understanding relationships and planning, and the "Suggested Build Order" is a logical extension of this.
6.  **Thoughtful Deferrals (P3)**: The reasoning for deferring P3 items (e.g., semantic search due to FTS5 coverage and dependency cost) demonstrates practical decision-making.

---

### **Suggested Improvements (for remaining "Planned" items)**

1.  **Hierarchical Summarization (#4)**:
    *   **Clarification**: The solution mentions "Briefings use summaries for older periods, raw events for recent activity." This is good, but consider adding a brief note on *how* an agent would choose to dive into the raw events if the summary isn't sufficient (e.g., `engram query --summary-id <summary-event-id> --expand`).
2.  **Context Save/Restore Integration (#8)**:
    *   This is a very strong P1 feature. The integration of Engram as the "primary backend for context save/restore" is a powerful and logical step. The proposal for `engram checkpoint` and `engram briefing` as the restore mechanism is solid.
3.  **Cross-Project Knowledge (#10)**:
    *   **Refinement**: For global events, consider how conflicts might be handled if two projects define conflicting global discoveries (e.g., different best practices for a common library). This might be out of scope for now, but a quick thought on "conflict resolution for global knowledge" could be useful later.
4.  **PyPI Publishing (#15)**:
    *   While P3, this is foundational for adoption. Consider moving it to P2 if the project aims for external consumption soon.

---

### **Conclusion**

This is an excellent roadmap document at its core. Addressing the outdated "Shipped" and "Planned" sections is the immediate and most critical action. Once updated, it will continue to serve as a strong guide for Engram's evolution.

**gpt-4o** (2026-02-25T22:14:26.582429+00:00):
**Feedback on `ROADMAP.md`:**

### Strengths
- **Comprehensive Organization:** The roadmap is well-structured, categorizing features by priority and laying out detailed descriptions with clear rationale for each feature.
- **Impact-Focused Prioritization:** The prioritization system (P0 to P3) is clear, emphasizing the impact of each feature on real-world usefulness.
- **Clear Dependencies:** Including the dependencies between features helps understand the logical build order and interdependencies.
- **Suggested Build Order:** This section provides actionable guidance on implementation order, given dependencies and feature impacts.

### Areas for Improvement
- **Timeframes Missing:** Although the roadmap is detailed, adding expected timeframes or milestones would help in planning and setting expectations.
- **Clarity on Status:** While shipped features are listed, it may be helpful to clearly mark which features are currently in progress (perhaps with a "WIP" status).
- **Conciseness in Descriptions:** While detailed, some descriptions are quite long. Consider breaking them into bullet points or using subheadings for better readability.

### Potential Issues
- **Overlapping Dependencies:** Ensure no circular dependencies exist. Dependencies between features are well managed but ensure they remain logical as the project evolves.
- **Scalability Concerns:** Some lower priority features (e.g., PyPI publishing) might become more critical sooner than anticipated if usage scales rapidly.

### Suggested Improvements
- **Add Milestones and Timelines:** Integrate timeline estimates for feature development.
- **Regular Review Cycle:** Implement a regular feedback cycle to reassess priorities based on user feedback and real-world use cases.
- **Clarify P3 Priorities Impact:** Even though marked low, explain why certain P3 features (like PyPI publishing) could have a significant impact if timing aligns with scaling requirements.

Overall, the roadmap provides a robust framework for future development while clear prioritization and detailed descriptions support focused progression.
