"""Briefing generator — summarizes project state from stored events."""

from datetime import datetime, timedelta, timezone

from engram.models import BriefingResult, EventType
from engram.query import parse_since
from engram.store import EventStore


class BriefingGenerator:
    """Generates project briefings from the event store."""

    def __init__(self, store: EventStore):
        self.store = store

    def generate(self, scope: str | None = None,
                 since: str | None = None) -> BriefingResult:
        """Generate a briefing. Defaults to last 7 days."""
        since_iso = parse_since(since) if since else self._default_since()

        warnings = self.store.recent_by_type(
            EventType.WARNING, limit=10, since=since_iso, scope=scope)
        decisions = self.store.recent_by_type(
            EventType.DECISION, limit=10, since=since_iso, scope=scope)
        mutations = self.store.recent_by_type(
            EventType.MUTATION, limit=20, since=since_iso, scope=scope)
        discoveries = self.store.recent_by_type(
            EventType.DISCOVERY, limit=10, since=since_iso, scope=scope)
        outcomes = self.store.recent_by_type(
            EventType.OUTCOME, limit=5, since=since_iso, scope=scope)

        project_name = self.store.get_meta("project_name") or "unknown"
        total = self.store.count()

        last = self.store.last_activity()
        first_ts = since_iso[:10] if since_iso else "unknown"
        last_ts = last[:10] if last else "now"
        time_range = f"{first_ts} to {last_ts}"

        return BriefingResult(
            project_name=project_name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_events=total,
            time_range=time_range,
            recent_mutations=mutations,
            active_warnings=warnings,
            recent_decisions=decisions,
            recent_discoveries=discoveries,
            recent_outcomes=outcomes,
        )

    @staticmethod
    def _default_since() -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=7)
        return dt.isoformat()
