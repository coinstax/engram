"""Shared fixtures for Engram tests."""

from datetime import datetime, timedelta, timezone

import pytest
from pathlib import Path

from engram.models import Event, EventType
from engram.store import EventStore


# Anchor 3 hours before now so fixtures stay inside the default 7-day
# briefing window without depending on absolute calendar dates.
_TEST_ANCHOR = datetime.now(timezone.utc) - timedelta(hours=3)


def ts_offset(minutes: int = 0) -> str:
    """Return an ISO-8601 UTC timestamp `minutes` after the test anchor."""
    return (_TEST_ANCHOR + timedelta(minutes=minutes)).isoformat()


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
        Event(id="", timestamp=ts_offset(0),
              event_type=EventType.DISCOVERY, agent_id="agent-a",
              content="JWT refresh endpoint returns 401 instead of rotating token",
              scope=["src/auth/refresh.ts"]),
        Event(id="", timestamp=ts_offset(5),
              event_type=EventType.DECISION, agent_id="agent-a",
              content="Using bcrypt over argon2 because existing infra uses it",
              scope=["src/auth/hash.ts"]),
        Event(id="", timestamp=ts_offset(10),
              event_type=EventType.WARNING, agent_id="agent-b",
              content="Don't modify user_sessions table — migration pending",
              scope=["src/db/schema.sql"]),
        Event(id="", timestamp=ts_offset(15),
              event_type=EventType.MUTATION, agent_id="agent-a",
              content="Refactored JWT refresh logic to use rotating tokens",
              scope=["src/auth/refresh.ts", "src/auth/middleware.ts"]),
        Event(id="", timestamp=ts_offset(20),
              event_type=EventType.OUTCOME, agent_id="agent-a",
              content="Fix worked for JWT refresh but broke session invalidation",
              scope=["src/auth/refresh.ts"]),
        Event(id="", timestamp=ts_offset(25),
              event_type=EventType.MUTATION, agent_id="agent-b",
              content="Added email validation to user registration endpoint",
              scope=["src/api/users.ts"]),
        Event(id="", timestamp=ts_offset(30),
              event_type=EventType.DISCOVERY, agent_id="agent-b",
              content="Database connection pool maxes out at 20 under load",
              scope=["src/db/pool.ts"]),
        Event(id="", timestamp=ts_offset(35),
              event_type=EventType.WARNING, agent_id="agent-a",
              content="Rate limiter config is hardcoded, needs env var",
              scope=["src/api/middleware.ts"]),
    ]
    store.insert_batch(events)
    return store
