"""ConsultationEngine — multi-turn AI conversations with persistent storage."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from engram.models import Event, EventType
from engram.store import EventStore
from engram import providers


# Max chars before truncating older messages (~20k tokens)
MAX_INPUT_CHARS = 80_000

# Max file size for file-based consultations (leaves headroom under MAX_INPUT_CHARS)
MAX_FILE_CHARS = 60_000


def read_file_for_consultation(file_path: str | Path) -> tuple[str, str]:
    """Read a file and return (filename, content).

    Raises ValueError if file not found, too large, or not valid UTF-8.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        raise ValueError(f"Cannot read file: {e}") from e

    if len(content) > MAX_FILE_CHARS:
        raise ValueError(
            f"File too large: {len(content)} chars (max {MAX_FILE_CHARS}). "
            f"Consider extracting the relevant section."
        )

    return path.name, content


def format_file_message(
    filename: str,
    content: str,
    prompt: str | None = None,
) -> str:
    """Format file content into an initial consultation message.

    Args:
        filename: Name of the file (for display and syntax detection)
        content: Full file text
        prompt: Custom prompt/question. Defaults to a general review request.
    """
    prompt = prompt or (
        "Review this file and provide feedback. "
        "Note any issues, suggest improvements, and highlight what works well."
    )

    suffix = Path(filename).suffix.lstrip(".")
    lang = suffix if suffix else ""

    return f"{prompt}\n\n**File: `{filename}`**\n\n```{lang}\n{content}\n```"


class ConsultationEngine:
    """Manages multi-turn conversations with external AI models."""

    def __init__(self, store: EventStore, project_dir: Path | None = None):
        self.store = store
        self.project_dir = project_dir or Path.cwd()

    @staticmethod
    def _generate_id() -> str:
        return f"conv-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(
        self,
        topic: str,
        models: list[str],
        system_prompt: str | None = None,
    ) -> str:
        """Create a new conversation. Returns conv_id."""
        # Validate models
        for m in models:
            if m not in providers.MODELS:
                raise ValueError(
                    f"Unknown model: {m}. Available: {list(providers.MODELS.keys())}"
                )

        conv_id = self._generate_id()
        now = self._now_iso()

        with self.store.conn:
            self.store.conn.execute(
                "INSERT INTO conversations (id, topic, status, models, system_prompt, created_at, updated_at) "
                "VALUES (?, ?, 'active', ?, ?, ?, ?)",
                (conv_id, topic, json.dumps(models), system_prompt, now, now),
            )

        self._save_log(conv_id)
        return conv_id

    def add_message(self, conv_id: str, content: str, sender: str = "host") -> dict:
        """Add a host message to the conversation. Returns message dict."""
        conv = self._get_conv_row(conv_id)
        if conv["status"] != "active":
            raise ValueError(f"Conversation {conv_id} is {conv['status']}, not active.")

        now = self._now_iso()
        with self.store.conn:
            cursor = self.store.conn.execute(
                "INSERT INTO conversation_messages (conv_id, role, sender, content, created_at) "
                "VALUES (?, 'user', ?, ?, ?)",
                (conv_id, sender, content, now),
            )
            self.store.conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conv_id),
            )

        msg = {
            "id": cursor.lastrowid,
            "conv_id": conv_id,
            "role": "user",
            "sender": sender,
            "content": content,
            "created_at": now,
        }
        self._save_log(conv_id)
        return msg

    def get_responses(self, conv_id: str, models: list[str] | None = None) -> list[dict]:
        """Call each model with full history, save responses. Returns new responses."""
        conv = self._get_conv_row(conv_id)
        if conv["status"] != "active":
            raise ValueError(f"Conversation {conv_id} is {conv['status']}, not active.")

        conv_models = json.loads(conv["models"])
        target_models = models or conv_models
        system_prompt = conv["system_prompt"]

        # Build message history for API calls
        api_messages = self._build_api_messages(conv_id)

        responses = []
        now = self._now_iso()

        for model_key in target_models:
            try:
                response_text = providers.send_message(
                    model_key, api_messages, system_prompt
                )
            except Exception as e:
                response_text = f"[Error from {model_key}: {e}]"

            with self.store.conn:
                cursor = self.store.conn.execute(
                    "INSERT INTO conversation_messages (conv_id, role, sender, content, created_at) "
                    "VALUES (?, 'assistant', ?, ?, ?)",
                    (conv_id, model_key, response_text, now),
                )
                self.store.conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conv_id),
                )

            responses.append({
                "id": cursor.lastrowid,
                "conv_id": conv_id,
                "role": "assistant",
                "sender": model_key,
                "content": response_text,
                "created_at": now,
            })

        self._save_log(conv_id)
        return responses

    def get_conversation(self, conv_id: str) -> dict:
        """Return full conversation with metadata + messages."""
        conv = self._get_conv_row(conv_id)
        messages = self.store.conn.execute(
            "SELECT * FROM conversation_messages WHERE conv_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()

        return {
            "id": conv["id"],
            "topic": conv["topic"],
            "status": conv["status"],
            "models": json.loads(conv["models"]),
            "system_prompt": conv["system_prompt"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "summary": conv["summary"],
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "sender": m["sender"],
                    "content": m["content"],
                    "created_at": m["created_at"],
                }
                for m in messages
            ],
        }

    def list_conversations(self, status: str | None = None, limit: int = 20) -> list[dict]:
        """List conversations, optionally filtered by status."""
        if status:
            rows = self.store.conn.execute(
                "SELECT * FROM conversations WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.store.conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [
            {
                "id": r["id"],
                "topic": r["topic"],
                "status": r["status"],
                "models": json.loads(r["models"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "summary": r["summary"],
                "message_count": self.store.conn.execute(
                    "SELECT COUNT(*) as cnt FROM conversation_messages WHERE conv_id = ?",
                    (r["id"],),
                ).fetchone()["cnt"],
            }
            for r in rows
        ]

    def complete(self, conv_id: str, summary: str | None = None) -> dict:
        """Mark conversation as completed, optionally store summary."""
        conv = self._get_conv_row(conv_id)
        now = self._now_iso()

        with self.store.conn:
            self.store.conn.execute(
                "UPDATE conversations SET status = 'completed', summary = ?, updated_at = ? WHERE id = ?",
                (summary, now, conv_id),
            )

        self._save_log(conv_id)
        return self.get_conversation(conv_id)

    def extract_event(self, conv_id: str, event_type: str, content: str) -> str:
        """Post an Engram event linked to this conversation via related_ids. Returns event ID."""
        self._get_conv_row(conv_id)  # validate exists

        event = Event(
            id="", timestamp="",
            event_type=EventType(event_type),
            agent_id="consultation",
            content=content,
            related_ids=[conv_id],
        )
        result = self.store.insert(event)
        return result.id

    def _get_conv_row(self, conv_id: str):
        """Fetch conversation row, raise if not found."""
        row = self.store.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Conversation not found: {conv_id}")
        return row

    def _build_api_messages(self, conv_id: str) -> list[dict]:
        """Build alternating user/assistant messages from conversation history.

        When multiple models respond in the same round, their responses are
        concatenated with sender labels into a single assistant message.
        """
        rows = self.store.conn.execute(
            "SELECT * FROM conversation_messages WHERE conv_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()

        api_messages = []
        pending_assistant: list[str] = []

        for row in rows:
            if row["role"] == "user":
                # Flush any pending assistant messages
                if pending_assistant:
                    api_messages.append({
                        "role": "assistant",
                        "content": "\n\n".join(pending_assistant),
                    })
                    pending_assistant = []
                api_messages.append({
                    "role": "user",
                    "content": row["content"],
                })
            elif row["role"] == "assistant":
                pending_assistant.append(
                    f"[{row['sender']}]: {row['content']}"
                )

        # Flush remaining assistant messages
        if pending_assistant:
            api_messages.append({
                "role": "assistant",
                "content": "\n\n".join(pending_assistant),
            })

        # Token management: truncate if too long
        api_messages = self._truncate_if_needed(api_messages)

        return api_messages

    def _truncate_if_needed(self, messages: list[dict]) -> list[dict]:
        """Truncate older messages from the middle if input exceeds MAX_INPUT_CHARS."""
        total_chars = sum(len(m["content"]) for m in messages)
        if total_chars <= MAX_INPUT_CHARS or len(messages) <= 2:
            return messages

        # Keep first message + last N messages, truncate middle
        first = messages[0]
        remaining = messages[1:]

        # Remove from the front of remaining until under limit
        while len(remaining) > 1:
            total_chars = len(first["content"]) + sum(len(m["content"]) for m in remaining)
            if total_chars <= MAX_INPUT_CHARS:
                break
            remaining.pop(0)

        truncated_count = len(messages) - 1 - len(remaining)
        if truncated_count > 0:
            marker = {
                "role": "user",
                "content": f"[...{truncated_count} earlier messages truncated...]",
            }
            return [first, marker] + remaining

        return [first] + remaining

    def _save_log(self, conv_id: str) -> Path:
        """Write/overwrite markdown log to docs/consultations/{conv_id}.md."""
        conv = self.get_conversation(conv_id)

        log_dir = self.project_dir / "docs" / "consultations"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{conv_id}.md"

        lines = [
            f"# Consultation: {conv['topic']}",
            f"- ID: {conv['id']}",
            f"- Models: {', '.join(conv['models'])}",
            f"- Status: {conv['status']}",
            f"- Started: {conv['created_at']}",
            f"- Updated: {conv['updated_at']}",
        ]

        if conv["system_prompt"]:
            lines.extend(["", "## System Prompt", conv["system_prompt"]])

        # Group messages into turns (a turn = one user message + all assistant responses)
        turn_num = 0
        messages = conv["messages"]
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg["role"] == "user":
                turn_num += 1
                lines.extend(["", "---", "", f"## Turn {turn_num}", ""])
                lines.append(f"**{msg['sender']}** ({msg['created_at']}):")
                lines.append(msg["content"])

                # Collect following assistant messages
                i += 1
                while i < len(messages) and messages[i]["role"] == "assistant":
                    a = messages[i]
                    lines.append("")
                    lines.append(f"**{a['sender']}** ({a['created_at']}):")
                    lines.append(a["content"])
                    i += 1
            else:
                i += 1

        if conv["summary"]:
            lines.extend(["", "---", "", "## Summary", conv["summary"]])

        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log_path
