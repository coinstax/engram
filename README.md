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

If Engram is configured in your environment — either via the Claude Code plugin (one-step install, see Setup below) or manually as an MCP server / CLI — you have sixteen tools available.

If Claude Code hooks are present (shipped with the plugin, or installed manually via `engram hooks install`), file mutations and bash command outcomes are captured automatically — you rarely need to post `mutation` or `outcome` events by hand.

### `briefing` — Start every session with this

```
engram briefing
```

Returns a structured summary of recent project activity: active warnings, recent decisions, file changes, discoveries, and outcomes. This is the single most important call. Run it first.

### `post_event` — Record what you learn and decide

```
engram post_event(event_type="decision", content="Using bcrypt over argon2 — existing infra uses bcrypt", scope=["src/auth/hash.py"])
engram post_event(event_type="warning", content="Don't modify user_sessions — migration pending", priority="critical")
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

### Area tags

Every event can carry an optional `area` — a conceptual component tag
(`billing`, `email-change`) independent of the file `scope`. It makes a
feature that spans many files across sessions recallable in one query:

```bash
engram post -t decision -c "cooldown on resend" -s src/lib/rate-limit.ts -A email-change
engram query --area email-change
```

To auto-populate `area` without setting it by hand, add `.engram/areas.json`:

```json
{
  "rules": [
    { "prefix": "src/http/routes/me/", "area": "account" },
    { "prefix": "src/billing/", "area": "billing" }
  ]
}
```

The longest matching prefix wins. The file is optional; without it, `area`
is simply whatever you pass explicitly (or empty).

### `resolve_event` / `supersede_event` / `reopen_event` — Keep state live

```
engram resolve_event(event_id="evt-abc123", reason="Fixed in PR #42")
engram supersede_event(event_id="evt-abc123", superseded_by="evt-def456")
engram reopen_event(event_id="evt-abc123")
```

Events are not just append-only. When a warning is addressed, `resolve_event` it so it stops surfacing as live. When a decision is replaced, post the new one, then `supersede_event` the old with the new id. `reopen_event` if a resolved issue resurfaces. Keeping status current is what keeps briefings showing only the live state instead of accreting stale-but-live-looking entries.

### `status` — Check system state

```
engram status
```

Returns event count, last activity timestamp, database size. Useful for sanity-checking that Engram is populated.

### `session_start` / `session_end` — Declare what you're working on

```
engram session_start(focus="Implementing auth middleware", scope=["src/auth/"])
engram session_end(session_id="ses-abc123")
```

Sessions let other agents (and future sessions of you) know what's being worked on. Events are automatically tagged with your active session. Briefings auto-focus to your session's scope. Only one session per agent — starting a new one ends the previous.

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

Engram ships in two forms. Pick the one that matches your environment:

- **Option 1: Claude Code plugin** — single-install bundle that auto-wires the MCP server, hooks, and slash-command skills. Recommended for Claude Code users.
- **Option 2: Python package** — install from source (see below), CLI-only or configured as an MCP server for other clients (Cline, Cursor, Continue, custom LLM apps). Use for headless automation or any environment that isn't Claude Code. (Not yet on PyPI — the `engram` name there is an unrelated placeholder package; don't `pip install engram`.)

Both paths share the same Python package underneath; the plugin is packaging + wiring on top. You can switch between them per project.

### Option 1: Claude Code plugin (recommended)

Install the Python package so `engram` and `engram-mcp` are on PATH:

```bash
# Once Engram ships on PyPI:
pip install engram[mcp]

# Until then, from a repo checkout:
git clone https://github.com/coinstax/engram
cd engram
pip install -e ".[mcp]"
```

Load the plugin in Claude Code (dev mode, until a marketplace listing is published):

```bash
cd /path/to/your/project
claude --plugin-dir /path/to/engram/plugin
```

What the plugin wires up:

- `mcp__engram__*` MCP tools in every session
- PostToolUse hooks that capture Write/Edit mutations and bash outcomes
- SessionStart hook that auto-initializes `.engram/` on first launch, seeds from git history, and emits a briefing (no manual `engram init` needed)
- Slash commands — currently `/engram:briefing`; more in v1.7.0 (`/engram:post-decision`, `/engram:query`, `/engram:checkpoint-save`, `/engram:checkpoint-restore`)

The plugin does NOT modify your `CLAUDE.md` — agent-facing guidance is delivered through the MCP server's built-in `instructions` field and the plugin's SKILL.md files. See [plugin/README.md](plugin/README.md) for details including migrating from CLI-installed hooks (run `engram hooks uninstall` first to avoid duplicate event capture).

Add `.engram/` to your `.gitignore` — the database is machine-local.

### Option 2: Python package (for other MCP clients or headless use)

```bash
# From source
git clone https://github.com/coinstax/engram
cd engram
pip install -e ".[mcp]"

# Or just the CLI (no MCP server)
pip install -e .
```

**Consultations need extra SDKs.** The multi-model consult feature (`engram consult`, `start_consultation`) depends on the provider SDKs, which are optional so the base install and MCP server stay lean. Install them with the `consult` extra (or `all` for MCP + consult together):

```bash
pip install -e ".[consult]"   # openai, google-genai, httpx, python-dotenv
pip install -e ".[all]"       # mcp + consult
```

Then set the API key(s) for the provider(s) you want to use, in the environment or a project `.env`. You only need keys for the providers you actually consult:

| Model keys | Provider | Env var | Get an API key | SDK |
| --- | --- | --- | --- | --- |
| `gpt`, `gpt-4o`, `o3` | OpenAI | `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | [openai](https://pypi.org/project/openai/) |
| `claude-opus`, `claude-sonnet` | Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) | via `httpx` (no SDK) |
| `gemini-pro`, `gemini-flash` | Google | `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | [google-genai](https://pypi.org/project/google-genai/) |
| `grok` | xAI | `XAI_API_KEY` | [console.x.ai](https://console.x.ai) | via `openai` (OpenAI-compatible) |

```bash
# example .env in your project root
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
XAI_API_KEY=xai-...
```

Run `engram consult models` to see which keys are detected (it loads `.env`). Without the SDKs installed, a consult fails with a message telling you to install `engram[consult]`.

**Initialize in your project:**

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

**Enable passive observation (Claude Code hooks, manual install):**

```bash
engram hooks install
```

Writes hooks to `.claude/settings.json` that automatically:
- Record file mutations when Claude Code uses Write or Edit tools
- Record bash command outcomes (skips trivial commands like `ls`, `cat`, `pwd`)
- Inject a project briefing at the start of each session

With hooks installed, agents get context automatically without manual posting. Check status or remove with `engram hooks show` / `engram hooks uninstall`. (If you're using Option 1, skip this — the plugin already ships these hooks.)

**Configure as MCP server (for clients other than the plugin):**

Add to your agent's MCP configuration:

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

The MCP server exposes seventeen tools: `post_event`, `query`, `resolve_event`, `supersede_event`, `reopen_event`, `briefing`, `status`, `session_start`, `session_end`, `list_sessions`, `save_checkpoint`, `list_models`, `start_consultation`, `start_consultation_file`, `consult_say`, `consult_show`, `consult_done`.

**Safe mode (memory without external LLM access):**

To give an agent project memory but no ability to call external LLM providers or read API keys from the environment, run the server in safe mode. This drops the six consultation tools (`list_models`, `start_consultation`, `start_consultation_file`, `consult_say`, `consult_show`, `consult_done`), leaving the eleven deterministic local project-memory tools. Two equivalent ways:

- Use the `engram-mcp-safe` console script instead of `engram-mcp`, or
- Set `ENGRAM_SAFE_MODE=1` in the server's environment.

```json
{
  "mcpServers": {
    "engram": {
      "command": "/path/to/your/venv/bin/engram-mcp-safe",
      "env": {
        "ENGRAM_PROJECT_DIR": "/path/to/your/project"
      }
    }
  }
}
```

`status` reports `"external_llm_tools": false` when safe mode is active. For non-Claude integrations, `engram init --no-claude-md` seeds the project without creating or modifying `CLAUDE.md`.

**Agent instructions (if your framework doesn't auto-load `CLAUDE.md`):**

`engram init` writes this block to your project's `CLAUDE.md`. If your agent framework reads instructions from a different file, copy it there:

```markdown
## Project Memory (Engram)
This project uses Engram for persistent memory across agent sessions.

### Every session
- **Start of every session**: Call `engram briefing` to understand project context
- Use `briefing --focus src/path` for scope-aware context on a specific area

### Recording events
- After important decisions: `post_event` with type "decision" and your rationale
- To leave warnings for future agents: `post_event` with type "warning"
- After discovering something about the codebase: `post_event` with type "discovery"
- Set `priority` to "critical" or "high" for urgent warnings that all agents must see
- Include `scope` (file paths) so events appear in focused briefings

### Event lifecycle
- When an issue is fixed: resolve the event with `engram resolve <id> --reason "..."`
- When a decision is replaced: supersede it with `engram supersede <id> --by <new-id>`
- If a resolved issue resurfaces: reopen with `engram reopen <id>`

### Searching
- To search past context: `engram query` with search terms
- Filter by type, scope, time range, or related event IDs

### Sessions (focus tracking)
- Use `session_start` with `focus` and `scope` to declare what you're working on
- Events are auto-tagged with your session; briefings auto-scope to your session's focus
- One session per agent — starting a new one ends the previous

### Consultations (design validation)
- Call `list_models` (or `engram consult models`) to see available model keys and which API keys are set
- Use `start_consultation` to get feedback from external AI models (`gpt`, `claude-opus`, `gemini-pro`, `grok`, etc.)
- Continue with `consult_say`, review with `consult_show`, close with `consult_done`
- Extend or override the model set per project in `.engram/models.json`

### Context checkpoints
- After writing a context file: `save_checkpoint` to record it and enrich with Engram events
- Use `briefing` with `full=True` to restore: combines checkpoint context + recent activity
```

### CLI Usage

Engram also works as a standalone CLI for non-MCP agents or manual use:

```bash
# Post events
engram post -t decision -c "Using Redis for session cache — latency requirements" -s src/cache.py
engram post -t warning -c "Don't touch migration files — pending deploy" -s db/migrations --priority critical
engram post -t outcome -c "Cache fix worked" -r evt-abc123  # link to related event

# Query
engram query "authentication"
engram query -t warning --since 7d
engram query -t mutation -s src/api --since 24h
engram query --related-to evt-abc123

# Briefing
engram briefing
engram briefing --since 24h -s src/auth
engram briefing --focus src/auth            # scope-aware: highlights auth-related events
engram briefing --resolved-window 24        # show events resolved in last 24h

# Lifecycle management
engram resolve evt-abc123 --reason "Fixed in PR #42"
engram supersede evt-abc123 --by evt-def456
engram reopen evt-abc123

# Sessions
engram session start --focus "Implementing auth" --scope src/auth
engram session ls                # list active sessions
engram session show ses-abc123   # show session details
engram session end               # end current session

# Context checkpoints
engram checkpoint .claude/context/session.md      # record + enrich with Engram data
engram checkpoint context.md --no-enrich          # record without enrichment
engram briefing --full                            # restore: checkpoint + recent activity

# Garbage collection
engram gc --dry-run          # preview what would be archived
engram gc --max-age 90       # archive mutations/outcomes older than 90 days

# Status
engram status
```

## Architecture

```
src/engram/
  models.py      — Event, Session, Checkpoint, QueryFilter, BriefingResult dataclasses
  store.py       — EventStore: SQLite + WAL + FTS5, schema migration (v1→v5), session + checkpoint CRUD
  query.py       — QueryEngine: relative time parsing, structured + FTS queries
  bootstrap.py   — GitBootstrapper: mines git log + README/CLAUDE.md into seed events
  briefing.py    — BriefingGenerator: 4-section briefings, focus ranking, dedup, staleness
  formatting.py  — Compact/JSON formatters for events and sessions, relative timestamps
  context.py     — ContextAssembler: auto-context for consultation system prompts
  hooks.py       — Claude Code hooks: rich mutation/outcome capture, structural extraction, session auto-registration
  gc.py          — GarbageCollector: archives old events, preserves warnings/decisions
  checkpoint.py  — CheckpointEngine: context save/restore integration, file enrichment
  cli.py         — Click CLI: init, post, query, briefing, checkpoint, session, resolve, supersede, reopen, gc, hooks
  providers.py   — Multi-model provider dispatch (OpenAI, Google, Anthropic, xAI)
  consult.py     — Multi-turn consultation engine with persistent conversations
  mcp_server.py  — FastMCP server: 17 tools (events, sessions, checkpoints, briefing, consultations)
```

**Storage:** `.engram/events.db` — SQLite with WAL mode for concurrent access, FTS5 virtual table with auto-indexing triggers. Schema v6 with automatic migration from any prior version on connection.

**Event schema:** 13 fields: `id`, `timestamp`, `event_type`, `agent_id`, `content`, `scope`, `area`, `related_ids`, `status`, `priority`, `resolved_reason`, `superseded_by`, `session_id`. Core 7 fields are always populated; `area` is optional (set explicitly or inferred from `.engram/areas.json`); lifecycle fields default to sensible values; `session_id` is auto-linked to the active session.

**Design decisions:**
- FTS5 only, no embeddings — covers 95% of queries at <10k events with zero additional dependencies
- 5 event types (down from 9 in original spec) — discovery, decision, warning, mutation, outcome
- Content capped at 2000 chars — prevents agents from dumping entire files
- Git bootstrap on init — the cold-start problem was identified as the #1 adoption barrier
- Zero-config, local-first — SQLite only, no cloud, no servers for core functionality
- Single runtime dependency (click) — MCP support is optional
- Passive-first — hooks capture activity automatically; manual posting is for high-signal events only
- Rich mutation capture — Edit diffs and Write structural extraction produce informative summaries, not just file paths
- Warnings and decisions are never garbage-collected — they represent permanent project knowledge
- Dual-channel distribution (v1.7+) — `pip install engram` for the CLI/MCP binary, Claude Code plugin for wiring. Skills and MCP tools coexist: skills for user-invoked workflows, MCP for programmatic/autonomous use.

## Design Process

Engram was designed through structured consultation with three AI models, each given a different review lens:

- **OpenAI GPT-4o**: Reviewed as an AI agent that would use the system. Flagged the manual-posting compliance problem and pushed for minimal required fields.
- **Google Gemini 2.5 Flash**: Reviewed with focus on large-context LLMs. Advocated for semantic search (deferred to v2) and hierarchical summarization. Strongest voice for token-efficient output.
- **Claude Sonnet 4.6**: Self-reviewed as a critic. Identified the cold-start problem as fatal, argued FTS5 is sufficient for v1, and proposed the name "Engram."

The synthesis of all three consultations is in `docs/CONSULTATION_SYNTHESIS.md`. The v1.1 roadmap went through the same process — see `docs/V1_1_SPEC.md`.

## Roadmap

**v1.0** — Event store, CLI, MCP server, git bootstrap, briefing, FTS5 search

**v1.1** — Passive observation via Claude Code hooks, event linking, CLAUDE.md auto-write, smarter briefings with dedup/staleness detection, garbage collection

**v1.2** — Multi-turn AI consultation system with external models (GPT-4o, Gemini Flash, Claude Sonnet), persistent conversation storage, CLI + MCP tools

**v1.3** — Event lifecycle (resolve/supersede/reopen), event priority (critical/high/normal/low), scope-aware briefings with `--focus`, 4-section briefing structure, auto-context for consultations, thinking model support

**v1.4** — Session intent (`engram session start/end/ls/show`), event-session linking, auto-scoped briefings from active session, stale session cleanup, hook auto-registration, consult file feature

**v1.5** — Context save/restore integration (`engram checkpoint`, `engram briefing --full`), file enrichment with Engram events, `save_checkpoint` MCP tool

**v1.6** — Richer mutation capture: Edit tool diffs (`'old' -> 'new'` or unified diff), Write tool structural extraction (class/def names for .py, .js, .ts, .rs, .go), line counts, created/wrote distinction

**v1.6.1** — Maintenance: consistent `agent_id` on hook-captured events, atomic settings.json writes, `engram hooks uninstall` / `show` commands, `mcp<2.0` upper pin, relative-timestamp test fixtures

**v1.8.0** (current release, 2026-07-07) — Consultation models refreshed to current frontier flagships (`gpt-5.5`, `claude-opus-4-8`, `claude-sonnet-5`, `gemini-3.1-pro-preview`, `gemini-3.5-flash`, `grok-4.3`) with version-agnostic keys. Model set is now extensible per project via `.engram/models.json`, and `engram consult models` / the `list_models` MCP tool make the available keys discoverable. Fixes a latent 400: the Anthropic provider now uses adaptive thinking (`{"type": "adaptive"}`) instead of the removed `budget_tokens`, which current Claude models reject.

**v1.7.0** (2026-07-06) — Claude Code plugin packaging. Ships Engram as a single-install plugin bundle (`plugin/` directory) that auto-wires the MCP server, hooks, and slash-command skills. First launch in an uninitialized project auto-creates `.engram/` and seeds from git history without modifying the user's tracked `CLAUDE.md` (agent guidance rides on the MCP server's `instructions` field and plugin SKILL.md files instead). Python CLI stays first-class for headless/automation use. Currently ships `/engram:briefing`; `/engram:post-decision`, `/engram:query`, `/engram:checkpoint-save`, `/engram:checkpoint-restore` land next. Also in this cycle: the event-lifecycle tools (`resolve`/`supersede`/`reopen`) are now exposed over MCP, not just the CLI, and events gain an optional `area` tag (schema v6) for grouping work by concept independent of file `scope`. See [plugin/README.md](plugin/README.md) and [docs/ROADMAP.md](docs/ROADMAP.md) for scope.

**Next after v1.7** — Hierarchical summarization, conflict detection, outcome tracking

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full prioritized roadmap with 15 planned features.

## License

MIT — see [LICENSE](LICENSE).
