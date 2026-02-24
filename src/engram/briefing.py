"""Briefing generator — summarizes project state from stored events."""

from datetime import datetime, timedelta, timezone

from engram.formatting import _short_timestamp
from engram.models import BriefingResult, Event, EventType
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

        # Smarter briefing: dedup mutations and detect staleness
        mutations = self._deduplicate_mutations(mutations)
        stale = self._detect_stale(warnings + decisions, mutations)

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
            potentially_stale=stale,
        )

    @staticmethod
    def _default_since() -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=7)
        return dt.isoformat()

    @staticmethod
    def _deduplicate_mutations(mutations: list[Event]) -> list[Event]:
        """Collapse multiple mutations to the same file within a 30-min window."""
        if not mutations:
            return mutations

        # Group by (single-file scope, agent_id)
        groups: dict[tuple[str, str], list[Event]] = {}
        ungrouped: list[Event] = []

        for event in mutations:
            if event.scope and len(event.scope) == 1:
                key = (event.scope[0], event.agent_id)
                groups.setdefault(key, []).append(event)
            else:
                ungrouped.append(event)

        result = list(ungrouped)

        for (filepath, agent), group in groups.items():
            if len(group) == 1:
                result.append(group[0])
                continue

            # Sort chronologically for windowing
            group.sort(key=lambda e: e.timestamp)

            # Split into 30-min windows
            windows: list[list[Event]] = []
            current_window: list[Event] = [group[0]]

            for event in group[1:]:
                prev_ts = current_window[-1].timestamp[:19]
                curr_ts = event.timestamp[:19]
                try:
                    prev_dt = datetime.fromisoformat(prev_ts)
                    curr_dt = datetime.fromisoformat(curr_ts)
                    if (curr_dt - prev_dt) <= timedelta(minutes=30):
                        current_window.append(event)
                    else:
                        windows.append(current_window)
                        current_window = [event]
                except ValueError:
                    current_window.append(event)

            windows.append(current_window)

            for window in windows:
                if len(window) == 1:
                    result.append(window[0])
                else:
                    # Collapse into synthetic event
                    latest = window[-1]
                    count = len(window)
                    first_ts = _short_timestamp(window[0].timestamp)
                    last_ts = _short_timestamp(window[-1].timestamp)
                    collapsed = Event(
                        id=latest.id,
                        timestamp=latest.timestamp,
                        event_type=latest.event_type,
                        agent_id=latest.agent_id,
                        content=f"Modified {filepath} ({count} edits, {first_ts}-{last_ts})",
                        scope=latest.scope,
                        related_ids=[e.id for e in window],
                    )
                    result.append(collapsed)

        # Sort by timestamp descending (most recent first)
        result.sort(key=lambda e: e.timestamp, reverse=True)
        return result

    @staticmethod
    def _detect_stale(decisions_and_warnings: list[Event],
                      mutations: list[Event]) -> list[Event]:
        """Find decisions/warnings whose scope was modified by a later mutation."""
        stale: list[Event] = []

        for event in decisions_and_warnings:
            if not event.scope:
                continue
            event_scopes = set(event.scope)

            for mutation in mutations:
                if not mutation.scope:
                    continue
                if mutation.timestamp <= event.timestamp:
                    continue
                if event_scopes & set(mutation.scope):
                    stale.append(event)
                    break

        return stale
