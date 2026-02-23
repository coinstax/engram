"""Shared fixtures for Engram tests."""

import pytest
from pathlib import Path

from engram.models import Event, EventType
from engram.store import EventStore


@pytest.fixture
def store(tmp_path):
    """Empty initialized event store."""
    db_path = tmp_path / "events.db"
    s = EventStore(db_path)
    s.initialize()
    yield s
    s.close()


@pytest.fixture
def seeded_store(store):
    """Store with sample events across all types."""
    events = [
        Event(id="", timestamp="2026-02-23T10:00:00+00:00",
              event_type=EventType.DISCOVERY, agent_id="agent-a",
              content="JWT refresh endpoint returns 401 instead of rotating token",
              scope=["src/auth/refresh.ts"]),
        Event(id="", timestamp="2026-02-23T10:05:00+00:00",
              event_type=EventType.DECISION, agent_id="agent-a",
              content="Using bcrypt over argon2 because existing infra uses it",
              scope=["src/auth/hash.ts"]),
        Event(id="", timestamp="2026-02-23T10:10:00+00:00",
              event_type=EventType.WARNING, agent_id="agent-b",
              content="Don't modify user_sessions table — migration pending",
              scope=["src/db/schema.sql"]),
        Event(id="", timestamp="2026-02-23T10:15:00+00:00",
              event_type=EventType.MUTATION, agent_id="agent-a",
              content="Refactored JWT refresh logic to use rotating tokens",
              scope=["src/auth/refresh.ts", "src/auth/middleware.ts"]),
        Event(id="", timestamp="2026-02-23T10:20:00+00:00",
              event_type=EventType.OUTCOME, agent_id="agent-a",
              content="Fix worked for JWT refresh but broke session invalidation",
              scope=["src/auth/refresh.ts"]),
        Event(id="", timestamp="2026-02-23T10:25:00+00:00",
              event_type=EventType.MUTATION, agent_id="agent-b",
              content="Added email validation to user registration endpoint",
              scope=["src/api/users.ts"]),
        Event(id="", timestamp="2026-02-23T10:30:00+00:00",
              event_type=EventType.DISCOVERY, agent_id="agent-b",
              content="Database connection pool maxes out at 20 under load",
              scope=["src/db/pool.ts"]),
        Event(id="", timestamp="2026-02-23T10:35:00+00:00",
              event_type=EventType.WARNING, agent_id="agent-a",
              content="Rate limiter config is hardcoded, needs env var",
              scope=["src/api/middleware.ts"]),
    ]
    store.insert_batch(events)
    return store
