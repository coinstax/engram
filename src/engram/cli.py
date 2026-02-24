"""Engram CLI — project memory for AI coding agents."""

import os
import sys
from pathlib import Path

import click

from engram.models import Event, EventType
from engram.store import EventStore
from engram.query import QueryEngine, parse_event_types
from engram.briefing import BriefingGenerator
from engram.bootstrap import GitBootstrapper
from engram.formatting import (
    format_compact, format_json,
    format_briefing_compact, format_briefing_json,
)

ENGRAM_DIR = ".engram"
DB_NAME = "events.db"

CLAUDE_MD_SNIPPET = """
## Project Memory (Engram)
This project uses Engram for persistent memory across agent sessions.
- Before starting work: `engram briefing`
- After important decisions: `engram post -t decision -c "rationale..." -s path/to/file`
- To leave warnings: `engram post -t warning -c "don't do X because..." -s path/to/file`
- After discovering something: `engram post -t discovery -c "found that..."`
- To search history: `engram query "search terms"`
""".strip()


def _resolve_project(project: str) -> Path:
    """Resolve project directory."""
    return Path(project).resolve()


def _auto_write_claude_md(project: Path) -> str:
    """Auto-write Engram section to CLAUDE.md. Returns status message."""
    claude_md = project / "CLAUDE.md"
    marker = "## Project Memory (Engram)"

    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        if marker in content:
            return "CLAUDE.md already has Engram section."
        with claude_md.open("a", encoding="utf-8") as f:
            f.write("\n\n" + CLAUDE_MD_SNIPPET + "\n")
        return "Appended Engram section to CLAUDE.md."
    else:
        claude_md.write_text(CLAUDE_MD_SNIPPET + "\n", encoding="utf-8")
        return "Created CLAUDE.md with Engram section."


def _get_store(project: Path) -> EventStore:
    """Get an initialized EventStore for the project."""
    db_path = project / ENGRAM_DIR / DB_NAME
    if not db_path.exists():
        click.echo(f"Error: Engram not initialized in {project}", err=True)
        click.echo("Run 'engram init' first.", err=True)
        sys.exit(1)
    store = EventStore(db_path)
    return store


@click.group()
@click.option("--project", "-p", default=".", help="Project directory")
@click.pass_context
def cli(ctx, project):
    """Engram — project memory for AI coding agents."""
    ctx.ensure_object(dict)
    ctx.obj["project"] = _resolve_project(project)


@cli.command()
@click.option("--max-commits", default=100, help="Max git commits to mine")
@click.pass_context
def init(ctx, max_commits):
    """Initialize Engram in this project. Seeds from git history."""
    project = ctx.obj["project"]
    engram_dir = project / ENGRAM_DIR

    if engram_dir.exists():
        click.echo(f"Engram already initialized in {project}")
        return

    engram_dir.mkdir(parents=True)
    db_path = engram_dir / DB_NAME
    store = EventStore(db_path)
    store.initialize()

    # Detect project name and bootstrap from git
    event_count = 0
    try:
        bootstrapper = GitBootstrapper(project)
        project_name = bootstrapper.detect_project_name()
        store.set_meta("project_name", project_name)

        events = bootstrapper.mine_history(max_commits=max_commits)
        if events:
            event_count = store.insert_batch(events)
    except ValueError:
        # Not a git repo — still initialize, just without seed data
        project_name = project.name
        store.set_meta("project_name", project_name)

    from datetime import datetime, timezone
    store.set_meta("initialized_at", datetime.now(timezone.utc).isoformat())

    click.echo(f"Engram initialized for '{project_name}'. {event_count} events seeded from git history.")

    # Auto-write CLAUDE.md
    claude_msg = _auto_write_claude_md(project)
    click.echo(claude_msg)
    click.echo("Run 'engram hooks install' to enable passive observation via Claude Code hooks.")

    store.close()


@cli.command()
@click.option("--type", "-t", "event_type", required=True,
              type=click.Choice(["discovery", "decision", "warning", "mutation", "outcome"]))
@click.option("--content", "-c", required=True, help="Event content (max 2000 chars)")
@click.option("--scope", "-s", multiple=True, help="File path(s)")
@click.option("--agent", "-a", default=None, help="Agent identifier")
@click.option("--related", "-r", multiple=True, help="Related event ID(s)")
@click.option("--priority", "-p", default="normal",
              type=click.Choice(["critical", "high", "normal", "low"]),
              help="Event priority (default: normal)")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def post(ctx, event_type, content, scope, agent, related, priority, fmt):
    """Post an event to the store."""
    project = ctx.obj["project"]
    store = _get_store(project)

    if len(content) > 2000:
        click.echo("Error: Content exceeds 2000 character limit.", err=True)
        sys.exit(1)

    agent_id = agent or os.environ.get("ENGRAM_AGENT_ID", "cli")
    scope_list = list(scope) if scope else None
    related_list = list(related) if related else None

    event = Event(
        id="", timestamp="",
        event_type=EventType(event_type),
        agent_id=agent_id,
        content=content,
        scope=scope_list,
        related_ids=related_list,
        priority=priority,
    )
    result = store.insert(event)

    if fmt == "json":
        click.echo(format_json([result]))
    else:
        click.echo(format_compact([result]))

    store.close()


@cli.command()
@click.argument("text", required=False)
@click.option("--type", "-t", "event_type", default=None, help="Event type(s), comma-separated")
@click.option("--scope", "-s", default=None, help="Scope path prefix")
@click.option("--since", default=None, help="Time filter: 24h, 7d, or ISO date")
@click.option("--agent", "-a", default=None, help="Filter by agent")
@click.option("--related-to", default=None, help="Find events related to this event ID")
@click.option("--limit", "-n", default=50, help="Max results")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def query(ctx, text, event_type, scope, since, agent, related_to, limit, fmt):
    """Query events. Supports FTS text and/or structured filters."""
    project = ctx.obj["project"]
    store = _get_store(project)

    types = parse_event_types(event_type) if event_type else None
    engine = QueryEngine(store)
    results = engine.execute(
        text=text, event_types=types, agent_id=agent,
        scope=scope, since=since, limit=limit, related_to=related_to,
    )

    if fmt == "json":
        click.echo(format_json(results))
    else:
        click.echo(format_compact(results))

    store.close()


@cli.command()
@click.option("--scope", "-s", default=None, help="Scope path prefix")
@click.option("--since", default=None, help="Time filter: 24h, 7d, or ISO date")
@click.option("--focus", default=None, help="Focus path for scope-aware ranking")
@click.option("--resolved-window", default=48, type=int,
              help="Hours to show recently resolved events (default: 48)")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def briefing(ctx, scope, since, focus, resolved_window, fmt):
    """Generate a project briefing."""
    project = ctx.obj["project"]
    store = _get_store(project)

    gen = BriefingGenerator(store)
    result = gen.generate(scope=scope, since=since, focus=focus,
                          resolved_window_hours=resolved_window)

    if fmt == "json":
        click.echo(format_briefing_json(result))
    else:
        click.echo(format_briefing_compact(result))

    store.close()


@cli.command()
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def status(ctx, fmt):
    """Show Engram status."""
    project = ctx.obj["project"]
    store = _get_store(project)

    total = store.count()
    last = store.last_activity()
    project_name = store.get_meta("project_name") or "unknown"
    initialized = store.get_meta("initialized_at") or "unknown"
    db_size = (project / ENGRAM_DIR / DB_NAME).stat().st_size

    if fmt == "json":
        import json
        click.echo(json.dumps({
            "project_name": project_name,
            "total_events": total,
            "last_activity": last,
            "initialized_at": initialized,
            "db_size_bytes": db_size,
        }, indent=2))
    else:
        click.echo(f"Project:      {project_name}")
        click.echo(f"Events:       {total}")
        click.echo(f"Last activity: {last or 'none'}")
        click.echo(f"Initialized:  {initialized}")
        click.echo(f"DB size:      {db_size:,} bytes")

    store.close()


@cli.command()
@click.option("--max-age", default=90, help="Archive events older than N days (default: 90)")
@click.option("--dry-run", is_flag=True, help="Show what would be archived without doing it")
@click.pass_context
def gc(ctx, max_age, dry_run):
    """Archive old events to reduce database size.

    Only mutations and outcomes are archived. Warnings and decisions
    are always preserved regardless of age.
    """
    from engram.gc import GarbageCollector
    project = ctx.obj["project"]
    store = _get_store(project)

    collector = GarbageCollector(store, project / ENGRAM_DIR)
    result = collector.collect(max_age_days=max_age, dry_run=dry_run)

    if dry_run:
        click.echo(f"Would archive {result['would_archive']} events older than {max_age} days.")
    elif result["archived"] == 0:
        click.echo(f"No events to archive (cutoff: {max_age} days).")
    else:
        click.echo(f"Archived {result['archived']} events to {result['archive_path']}.")

    store.close()


# --- Event lifecycle commands ---

@cli.command()
@click.argument("event_id")
@click.option("--reason", "-r", required=True, help="Why this event is resolved")
@click.pass_context
def resolve(ctx, event_id, reason):
    """Resolve an active event (e.g., a warning that's been addressed)."""
    project = ctx.obj["project"]
    store = _get_store(project)

    try:
        event = store.get_event(event_id)
        if not event:
            click.echo(f"Error: Event not found: {event_id}", err=True)
            sys.exit(1)
        if event.status != "active":
            click.echo(f"Error: Event {event_id} is {event.status}, not active.", err=True)
            sys.exit(1)

        updated = store.update_status(event_id, "resolved", resolved_reason=reason)
        click.echo(f"Resolved: {event_id}")
        click.echo(f"Reason: {reason}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


@cli.command()
@click.argument("event_id")
@click.option("--by", "new_event_id", required=True, help="ID of the superseding event")
@click.pass_context
def supersede(ctx, event_id, new_event_id):
    """Mark an event as superseded by a newer event."""
    project = ctx.obj["project"]
    store = _get_store(project)

    try:
        old = store.get_event(event_id)
        if not old:
            click.echo(f"Error: Event not found: {event_id}", err=True)
            sys.exit(1)
        new = store.get_event(new_event_id)
        if not new:
            click.echo(f"Error: Superseding event not found: {new_event_id}", err=True)
            sys.exit(1)
        if old.status != "active":
            click.echo(f"Error: Event {event_id} is {old.status}, not active.", err=True)
            sys.exit(1)

        store.update_status(event_id, "superseded", superseded_by=new_event_id)
        click.echo(f"Superseded: {event_id} -> {new_event_id}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


@cli.command()
@click.argument("event_id")
@click.pass_context
def reopen(ctx, event_id):
    """Reopen a resolved event (set back to active). Superseded events cannot be reopened."""
    project = ctx.obj["project"]
    store = _get_store(project)

    try:
        event = store.get_event(event_id)
        if not event:
            click.echo(f"Error: Event not found: {event_id}", err=True)
            sys.exit(1)
        if event.status == "superseded":
            click.echo(f"Error: Superseded events cannot be reopened. Event {event_id} was superseded by {event.superseded_by}.", err=True)
            sys.exit(1)
        if event.status == "active":
            click.echo(f"Event {event_id} is already active.", err=True)
            sys.exit(1)

        store.update_status(event_id, "active")
        click.echo(f"Reopened: {event_id}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


# --- Consultation commands ---

@cli.group()
@click.pass_context
def consult(ctx):
    """Multi-turn AI consultations with external models."""
    pass


@consult.command("start")
@click.option("--topic", "-t", required=True, help="Conversation topic")
@click.option("--models", "-m", required=True, help="Comma-separated model keys (gpt-4o,gemini-flash,claude-sonnet)")
@click.option("--system", "-s", default=None, help="System prompt for all models")
@click.option("--context/--no-context", default=True, help="Auto-assemble project context (default: on)")
@click.option("--message", "-M", default=None, help="Initial message (sends and gets responses immediately)")
@click.pass_context
def consult_start(ctx, topic, models, system, context, message):
    """Start a new consultation."""
    from engram.consult import ConsultationEngine
    from engram.context import ContextAssembler
    project = ctx.obj["project"]
    store = _get_store(project)

    model_list = [m.strip() for m in models.split(",")]
    engine = ConsultationEngine(store, project_dir=project)

    # Auto-assemble project context
    system_prompt = system
    if context:
        assembler = ContextAssembler(store, project_dir=project)
        auto_context = assembler.assemble_for_consultation(
            topic=topic, models=model_list,
        )
        if system:
            system_prompt = f"{auto_context}\n\n---\n\n## Additional Instructions\n{system}"
        else:
            system_prompt = auto_context
        summary = assembler.context_summary()
        click.echo(f"Auto-context: {len(system_prompt)} chars ({summary})")

    try:
        conv_id = engine.start(topic, model_list, system_prompt=system_prompt)
        click.echo(f"Started consultation: {conv_id}")
        click.echo(f"Topic: {topic}")
        click.echo(f"Models: {', '.join(model_list)}")

        if message:
            engine.add_message(conv_id, message)
            click.echo(f"\n> {message}\n")
            responses = engine.get_responses(conv_id)
            for r in responses:
                click.echo(f"--- {r['sender']} ---")
                click.echo(r["content"])
                click.echo()
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


@consult.command("say")
@click.argument("conv_id")
@click.argument("message")
@click.option("--models", "-m", default=None, help="Override models for this turn")
@click.pass_context
def consult_say(ctx, conv_id, message, models):
    """Send a message and get responses."""
    from engram.consult import ConsultationEngine
    project = ctx.obj["project"]
    store = _get_store(project)
    engine = ConsultationEngine(store, project_dir=project)

    try:
        engine.add_message(conv_id, message)
        click.echo(f"> {message}\n")

        model_list = [m.strip() for m in models.split(",")] if models else None
        responses = engine.get_responses(conv_id, models=model_list)
        for r in responses:
            click.echo(f"--- {r['sender']} ---")
            click.echo(r["content"])
            click.echo()
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


@consult.command("show")
@click.argument("conv_id")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def consult_show(ctx, conv_id, fmt):
    """Show full conversation history."""
    import json as _json
    from engram.consult import ConsultationEngine
    project = ctx.obj["project"]
    store = _get_store(project)
    engine = ConsultationEngine(store, project_dir=project)

    try:
        conv = engine.get_conversation(conv_id)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if fmt == "json":
        click.echo(_json.dumps(conv, indent=2))
    else:
        click.echo(f"# {conv['topic']} [{conv['status']}]")
        click.echo(f"ID: {conv['id']} | Models: {', '.join(conv['models'])}")
        if conv["system_prompt"]:
            click.echo(f"System: {conv['system_prompt']}")
        click.echo()
        for msg in conv["messages"]:
            click.echo(f"[{msg['sender']}] ({msg['role']}):")
            click.echo(msg["content"])
            click.echo()
        if conv["summary"]:
            click.echo(f"Summary: {conv['summary']}")

    store.close()


@consult.command("ls")
@click.option("--status", default=None, type=click.Choice(["active", "paused", "completed"]))
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def consult_ls(ctx, status, fmt):
    """List consultations."""
    import json as _json
    from engram.consult import ConsultationEngine
    project = ctx.obj["project"]
    store = _get_store(project)
    engine = ConsultationEngine(store, project_dir=project)

    convs = engine.list_conversations(status=status)

    if fmt == "json":
        click.echo(_json.dumps(convs, indent=2))
    else:
        if not convs:
            click.echo("(no consultations)")
        else:
            for c in convs:
                click.echo(
                    f"{c['id']} [{c['status']}] {c['topic']} "
                    f"({c['message_count']} msgs, {', '.join(c['models'])})"
                )

    store.close()


@consult.command("done")
@click.argument("conv_id")
@click.option("--summary", default=None, help="Conversation summary")
@click.pass_context
def consult_done(ctx, conv_id, summary):
    """Mark a consultation as completed."""
    from engram.consult import ConsultationEngine
    project = ctx.obj["project"]
    store = _get_store(project)
    engine = ConsultationEngine(store, project_dir=project)

    try:
        result = engine.complete(conv_id, summary=summary)
        click.echo(f"Completed: {conv_id}")
        if summary:
            click.echo(f"Summary: {summary}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


@consult.command("extract")
@click.argument("conv_id")
@click.option("--type", "-t", "event_type", required=True,
              type=click.Choice(["discovery", "decision", "warning"]))
@click.option("--content", "-c", required=True, help="Event content to extract")
@click.pass_context
def consult_extract(ctx, conv_id, event_type, content):
    """Extract an Engram event from a consultation."""
    from engram.consult import ConsultationEngine
    project = ctx.obj["project"]
    store = _get_store(project)
    engine = ConsultationEngine(store, project_dir=project)

    try:
        event_id = engine.extract_event(conv_id, event_type, content)
        click.echo(f"Extracted [{event_type}] {event_id} linked to {conv_id}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        store.close()


# --- Hook management (user-facing) ---

@cli.group()
@click.pass_context
def hooks(ctx):
    """Manage Claude Code hooks for passive observation."""
    pass


@hooks.command()
@click.pass_context
def install(ctx):
    """Install Claude Code hooks for automatic activity capture."""
    from engram.hooks import install_hooks
    project = ctx.obj["project"]
    result = install_hooks(project)
    click.echo(result["message"])


# --- Hook handlers (internal, called by Claude Code) ---

@cli.group(hidden=True)
@click.pass_context
def hook(ctx):
    """Internal hook handlers invoked by Claude Code."""
    pass


@hook.command("post-tool-use")
@click.pass_context
def hook_post_tool_use(ctx):
    """Handle PostToolUse hook. Reads JSON from stdin."""
    import json as _json
    data = _json.load(sys.stdin)
    project_dir = Path(data.get("cwd", str(ctx.obj["project"]))).resolve()

    from engram.hooks import handle_post_tool_use
    handle_post_tool_use(data, project_dir)


@hook.command("session-start")
@click.pass_context
def hook_session_start(ctx):
    """Handle SessionStart hook. Outputs briefing to stdout."""
    import json as _json
    data = _json.load(sys.stdin)
    project_dir = Path(data.get("cwd", str(ctx.obj["project"]))).resolve()

    from engram.hooks import handle_session_start
    output = handle_session_start(data, project_dir)
    if output:
        click.echo(output)
