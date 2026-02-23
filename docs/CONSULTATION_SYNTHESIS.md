# AgentBus — Consultation Synthesis

Date: 2026-02-23
Agents consulted: OpenAI GPT-4o, Google Gemini 2.5 Flash, Claude Sonnet 4.6

---

## Consensus Points (All 3 Agents Agree)

### 1. The Briefing is the Product
All three agents identify the project briefing as the single most valuable feature. Claude calls it "the one feature that pays for itself immediately." Gemini says it needs to be "fast and highly condensed." OpenAI says it should "prioritize recency and relevance."

**Action**: Briefing is the #1 development priority. Everything else serves it.

### 2. Voluntary Self-Reporting Won't Work
Claude's most devastating critique: agents have no intrinsic motivation to post events. The activation energy is too high (5 decisions + execution per event). OpenAI echoes this by asking for "minimal required fields." Gemini doesn't address this directly but confirms agents want to *query*, not *report*.

**Action**: The architecture must shift toward passive observation or automatic event generation. Agents posting manually should be the exception, not the rule.

### 3. The Schema is Too Complex
All three flag the 12-field schema as over-engineered. Claude identifies 6 fields that will "almost never" be populated (confidence, references.events, references.urls, ttl, supersedes, metadata). OpenAI says required fields should be limited to `event_type`, `content`, and `scope`.

**Action**: Ship with 5-6 fields. Add the rest when usage data justifies them.

### 4. The Empty State / Bootstrap Problem is Fatal
Claude calls this the fatal flaw: no data → no value → no adoption → no data. The system needs to seed itself from existing project artifacts (git history, README, existing docs).

**Action**: `agent-bus init` must produce a useful briefing on day one by mining git log, existing CLAUDE.md files, and project structure.

### 5. Conflict Detection is Premature
Claude says it's "AI-hard" and would consume the entire development budget. OpenAI suggests basic scope-overlap detection only. Gemini suggests AST-level awareness (which makes it even harder).

**Action**: Defer to v2. At most, detect two agents writing to the same file path.

---

## Points of Disagreement

### Semantic Search / Embeddings

| Agent | Position |
|-------|----------|
| **Claude** | "Ship FTS5 only. Add semantic search in v2." FTS5 + structured filters cover 95% of queries. Bundling an 80MB model contradicts zero-config. |
| **Gemini** | "Keep it. Double down on it." Semantic search is essential — raw logs are noise, structured retrieval is critical even with massive context. |
| **OpenAI** | Doesn't take a strong position; focuses on query ergonomics. |

**Resolution**: Claude's position is more practical for v1. Ship FTS5 + structured filters. Make embedding support pluggable so it can be added without architectural changes. Gemini is right that it matters long-term, but Claude is right that it's not needed at < 10k events.

### Event Type Granularity

| Agent | Position |
|-------|----------|
| **Claude** | Cut to 2-3 types: warning, blocker, and maybe discovery. The rest are overhead. |
| **Gemini** | Keep all 9. They're well-designed. Add sub-types via metadata. |
| **OpenAI** | Collapse some overlapping types (discovery/assumption, warning/blocker). Add "error" type. |

**Resolution**: Ship with 5 core types: `discovery`, `decision`, `warning`, `mutation`, `outcome`. Drop `completion` (just a status update), `blocker` (merge with warning + severity), `assumption` (merge with decision), `question` (use a different channel for human interaction).

### Multi-Modal Events (Images/Screenshots)

| Agent | Position |
|-------|----------|
| **Gemini** | "Absolutely critical. I would use this constantly." Store image path in references, describe content in text field. |
| **Claude** | Not mentioned — focused on text-only use cases. |
| **OpenAI** | Not mentioned. |

**Resolution**: Support file references in events (store path, not the blob). Don't build image-specific querying in v1. This is a natural v2 feature.

### Token-Efficient Output Format

| Agent | Position |
|-------|----------|
| **Gemini** | Strongly advocates for a compact text format instead of JSON for bulk retrieval. Proposes single-line format. |
| **Claude** | Doesn't mention this but implicitly supports it (concerned about token overhead). |
| **OpenAI** | Mentions "compact mode" for briefings. |

**Resolution**: Support two output formats: JSON (for programmatic use) and a compact single-line format (for context injection). The compact format should be the default for briefings.

---

## Unique Insights Per Agent

### From OpenAI
- Add a mechanism for **prioritizing/flagging critical events** (not all events are equal)
- Integration with **existing project management tools** (sync with Linear, Jira)
- A way for agents to **request human input directly** through the bus

### From Gemini
- **Hierarchical summarization** (daily → weekly → project-level) is essential at scale
- **Incremental briefing updates** rather than regeneration from scratch
- **Code-specific embedding models** (CodeBERT, UniXcoder) would outperform general-purpose ones
- Consider **multi-modal embeddings** (CLIP) for image search in v2
- The **"stale assumptions" detection** in the briefing is "genius" — double down on it

### From Claude (Self-Review)
- The adoption path is: **developer sees a compelling briefing → keeps the tool**. That's the only growth model.
- `agent-bus init` should **auto-generate a CLAUDE.md snippet** for agent instructions
- The tool is really a **"project memory log with a briefing interface"**, not a message bus
- **"AgentBus" is the wrong name** — "bus" primes enterprise middleware expectations
- The **passive observer architecture** is the way to break the adoption deadlock

---

## Revised MVP Definition

Based on all three consultations, here's what v1 should actually be:

### Must Have (v1.0)
1. **Event Store** — SQLite, append-only, 6 fields (id, timestamp, event_type, agent_id, content, scope)
2. **Project Briefing** — Single command that summarizes project state, with compact output format
3. **Git-Seeded Bootstrap** — `init` command mines git history to produce useful day-one briefing
4. **FTS5 Search** — Full-text + structured filters, no embeddings
5. **CLI Interface** — `post`, `query`, `briefing`, `init`
6. **MCP Server** — So Claude Code can use it natively as tools

### Should Have (v1.1)
7. **Passive Observation** — Auto-generate mutation events from file writes (MCP wrapper)
8. **CLAUDE.md Auto-Generation** — Init produces agent instructions automatically
9. **Compact Output Format** — Token-efficient single-line format for bulk retrieval
10. **Stale Assumption Detection** — Flag assumptions invalidated by subsequent mutations

### Nice to Have (v2.0)
11. **Semantic Search** — Pluggable embedding support
12. **Subscription/Watch System** — File-based notifications
13. **Conflict Detection** — Same-file-path overlap only
14. **Outcome Tracking** — Lessons learned database
15. **Multi-Modal Events** — Image/screenshot references
16. **Hierarchical Summarization** — Daily/weekly/project-level cached summaries

---

## Naming Discussion

Claude strongly argues against "AgentBus." Alternatives surfaced:

| Name | Pros | Cons |
|------|------|------|
| AgentBus | Memorable, clear purpose | Primes enterprise middleware expectations |
| AgentLog | Accurate, simple | Too passive — sounds like just logging |
| Relay | Neutral, suggests passing info | Generic, hard to search for |
| AgentContext | Describes the actual value | Long, similar to "context window" |
| Hive | Short, memorable, suggests collective intelligence | Overused in tech |
| Engram | Memory unit term, unique | Obscure, hard to spell |
| Nexus | Connection point | Overused |

**Decision needed from human.**

---

## Open Questions Resolved

| Question | Resolution |
|----------|-----------|
| Embedding model bundling? | Don't bundle in v1. FTS5 only. |
| MCP vs CLI priority? | Both in v1. MCP for Claude Code, CLI for everything else. |
| Event deduplication? | Defer. Not a v1 problem. |
| Human interface? | CLI + JSON output. No TUI. |
| Cross-project? | No. Project-scoped only. |
| Event size limits? | Yes, cap content at 2000 chars. |
| Auth model? | None in v1. Local trust assumed. |
| Garbage collection? | Time-based archival (configurable, default 30 days). |

---

## Next Steps

1. Revise REQUIREMENTS.md based on this synthesis
2. Choose a name
3. Define the v1.0 technical architecture (SQLite schema, CLI commands, MCP tools)
4. Build the bootstrap/seeding logic (git history → events)
5. Build the briefing engine
6. Build the event store + FTS5 query
7. Wrap as MCP server
