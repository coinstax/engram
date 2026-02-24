"""Query engine with relative time parsing and filter normalization."""

import re
from datetime import datetime, timedelta, timezone

from engram.models import Event, EventType, QueryFilter
from engram.store import EventStore

RELATIVE_TIME_PATTERN = re.compile(r"^(\d+)(m|h|d|w)$")

TIME_MULTIPLIERS = {
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}


def parse_since(since: str) -> str:
    """Convert a relative or absolute time string to an ISO timestamp.

    Accepts:
        "30m", "24h", "7d", "2w" — relative to now
        "2026-02-20" — date (assumes start of day UTC)
        "2026-02-20T14:00:00" — ISO timestamp (passed through)
    """
    match = RELATIVE_TIME_PATTERN.match(since.strip())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        dt = datetime.now(timezone.utc) - (TIME_MULTIPLIERS[unit] * amount)
        return dt.isoformat()

    # Try ISO date/datetime
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(since.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue

    # Pass through as-is (let SQLite handle it)
    return since


def parse_event_types(type_str: str) -> list[EventType]:
    """Parse comma-separated event type string into list."""
    types = []
    for t in type_str.split(","):
        t = t.strip().lower()
        if t:
            types.append(EventType(t))
    return types


class QueryEngine:
    """Normalizes query parameters and delegates to EventStore."""

    def __init__(self, store: EventStore):
        self.store = store

    def execute(self, text: str | None = None,
                event_types: list[EventType] | None = None,
                agent_id: str | None = None,
                scope: str | None = None,
                since: str | None = None,
                limit: int = 50,
                related_to: str | None = None) -> list[Event]:
        """Execute a query with normalized parameters."""
        if related_to and not any([text, event_types, agent_id, scope, since]):
            return self.store.query_related(related_to, limit)

        normalized_since = parse_since(since) if since else None

        filters = QueryFilter(
            text=text,
            event_types=event_types,
            agent_id=agent_id,
            scope=scope,
            since=normalized_since,
            limit=limit,
            related_to=related_to,
        )
        return self.store.query_structured(filters)
