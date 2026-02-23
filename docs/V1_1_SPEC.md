# Engram v1.1 Specification

Date: 2026-02-23
Status: Draft
Consulted: OpenAI GPT-4o, Google Gemini 2.5 Flash, Claude Opus 4.6

---

## Consultation Summary

### What All Three Agents Agree On

1. **Passive observation is the single highest-impact feature.** Without it, Engram remains a manual chore with low compliance. This is the v1.1 linchpin.

2. **Event linking/references should be in v1.1.** Both Gemini and OpenAI independently flagged this as foundational for any intelligence features (staleness detection, causal chains, briefing quality). It's a prerequisite for stale assumption detection.

3. **CLAUDE.md auto-generation is an easy win.** Low effort, high adoption impact. Should have been in v1.0.

4. **Compact output improvements should be deferred.** The current format is good enough. Focus on what gets *into* Engram and how it's *summarized*, not on shaving tokens from output.

5. **Hierarchical summarization and semantic search should stay in v2.** Tempting but premature without a richer event corpus.

### Key Disagreements

| Topic | OpenAI | Gemini | Claude (self) |
|-------|--------|--------|---------------|
| Passive observation method | File watcher (inotify) + git diff | MCP tool wrapper (primary) + file watcher (secondary) + git diff (tertiary) | Claude Code hooks (pre/post) -- most practical for the primary user |
| Stale assumption detection | v1.1 priority | v1.1 but dependent on event linking | v1.1 -- simple version without requiring new event types |
| New "assumption" event type | Not mentioned | Wants it added | Not needed -- decisions with assumption-like content can be detected |

### Gemini's Unique Insight: Intent-Driven Events

Gemini's strongest contribution: passive observation should capture **intent and action-result pairs**, not just raw file changes. The difference between "file changed" and "agent decided to write X because Y, then X changed successfully" is enormous for briefing quality.

### OpenAI's Unique Insight: User Feedback Loop

Agents or users should be able to flag events as inaccurate/irrelevant, which helps refine automatic event generation over time. Not v1.1, but worth designing for.

---

## v1.1 Feature Specification

### Priority Order

1. **Passive Observation via Claude Code Hooks** (P0 -- the unlock)
2. **Event Linking** (P0 -- foundational)
3. **CLAUDE.md Auto-Write on Init** (P1 -- easy win)
4. **Smarter Briefing** (P1 -- dedup, staleness, priority)
5. **Stale Assumption Detection** (P2 -- depends on 1 & 2)
6. **Garbage Collection / Archival** (P2 -- needed before event volume grows)

---

### Feature 1: Passive Observation via Claude Code Hooks

**Problem:** Agents must manually call `engram post` for every event. They won't do this consistently. The activation energy is too high.

**Solution:** Use Claude Code's hook system to automatically capture agent activity. Claude Code supports pre/post hooks on tool calls. When the agent writes a file, runs a command, or edits code, Engram automatically records it.

**Implementation approach:**

Claude Code hooks are configured in `.claude/settings.json` and fire shell commands before/after tool use. This is the most practical approach because:
- Claude Code is the primary (currently only) MCP consumer
- Hooks fire automatically -- zero agent effort
- They have access to tool name, arguments, and results
- No daemon process needed (unlike file watchers)
- No new dependencies

**Concrete design:**

1. **Post-write hook**: After any `write_file` or `edit_file` tool call, fire `engram post -t mutation -c "Modified {filepath}" -s {filepath} -a claude-code-hook`

2. **Post-command hook**: After `bash` tool calls, fire `engram post -t outcome -c "Ran: {command} (exit {code})" -a claude-code-hook` (for non-trivial commands only -- filter out `ls`, `cat`, etc.)

3. **Session start hook**: On first tool call, auto-run `engram briefing` and inject into context.

4. **New CLI command**: `engram hooks install` -- writes the hook configuration to `.claude/settings.json`. This is the "one command to enable passive observation" experience.

**Event volume control:**
- Debounce rapid edits to same file (collapse writes within 5s window)
- Skip trivial commands (configurable ignore list)
- Content summarization: for file writes, store a brief summary not the full diff

**Schema impact:** None -- uses existing event types and fields.

**What this does NOT cover:**
- Non-Claude-Code agents (they still need manual posting or their own hooks)
- Git operations (these are already captured by bootstrap)

---

### Feature 2: Event Linking

**Problem:** Events exist in isolation. An outcome can't reference the decision it evaluates. A mutation can't point back to why it was made. This makes briefings and staleness detection impossible to do well.

**Solution:** Add an optional `related_ids` field to events.

**Schema change:**

```sql
ALTER TABLE events ADD COLUMN related_ids TEXT;
-- JSON array of event IDs, e.g. '["evt-abc123", "evt-def456"]'
```

**Model change:**

```python
@dataclass
class Event:
    id: str
    timestamp: str
    event_type: EventType
    agent_id: str
    content: str
    scope: list[str] | None = None
    related_ids: list[str] | None = None  # NEW
```

**How linking works:**
- When posting an event, optionally include `--related` IDs
- The MCP `post_event` tool gains a `related_ids` parameter
- Passive observation hooks auto-link when possible (e.g., outcome after decision)
- Linking is always optional -- events without links still work fine

**Query support:**
- `engram query --related-to evt-abc123` -- find all events linked to a given event
- Briefing can follow links to present causal chains

**Complexity budget:** This is a single nullable column + one query method. Minimal.

---

### Feature 3: CLAUDE.md Auto-Write on Init

**Problem:** `engram init` prints a CLAUDE.md snippet but doesn't write it. Users must copy-paste manually.

**Solution:** `engram init` appends the snippet to CLAUDE.md automatically if the file exists (or creates a minimal one if it doesn't). If the snippet is already present, skip it.

**Implementation:**
- After bootstrap, check if `CLAUDE.md` exists in project root
- If yes: check if "Engram" section already exists (search for `## Project Memory (Engram)`)
- If no Engram section: append the snippet with a blank line separator
- If no CLAUDE.md: create one with just the Engram section
- Print confirmation of what was done

**The snippet should also include MCP configuration instructions:**

```
## Project Memory (Engram)
This project uses Engram for persistent memory across agent sessions.
- **Start of every session**: Call `engram briefing` via MCP to understand project context
- After important decisions: `engram post_event` with type "decision" and your rationale
- To leave warnings for future agents: `engram post_event` with type "warning"
- After discovering something about the codebase: `engram post_event` with type "discovery"
- To search past context: `engram query` with search terms
```

---

### Feature 4: Smarter Briefing

**Problem:** The current briefing is a flat list of recent events grouped by type. No deduplication, no priority, no cross-referencing.

**v1.1 improvements (heuristic-based, no LLM required):**

#### 4a. Deduplication

Multiple mutations to the same file within a time window get collapsed:
- "Modified src/auth.py (3 edits, 14:00-14:15)" instead of 3 separate entries
- Group by: same file path + same agent + within 30 min window
- Show only the latest content, with count

#### 4b. Priority Ordering

Within each section, sort by importance heuristic:
- **Warnings**: most recent first (already done), but boost warnings with no related outcome (unresolved)
- **Decisions**: boost decisions that have no related mutation yet (un-acted-on)
- **Mutations**: boost mutations to files that also have warnings

#### 4c. Staleness Flags

When displaying decisions and warnings, check if a subsequent mutation touched the same scope:
- If a warning says "don't modify X" but a mutation modified X after the warning, flag it: `[POSSIBLY STALE]`
- Simple implementation: for each warning/decision, check if any mutation with a later timestamp has overlapping scope

#### 4d. Causal Chain Presentation (requires event linking)

If events are linked, present them as chains instead of flat lists:
```
## Recent Work
- Decision: Use bcrypt for password hashing (14:00)
  -> Mutation: Modified src/auth/hash.py (14:05)
  -> Outcome: All tests passing (14:08)
```

---

### Feature 5: Stale Assumption Detection

**Problem:** An agent posts a decision or warning based on current code state. Later, another agent modifies the relevant code. The original decision may now be invalid, but nothing flags this.

**Implementation:**

This builds on features 2 (event linking) and 4c (staleness flags).

**Algorithm:**
1. For each decision/warning event with a `scope`:
2. Check if any mutation event exists with:
   - Later timestamp
   - Overlapping scope (any file path in common)
   - Different agent_id (another agent made the change) OR significantly later timestamp (same agent, new session)
3. If found, mark the decision/warning as potentially stale in briefing output

**New briefing section:**
```
## Potentially Stale (2)
- [STALE?] Warning "Don't modify user_sessions table" (2d ago, scope: src/db/sessions.py)
  -> Contradicted by: Mutation "Added soft delete column" (6h ago, by claude-session-xyz)
```

**Not building:** Full invalidation tracking, automatic supersession of events, or confidence scoring. Those are v2.

---

### Feature 6: Garbage Collection

**Problem:** Event store grows unboundedly. At scale, queries and briefings slow down.

**Implementation:**

New CLI command: `engram gc`
- Archive events older than N days (default: 90) to a separate SQLite file
- Keep all warnings and decisions regardless of age (they have long-term value)
- Only archive mutations and outcomes older than the threshold
- `engram gc --dry-run` shows what would be archived
- Store archive in `.engram/archive/YYYY-MM.db`

**Auto-GC:** Optionally run GC automatically when event count exceeds a threshold (configurable, default 5000).

---

## What We Are NOT Building in v1.1

1. **Semantic search / embeddings** -- FTS5 is sufficient at current scale. Revisit when event counts justify it.
2. **Hierarchical summarization** -- Requires more event volume and linking maturity. v2.
3. **Subscription / watch system** -- Over-engineered for single-agent use. v2.
4. **HTTP API** -- CLI + MCP covers all current use cases. v2.
5. **Multi-project support** -- Keep it project-scoped. v2.
6. **Conflict detection** -- Still "AI-hard." v2 at earliest.
7. **New event types** -- The 5 types are sufficient. Adding "assumption" creates confusion with "decision."
8. **User feedback on events** -- Good idea (OpenAI), but needs a UI. v2.
9. **IDE integrations** -- Too broad. Claude Code hooks cover the primary use case.

---

## Migration Path

v1.1 must be backwards-compatible with v1.0 event stores:
- `related_ids` column added via `ALTER TABLE` on first access (nullable, no data loss)
- All existing queries continue to work
- `engram init` on an already-initialized project is a no-op (already implemented)
- New `engram upgrade` command runs schema migrations

---

## Success Criteria

v1.1 is successful if:
1. An agent session with hooks installed generates 5+ events automatically without any manual `engram post` calls
2. The briefing output is noticeably more useful than v1.0 (dedup, staleness flags)
3. `engram init` in a new project requires zero manual configuration to start capturing events
4. Event linking enables at least basic causal chain display in briefings

---

## Development Sequence

1. Schema migration + `related_ids` field (foundation for everything)
2. CLAUDE.md auto-write (quick win, ships independently)
3. Claude Code hooks integration + `engram hooks install`
4. Briefing improvements (dedup, staleness, priority)
5. Stale assumption detection in briefing
6. Garbage collection
7. Tests for all new features
