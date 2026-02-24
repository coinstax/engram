# Engram Consultation System — Multi-Turn AI Conversations

## Context

Engram v1.1 is complete. During development, one-shot consultations with GPT-4o and Gemini produced genuinely useful design feedback — but they were single-turn. The user and I agreed that multi-turn back-and-forth would catch more issues (it was exactly this kind of "but what about..." probing that found two bugs in the test coverage audit).

This feature adds a `ConsultationEngine` that lets the host agent (Claude Code) have persistent, multi-turn design discussions with external AI models via their APIs. Conversations are stored in SQLite alongside the event store and can produce Engram events (decisions, discoveries) as artifacts.

**Audit requirement:** All conversations are logged as markdown files in `docs/consultations/` — one file per conversation, updated after each turn. All communication is in English. This provides a human-readable audit trail alongside the SQLite storage.

---

## Phase 1: Provider Abstraction

### New file: `src/engram/providers.py` (~100 lines)

Minimal multi-provider layer. No ABC, no plugin system — a dict of configs and an if/elif dispatch.

```python
MODELS = {
    "gpt-4o":        ModelConfig("openai",    "gpt-4o",             "OPENAI_API_KEY"),
    "gemini-flash":  ModelConfig("google",    "gemini-2.5-flash",   "GOOGLE_API_KEY"),
    "claude-sonnet": ModelConfig("anthropic", "claude-sonnet-4-20250514", "ANTHROPIC_API_KEY"),
}

def send_message(model_key: str, messages: list[dict], system_prompt: str | None = None) -> str:
    """Send conversation history to a model, return response text."""
```

Three private functions: `_send_openai` (uses `openai` SDK), `_send_google` (uses `google.genai` — the new SDK, not deprecated `google.generativeai`), `_send_anthropic` (uses `httpx` directly since the anthropic SDK is not installed and httpx is).

`messages` uses `[{"role": "user"|"assistant", "content": "..."}]` as the common format. Each provider function translates to its native format.

Loads API keys from environment. Calls `load_dotenv()` from project root `.env` if available.

### New file: `tests/test_providers.py`

- Test model registry has expected keys
- Test missing API key raises clear error
- Test each provider function with mocked HTTP (use `unittest.mock.patch`)

---

## Phase 2: Schema Migration (v2 → v3)

### `src/engram/store.py`

Bump `SCHEMA_VERSION` to 3. Add to `_migrate()`:

```python
if version < 3:
    self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (...);
        CREATE TABLE IF NOT EXISTS conversation_messages (...);
        CREATE INDEX IF NOT EXISTS idx_conv_messages_conv
            ON conversation_messages(conv_id, id);
    """)
    self.set_meta("schema_version", "3")
```

**`conversations` table:**
- `id TEXT PRIMARY KEY` — format: `conv-{uuid_hex[:12]}`
- `topic TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'active'` — CHECK: active, paused, completed
- `models TEXT NOT NULL` — JSON array of model keys
- `system_prompt TEXT` — optional shared context
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `summary TEXT` — filled on completion

**`conversation_messages` table:**
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `conv_id TEXT NOT NULL REFERENCES conversations(id)`
- `role TEXT NOT NULL` — CHECK: system, user, assistant
- `sender TEXT NOT NULL` — "host", "gpt-4o", "gemini-flash", etc.
- `content TEXT NOT NULL`
- `created_at TEXT NOT NULL`

Also add to `SCHEMA_SQL` (for fresh databases) so both tables exist on `initialize()`.

### `tests/test_migration.py`

Add test: v2 DB (has events + related_ids but no conversations tables) migrates to v3 cleanly.

---

## Phase 3: Consultation Engine

### New file: `src/engram/consult.py` (~200 lines)

```python
class ConsultationEngine:
    def __init__(self, store: EventStore):
        self.store = store

    def start(self, topic, models, system_prompt=None) -> str:
        """Create conversation. Returns conv_id."""

    def add_message(self, conv_id, content, sender="host") -> dict:
        """Add host message. Returns message dict."""

    def get_responses(self, conv_id, models=None) -> list[dict]:
        """Call each model with full history, save responses. Returns new responses."""

    def get_conversation(self, conv_id) -> dict:
        """Return full conversation with metadata + messages."""

    def list_conversations(self, status=None, limit=20) -> list[dict]:
        """List conversations, optionally filtered."""

    def complete(self, conv_id, summary=None) -> dict:
        """Mark completed, optionally store summary."""

    def extract_event(self, conv_id, event_type, content) -> str:
        """Post an Engram event linked to this conversation via related_ids."""

    def _save_log(self, conv_id) -> Path:
        """Write/overwrite markdown log to docs/consultations/{conv_id}.md.
        Called automatically after every mutation (add_message, get_responses, complete).
        Returns the log file path."""
```

**Markdown log format** (written to `docs/consultations/{conv_id}.md`):
```markdown
# Consultation: {topic}
- ID: {conv_id}
- Models: gpt-4o, gemini-flash
- Status: active
- Started: 2026-02-23T15:00:00Z
- Updated: 2026-02-23T15:10:00Z

## System Prompt
{system_prompt if any}

---

## Turn 1

**host** (2026-02-23T15:00:00Z):
What are the tradeoffs of X vs Y?

**gpt-4o** (2026-02-23T15:00:05Z):
X is better because...

**gemini-flash** (2026-02-23T15:00:08Z):
Y has advantages in...

---

## Turn 2
...

---

## Summary
{summary if completed}
```

The log is the full conversation in readable form. It's overwritten (not appended) on each update so the file always reflects the complete state. The `docs/consultations/` directory already contains the v1.0 and v1.1 one-shot consultation files, so this is a natural extension.

**Turn flow** (host-directed, not autonomous):
1. `start("Should we use X or Y?", ["gpt-4o", "gemini-flash"])`
2. `add_message(conv_id, "What are the tradeoffs?")`
3. `get_responses(conv_id)` — each model sees full history, responds
4. Host reads, follows up: `add_message(conv_id, "Good point, but what about Z?")`
5. `get_responses(conv_id)` — next round
6. Repeat as needed
7. `extract_event(conv_id, "decision", "We decided X because...")`
8. `complete(conv_id, summary="Decided X, see evt-xxx")`

**Multi-model message history formatting:**
When multiple models respond in the same round, their responses are concatenated with sender labels into a single assistant message for the next API call (APIs require alternating user/assistant):

```
assistant: "[gpt-4o]: UUIDs are better because...\n\n[gemini-flash]: Auto-increment is simpler..."
```

Each model sees what the others said. The host mediates every turn.

**Token management:** Rough `len(text) / 4` estimate before each call. If input exceeds 80k chars (~20k tokens), truncate older messages from the middle, keeping system prompt + first message + last N messages. Insert `[...N earlier messages truncated...]` marker.

### New file: `tests/test_consult.py`

- Test start creates conversation in DB
- Test add_message stores message correctly
- Test get_responses calls providers and saves responses (mock `providers.send_message`)
- Test message history formatting (multi-model concatenation)
- Test complete sets status
- Test extract_event creates Engram event with related_ids containing conv_id
- Test list_conversations filters by status
- Test token truncation with very long histories
- Test _save_log writes markdown to docs/consultations/{conv_id}.md
- Test log contains all messages with sender labels and timestamps
- Test log is updated (overwritten) after each turn

---

## Phase 4: CLI Commands

### `src/engram/cli.py`

Add `consult` command group:

```
engram consult start -t "topic" -m gpt-4o,gemini-flash [-s "system prompt"] [-M "first message"]
engram consult say <conv-id> "message" [-m model1,model2]
engram consult show <conv-id> [-f compact|json]
engram consult ls [--status active|completed] [-f compact|json]
engram consult done <conv-id> [--summary "..."]
engram consult extract <conv-id> -t decision -c "insight text"
```

`start` with `-M` sends the initial message and gets responses in one command (convenience for the common case). Without `-M`, it just creates the conversation.

`say` adds the host message, calls `get_responses`, and prints all new responses.

`show` prints the full conversation with sender labels and timestamps.

### `tests/test_cli.py`

- Test `consult start` creates conversation
- Test `consult say` with mocked providers
- Test `consult show` displays history
- Test `consult ls` lists conversations
- Test `consult done` marks completed

---

## Phase 5: MCP Tools

### `src/engram/mcp_server.py`

Add four tools:

- `start_consultation(topic, models, system_prompt, initial_message)` → conv_id + responses
- `consult_say(conv_id, message, models)` → new responses
- `consult_show(conv_id)` → full conversation
- `consult_done(conv_id, summary)` → confirmation

`extract_event` is not a separate MCP tool — the agent can use the existing `post_event` with `related_ids=[conv_id]` to link events to conversations.

### `tests/test_mcp_server.py`

- Test start_consultation with mocked providers
- Test consult_say returns formatted responses
- Test consult_show returns full history

---

## Phase 6: Dependencies & Version

### `pyproject.toml`

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0"]
consult = ["openai>=1.0", "google-genai>=1.0", "httpx>=0.25", "python-dotenv>=1.0"]
dev = ["pytest>=8.0"]
all = ["mcp>=1.0", "openai>=1.0", "google-genai>=1.0", "httpx>=0.25", "python-dotenv>=1.0"]
```

Note: `google-genai` (not `google-generativeai` which is deprecated). `httpx` for Anthropic API (no separate SDK needed). All already installed in .venv.

### Version bump

- `src/engram/__init__.py`: `__version__ = "1.2.0"`
- `pyproject.toml`: `version = "1.2.0"`

---

## Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `src/engram/providers.py` | New | Multi-model provider abstraction |
| `src/engram/consult.py` | New | ConsultationEngine core logic |
| `src/engram/store.py` | Modify | Schema v3 migration (conversations tables) |
| `src/engram/cli.py` | Modify | `consult` command group |
| `src/engram/mcp_server.py` | Modify | Consultation MCP tools |
| `src/engram/__init__.py` | Modify | Version 1.2.0 |
| `pyproject.toml` | Modify | Version + consult dependencies |
| `tests/test_providers.py` | New | Provider tests (mocked) |
| `tests/test_consult.py` | New | Engine tests (mocked providers) |
| `tests/test_cli.py` | Modify | CLI consultation tests |
| `tests/test_mcp_server.py` | Modify | MCP consultation tests |
| `tests/test_migration.py` | Modify | v2→v3 migration test |

## What I'm NOT Building

- **Model-to-model direct conversation** — host always mediates, preventing runaway API costs
- **Streaming responses** — complete responses only, simpler and sufficient for CLI/MCP
- **Conversation branching** — linear threads only
- **FTS on conversations** — too few to need search; `ls` and `show` are sufficient
- **tmux/process-based UI** — API calls are simpler, testable, and persistent
- **Per-model system prompts** — all models get the same context; diversity comes from the models themselves
- **Retry/backoff** — if an API call fails, it raises; the host retries by calling `say` again

---

## Verification

1. `.venv/bin/pytest tests/ -v` — all existing 127 tests + new tests pass
2. Schema migration: open v1.1 DB with v1.2 code, verify conversations tables created
3. Provider test: mock API calls, verify message formatting for each provider
4. End-to-end (with real API keys):
   ```bash
   engram consult start -t "test topic" -m gpt-4o -M "Hello, what do you think about SQLite?"
   engram consult say <conv-id> "What about PostgreSQL instead?"
   engram consult show <conv-id>
   engram consult extract <conv-id> -t decision -c "Sticking with SQLite"
   engram consult done <conv-id> --summary "Confirmed SQLite is sufficient"
   ```
5. MCP: verify `start_consultation` and `consult_say` work via MCP tool calls
