"""Engram MCP server — exposes Engram tools for Claude Code integration."""

import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from engram.models import Event, EventType
from engram.store import EventStore
from engram.query import QueryEngine, parse_event_types
from engram.briefing import BriefingGenerator
from engram.formatting import (
    format_compact, format_json,
    format_briefing_compact, format_briefing_json,
)

ENGRAM_DIR = ".engram"
DB_NAME = "events.db"

mcp = FastMCP("engram", instructions=(
    "Engram is the project memory system. Use it to record decisions, "
    "discoveries, warnings, and changes. Always run 'briefing' at the "
    "start of a session to understand project context."
))


def _get_store() -> EventStore:
    """Get EventStore for the configured project directory."""
    project_dir = os.environ.get("ENGRAM_PROJECT_DIR", os.getcwd())
    db_path = Path(project_dir) / ENGRAM_DIR / DB_NAME
    if not db_path.exists():
        raise FileNotFoundError(
            f"Engram not initialized in {project_dir}. "
            f"Run 'engram init' in the project directory first."
        )
    store = EventStore(db_path)
    return store


@mcp.tool()
def post_event(
    event_type: str,
    content: str,
    agent_id: str = "claude-code",
    scope: list[str] | None = None,
    related_ids: list[str] | None = None,
    priority: str = "normal",
) -> str:
    """Post an event to the Engram project memory.

    Use this to record:
    - discovery: something important found about the codebase
    - decision: a design choice and its rationale
    - warning: something that should NOT be done, and why
    - mutation: a file change and what/why it was changed
    - outcome: whether a previous action worked or failed

    Args:
        event_type: One of: discovery, decision, warning, mutation, outcome
        content: Description of the event (max 2000 chars)
        agent_id: Identifier for this agent session
        scope: List of file paths this event relates to
        related_ids: List of related event IDs (for linking outcomes to decisions, etc.)
        priority: Event priority: critical, high, normal, low (default: normal)
    """
    store = _get_store()
    try:
        if len(content) > 2000:
            content = content[:2000]

        event = Event(
            id="", timestamp="",
            event_type=EventType(event_type),
            agent_id=agent_id,
            content=content,
            scope=scope,
            related_ids=related_ids,
            priority=priority,
        )
        result = store.insert(event)
        return format_compact([result])
    finally:
        store.close()


@mcp.tool()
def query(
    text: str | None = None,
    event_type: str | None = None,
    scope: str | None = None,
    since: str | None = None,
    agent_id: str | None = None,
    related_to: str | None = None,
    limit: int = 20,
    format: str = "compact",
) -> str:
    """Search Engram events using full-text search and/or structured filters.

    Args:
        text: Full-text search query
        event_type: Filter by type (comma-separated): discovery,decision,warning,mutation,outcome
        scope: Filter by file path prefix
        since: Time filter: "24h", "7d", "2w", or ISO date
        agent_id: Filter by agent identifier
        related_to: Find events linked to this event ID
        limit: Maximum results (default 20)
        format: Output format: "compact" or "json"
    """
    store = _get_store()
    try:
        types = parse_event_types(event_type) if event_type else None
        engine = QueryEngine(store)
        results = engine.execute(
            text=text, event_types=types, agent_id=agent_id,
            scope=scope, since=since, limit=limit, related_to=related_to,
        )
        if format == "json":
            return format_json(results)
        return format_compact(results)
    finally:
        store.close()


@mcp.tool()
def briefing(
    scope: str | None = None,
    since: str | None = None,
    format: str = "compact",
) -> str:
    """Generate a project briefing summarizing recent activity.

    Call this at the start of every session to understand project context.

    Args:
        scope: Filter by file path prefix (e.g., "src/auth")
        since: Time window: "24h", "7d", or ISO date (default: 7 days)
        format: Output format: "compact" or "json"
    """
    store = _get_store()
    try:
        gen = BriefingGenerator(store)
        result = gen.generate(scope=scope, since=since)
        if format == "json":
            return format_briefing_json(result)
        return format_briefing_compact(result)
    finally:
        store.close()


@mcp.tool()
def status() -> str:
    """Get Engram status: total events, database size, last activity.

    Returns project memory statistics as JSON.
    """
    store = _get_store()
    try:
        project_dir = os.environ.get("ENGRAM_PROJECT_DIR", os.getcwd())
        db_path = Path(project_dir) / ENGRAM_DIR / DB_NAME

        return json.dumps({
            "project_name": store.get_meta("project_name") or "unknown",
            "total_events": store.count(),
            "last_activity": store.last_activity(),
            "initialized_at": store.get_meta("initialized_at") or "unknown",
            "db_size_bytes": db_path.stat().st_size,
        }, indent=2)
    finally:
        store.close()


@mcp.tool()
def start_consultation(
    topic: str,
    models: str,
    system_prompt: str | None = None,
    initial_message: str | None = None,
) -> str:
    """Start a multi-turn consultation with external AI models.

    Creates a new conversation where you can discuss design decisions,
    get feedback, and have back-and-forth discussions with other models.

    Args:
        topic: What the consultation is about
        models: Comma-separated model keys: gpt-4o, gemini-flash, claude-sonnet
        system_prompt: Optional context/instructions for all models
        initial_message: If provided, sends this message and returns responses immediately
    """
    from engram.consult import ConsultationEngine
    store = _get_store()
    try:
        project_dir = Path(os.environ.get("ENGRAM_PROJECT_DIR", os.getcwd()))
        engine = ConsultationEngine(store, project_dir=project_dir)
        model_list = [m.strip() for m in models.split(",")]

        conv_id = engine.start(topic, model_list, system_prompt=system_prompt)
        result = f"Started consultation {conv_id}\nTopic: {topic}\nModels: {', '.join(model_list)}"

        if initial_message:
            engine.add_message(conv_id, initial_message)
            responses = engine.get_responses(conv_id)
            result += f"\n\n> {initial_message}\n"
            for r in responses:
                result += f"\n--- {r['sender']} ---\n{r['content']}\n"

        return result
    finally:
        store.close()


@mcp.tool()
def consult_say(
    conv_id: str,
    message: str,
    models: str | None = None,
) -> str:
    """Send a message in an active consultation and get responses from all models.

    Args:
        conv_id: Conversation ID (conv-...)
        message: Your message to the models
        models: Optional comma-separated model keys to override which models respond
    """
    from engram.consult import ConsultationEngine
    store = _get_store()
    try:
        project_dir = Path(os.environ.get("ENGRAM_PROJECT_DIR", os.getcwd()))
        engine = ConsultationEngine(store, project_dir=project_dir)

        engine.add_message(conv_id, message)
        model_list = [m.strip() for m in models.split(",")] if models else None
        responses = engine.get_responses(conv_id, models=model_list)

        result = f"> {message}\n"
        for r in responses:
            result += f"\n--- {r['sender']} ---\n{r['content']}\n"
        return result
    finally:
        store.close()


@mcp.tool()
def consult_show(conv_id: str) -> str:
    """Show the full history of a consultation.

    Args:
        conv_id: Conversation ID (conv-...)
    """
    from engram.consult import ConsultationEngine
    store = _get_store()
    try:
        project_dir = Path(os.environ.get("ENGRAM_PROJECT_DIR", os.getcwd()))
        engine = ConsultationEngine(store, project_dir=project_dir)
        conv = engine.get_conversation(conv_id)

        result = f"# {conv['topic']} [{conv['status']}]\n"
        result += f"ID: {conv['id']} | Models: {', '.join(conv['models'])}\n"
        if conv["system_prompt"]:
            result += f"System: {conv['system_prompt']}\n"
        result += "\n"
        for msg in conv["messages"]:
            result += f"[{msg['sender']}] ({msg['role']}):\n{msg['content']}\n\n"
        if conv["summary"]:
            result += f"Summary: {conv['summary']}\n"
        return result
    finally:
        store.close()


@mcp.tool()
def consult_done(
    conv_id: str,
    summary: str | None = None,
) -> str:
    """Mark a consultation as completed.

    Args:
        conv_id: Conversation ID (conv-...)
        summary: Optional summary of the consultation outcome
    """
    from engram.consult import ConsultationEngine
    store = _get_store()
    try:
        project_dir = Path(os.environ.get("ENGRAM_PROJECT_DIR", os.getcwd()))
        engine = ConsultationEngine(store, project_dir=project_dir)
        engine.complete(conv_id, summary=summary)
        result = f"Completed: {conv_id}"
        if summary:
            result += f"\nSummary: {summary}"
        return result
    finally:
        store.close()


def main():
    """Entry point for engram-mcp console script."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
