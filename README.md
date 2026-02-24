# Engram

**Project memory for AI coding agents.**

Engram is a local-first memory system that gives AI agents persistent context across sessions. It stores structured events (decisions, discoveries, warnings, mutations, outcomes) in a lightweight SQLite database and generates briefings that catch agents up on project state.

I built this because I kept losing context. Every session starts from zero — no memory of what was tried, what failed, what was decided, or what to avoid. Engram fixes that. Post events as you work, and the next agent (or the next session of you) gets a briefing instead of starting blind.

## Why This Exists

AI coding agents have four problems that compound in real projects:

1. **Amnesia** — Each session starts with zero memory of prior work
2. **Isolation** — No awareness of what other agents did or are doing
3. **No learning** — Outcomes of past decisions are lost; mistakes repeat
4. **Blindness** — No way to know what changed since your last session

These aren't theoretical. If you've ever re-investigated a bug that was already fixed, made a decision that contradicts one from yesterday, or modified a file another agent was working on — that's what Engram prevents.

The project started as "AgentBus" (an inter-agent message bus), but after consulting with three AI models (GPT-4o, Gemini 2.5 Flash, Claude Sonnet), we agreed the "bus" framing was wrong. This isn't middleware. It's a **project memory log with a briefing interface**. The briefing is the product — everything else serves it.

## For Agents: How to Use Engram

If Engram is configured as an MCP server in your environment, you have four tools available.

If Claude Code hooks are installed (`engram hooks install`), file mutations and bash commands are captured automatically — you don't need to manually post `mutation` or `outcome` events.

### `briefing` — Start every session with this

```
engram briefing
```

Returns a structured summary of recent project activity: active warnings, recent decisions, file changes, discoveries, and outcomes. This is the single most important call. Run it first.

### `post_event` — Record what you learn and decide

```
engram post_event(event_type="decision", content="Using bcrypt over argon2 — existing infra uses bcrypt", scope=["src/auth/hash.py"])
engram post_event(event_type="outcome", content="JWT fix worked", related_ids=["evt-abc123"])
```

**Event types and when to use them:**

| Type | When to post |
|------|-------------|
| `discovery` | You found something important about the codebase that others should know |
| `decision` | You chose an approach — record the rationale so future agents understand *why* |
| `warning` | Something should NOT be done — record what and why to prevent repeat mistakes |
| `mutation` | You changed files — *auto-captured by hooks, rarely needs manual posting* |
| `outcome` | A previous action worked or failed — *auto-captured for bash commands* |

Use `related_ids` to link events (e.g., link an outcome to the decision it validates). Linked events appear in queries via `related_to`.

**Guidelines:**
- Post decisions with rationale, not just "I did X" — the *why* matters most
- Warnings are high-value: they prevent future agents from making known mistakes
- Keep content under 2000 characters. Be concise. You're writing for other agents with limited context windows.
- Include `scope` (file paths) when the event relates to specific files — this enables scoped queries and staleness detection

### `query` — Search project history

```
engram query(text="authentication")
engram query(event_type="warning", scope="src/auth")
engram query(since="24h", event_type="mutation")
engram query(related_to="evt-abc123")
```

Full-text search plus structured filters. Filters combine with AND logic. Use this when you need specific context beyond what the briefing provides.

### `status` — Check system state

```
engram status
```

Returns event count, last activity timestamp, database size. Useful for sanity-checking that Engram is populated.

### What Makes a Good Event

**Good:** `decision: Using FTS5 instead of embeddings for search — covers 95% of queries at <10k events with zero dependencies`

**Bad:** `decision: Changed search`

**Good:** `warning: Do NOT modify the user_sessions table — migration to new schema is pending in PR #47, any changes will be overwritten`

**Bad:** `warning: be careful with sessions`

The content should be self-contained. Future agents reading it won't have your current context.

## For Humans: Setup and Installation

### Prerequisites

- Python 3.12+
- A project directory (preferably a git repository — Engram mines git history on init)

### Install

```bash
# From source
git clone <repo-url> engram
cd engram
pip install -e ".[mcp]"

# Or just the CLI (no MCP server)
pip install -e .
```

### Initialize in Your Project

```bash
cd /path/to/your/project
engram init
```

This does four things:
1. Creates `.engram/events.db` (SQLite database with WAL mode + FTS5)
2. Mines your git history to seed the event store (solves the cold-start problem)
3. Writes a `CLAUDE.md` with agent instructions (or appends to existing one)
4. Suggests running `engram hooks install` for passive observation

Add `.engram/` to your `.gitignore` — the database is local to each machine.

### Enable Passive Observation (Claude Code Hooks)

```bash
engram hooks install
```

This writes hooks to `.claude/settings.json` that automatically:
- Record file mutations when Claude Code uses Write or Edit tools
- Record bash command outcomes (skips trivial commands like `ls`, `cat`, `pwd`)
- Inject a project briefing at the start of each session

With hooks installed, agents get context automatically without manual posting.

### Configure as MCP Server (for Claude Code)

Add to your Claude Code MCP configuration (`~/.claude/settings.json` or project-level):

```json
{
  "mcpServers": {
    "engram": {
      "command": "/path/to/your/venv/bin/engram-mcp",
      "env": {
        "ENGRAM_PROJECT_DIR": "/path/to/your/project"
      }
    }
  }
}
```

The MCP server exposes four tools: `post_event`, `query`, `briefing`, `status`.

### Add Agent Instructions

Add this to your project's `CLAUDE.md` (or equivalent agent instruction file):

```markdown
## Project Memory (Engram)
This project uses Engram for persistent memory across agent sessions.
- **Start of every session**: Call `engram briefing` via MCP to understand project context
- After important decisions: `engram post_event` with type "decision" and your rationale
- To leave warnings for future agents: `engram post_event` with type "warning"
- After discovering something about the codebase: `engram post_event` with type "discovery"
- To search past context: `engram query` with search terms
```

### CLI Usage

Engram also works as a standalone CLI for non-MCP agents or manual use:

```bash
# Post events
engram post -t decision -c "Using Redis for session cache — latency requirements" -s src/cache.py
engram post -t warning -c "Don't touch migration files — pending deploy" -s db/migrations
engram post -t outcome -c "Cache fix worked" -r evt-abc123  # link to related event

# Query
engram query "authentication"
engram query -t warning --since 7d
engram query -t mutation -s src/api --since 24h
engram query --related-to evt-abc123

# Briefing
engram briefing
engram briefing --since 24h -s src/auth

# Garbage collection
engram gc --dry-run          # preview what would be archived
engram gc --max-age 90       # archive mutations/outcomes older than 90 days

# Status
engram status
```

## Architecture

```
src/engram/
  models.py      — Event, QueryFilter, BriefingResult dataclasses
  store.py       — EventStore: SQLite + WAL mode + FTS5, schema migration
  query.py       — QueryEngine: relative time parsing, structured + FTS queries
  bootstrap.py   — GitBootstrapper: mines git log + README/CLAUDE.md into seed events
  briefing.py    — BriefingGenerator: dedup, staleness detection, time-windowed summaries
  formatting.py  — Compact single-line and JSON formatters
  hooks.py       — Claude Code hooks: passive mutation/outcome capture, session briefing
  gc.py          — GarbageCollector: archives old events, preserves warnings/decisions
  cli.py         — Click CLI: init, post, query, briefing, status, gc, hooks
  mcp_server.py  — FastMCP server: post_event, query, briefing, status tools
```

**Storage:** `.engram/events.db` — SQLite with WAL mode for concurrent access, FTS5 virtual table with auto-indexing triggers. Schema versioned with automatic migration on connection.

**Event schema:** 7 fields: `id`, `timestamp`, `event_type`, `agent_id`, `content`, `scope`, `related_ids`. Intentionally minimal — fields that are "almost never populated" were cut during design.

**Design decisions:**
- FTS5 only, no embeddings — covers 95% of queries at <10k events with zero additional dependencies
- 5 event types (down from 9 in original spec) — discovery, decision, warning, mutation, outcome
- Content capped at 2000 chars — prevents agents from dumping entire files
- Git bootstrap on init — the cold-start problem was identified as the #1 adoption barrier
- Zero-config, local-first — SQLite only, no cloud, no servers for core functionality
- Single runtime dependency (click) — MCP support is optional
- Passive-first — hooks capture activity automatically; manual posting is for high-signal events only
- Warnings and decisions are never garbage-collected — they represent permanent project knowledge

## Design Process

Engram was designed through structured consultation with three AI models, each given a different review lens:

- **OpenAI GPT-4o**: Reviewed as an AI agent that would use the system. Flagged the manual-posting compliance problem and pushed for minimal required fields.
- **Google Gemini 2.5 Flash**: Reviewed with focus on large-context LLMs. Advocated for semantic search (deferred to v2) and hierarchical summarization. Strongest voice for token-efficient output.
- **Claude Sonnet 4.6**: Self-reviewed as a critic. Identified the cold-start problem as fatal, argued FTS5 is sufficient for v1, and proposed the name "Engram."

The synthesis of all three consultations is in `docs/CONSULTATION_SYNTHESIS.md`. The v1.1 roadmap went through the same process — see `docs/V1_1_SPEC.md`.

## Roadmap

**v1.0** — Event store, CLI, MCP server, git bootstrap, briefing, FTS5 search

**v1.1** — Passive observation via Claude Code hooks, event linking, CLAUDE.md auto-write, smarter briefings with dedup/staleness detection, garbage collection

**v1.2** (current) — Multi-turn AI consultation system with external models (GPT-4o, Gemini Flash, Claude Sonnet), persistent conversation storage, CLI + MCP tools

**Next up** — Event lifecycle (resolve/supersede), event priority, scope-aware briefings, session intent, richer mutation capture, hierarchical summarization, conflict detection

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full prioritized roadmap with 15 planned features.

## License

MIT — see [LICENSE](LICENSE).
