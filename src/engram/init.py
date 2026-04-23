"""Shared Engram initialization logic — used by CLI and SessionStart hook."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from engram.bootstrap import GitBootstrapper
from engram.store import EventStore

ENGRAM_DIR = ".engram"
DB_NAME = "events.db"


@dataclass
class InitResult:
    """Outcome of perform_init()."""
    project_name: str
    events_seeded: int
    already_initialized: bool


def perform_init(project_dir: Path, *, max_commits: int = 100) -> InitResult:
    """Initialize Engram in a project directory. Idempotent.

    Creates `.engram/events.db`, sets schema, bootstraps from git history
    (when the project is a git repo), and records `project_name` +
    `initialized_at` meta. Returns `already_initialized=True` without
    further side effects when the DB already exists.

    NOTE: does NOT modify CLAUDE.md. Callers that want the CLAUDE.md
    append (e.g. `engram init` CLI) should invoke _auto_write_claude_md
    themselves after calling this helper.
    """
    engram_dir = project_dir / ENGRAM_DIR
    db_path = engram_dir / DB_NAME

    if db_path.exists():
        store = EventStore(db_path)
        try:
            project_name = store.get_meta("project_name") or project_dir.name
        finally:
            store.close()
        return InitResult(
            project_name=project_name,
            events_seeded=0,
            already_initialized=True,
        )

    engram_dir.mkdir(parents=True, exist_ok=True)
    store = EventStore(db_path)
    try:
        store.initialize()

        event_count = 0
        try:
            bootstrapper = GitBootstrapper(project_dir)
        except ValueError:
            # Not a git repo — still initialize, just without seed data.
            project_name = project_dir.name
        else:
            project_name = bootstrapper.detect_project_name()
            events = bootstrapper.mine_history(max_commits=max_commits)
            if events:
                event_count = store.insert_batch(events)

        store.set_meta("project_name", project_name)
        store.set_meta("initialized_at", datetime.now(timezone.utc).isoformat())
    finally:
        store.close()

    return InitResult(
        project_name=project_name,
        events_seeded=event_count,
        already_initialized=False,
    )
