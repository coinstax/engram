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
    click.echo()
    click.echo("Add this to your CLAUDE.md:")
    click.echo("---")
    click.echo(CLAUDE_MD_SNIPPET)
    click.echo("---")

    store.close()


@cli.command()
@click.option("--type", "-t", "event_type", required=True,
              type=click.Choice(["discovery", "decision", "warning", "mutation", "outcome"]))
@click.option("--content", "-c", required=True, help="Event content (max 2000 chars)")
@click.option("--scope", "-s", multiple=True, help="File path(s)")
@click.option("--agent", "-a", default=None, help="Agent identifier")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def post(ctx, event_type, content, scope, agent, fmt):
    """Post an event to the store."""
    project = ctx.obj["project"]
    store = _get_store(project)

    if len(content) > 2000:
        click.echo("Error: Content exceeds 2000 character limit.", err=True)
        sys.exit(1)

    agent_id = agent or os.environ.get("ENGRAM_AGENT_ID", "cli")
    scope_list = list(scope) if scope else None

    event = Event(
        id="", timestamp="",
        event_type=EventType(event_type),
        agent_id=agent_id,
        content=content,
        scope=scope_list,
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
@click.option("--limit", "-n", default=50, help="Max results")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def query(ctx, text, event_type, scope, since, agent, limit, fmt):
    """Query events. Supports FTS text and/or structured filters."""
    project = ctx.obj["project"]
    store = _get_store(project)

    types = parse_event_types(event_type) if event_type else None
    engine = QueryEngine(store)
    results = engine.execute(
        text=text, event_types=types, agent_id=agent,
        scope=scope, since=since, limit=limit,
    )

    if fmt == "json":
        click.echo(format_json(results))
    else:
        click.echo(format_compact(results))

    store.close()


@cli.command()
@click.option("--scope", "-s", default=None, help="Scope path prefix")
@click.option("--since", default=None, help="Time filter: 24h, 7d, or ISO date")
@click.option("--format", "-f", "fmt", default="compact",
              type=click.Choice(["compact", "json"]))
@click.pass_context
def briefing(ctx, scope, since, fmt):
    """Generate a project briefing."""
    project = ctx.obj["project"]
    store = _get_store(project)

    gen = BriefingGenerator(store)
    result = gen.generate(scope=scope, since=since)

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
