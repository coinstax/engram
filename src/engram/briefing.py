"""Briefing generator — summarizes project state from stored events."""

from datetime import datetime, timedelta, timezone

from engram.formatting import _short_timestamp
from engram.models import BriefingResult, Event, EventType
from engram.query import parse_since
from engram.store import EventStore


# Priority sort order (lower = more important)
_PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


class BriefingGenerator:
    """Generates project briefings from the event store."""

    def __init__(self, store: EventStore):
        self.store = store

    def generate(self, scope: str | None = None,
                 since: str | None = None,
                 focus: str | None = None,
                 resolved_window_hours: int = 48) -> BriefingResult:
        """Generate a 4-section briefing.

        Sections:
        1. Critical Warnings — critical priority + global (unscoped) warnings
        2. Focus-Relevant — events matching focus path (if provided)
        3. Other Active — remaining active events
        4. Recently Resolved — resolved events within resolved_window_hours
        """
        since_iso = parse_since(since) if since else self._default_since()

        # Fetch active events by type
        warnings = self.store.recent_by_type(
            EventType.WARNING, limit=20, since=since_iso, scope=scope, status="active")
        decisions = self.store.recent_by_type(
            EventType.DECISION, limit=15, since=since_iso, scope=scope, status="active")
        mutations = self.store.recent_by_type(
            EventType.MUTATION, limit=20, since=since_iso, scope=scope, status="active")
        discoveries = self.store.recent_by_type(
            EventType.DISCOVERY, limit=10, since=since_iso, scope=scope, status="active")
        outcomes = self.store.recent_by_type(
            EventType.OUTCOME, limit=5, since=since_iso, scope=scope, status="active")

        # Post-process mutations
        mutations = self._deduplicate_mutations(mutations)

        # Detect stale decisions/warnings
        stale = self._detect_stale(warnings + decisions, mutations)

        # Collect all non-mutation active events for sectioning
        all_active = warnings + decisions + discoveries + outcomes

        # --- Section 1: Critical Warnings ---
        critical_warnings = [
            e for e in warnings
            if e.priority == "critical" or not e.scope
        ]
        critical_ids = {e.id for e in critical_warnings}

        # --- Section 2: Focus-Relevant ---
        focus_relevant: list[Event] = []
        focus_ids: set[str] = set()
        if focus:
            for event in all_active:
                if event.id in critical_ids:
                    continue
                relevance = self._scope_relevance(event, focus)
                if relevance > 0:
                    focus_relevant.append(event)
                    focus_ids.add(event.id)
            focus_relevant = self._sort_by_priority_recency(focus_relevant)

        # --- Section 3: Other Active ---
        excluded = critical_ids | focus_ids
        other_active = [e for e in all_active if e.id not in excluded]
        other_active = self._sort_by_priority_recency(other_active)

        # --- Section 4: Recently Resolved ---
        resolved_since = (
            datetime.now(timezone.utc) - timedelta(hours=resolved_window_hours)
        ).isoformat()
        recently_resolved = self.store.recent_resolved(since=resolved_since, limit=10)

        # Sort critical warnings by priority then recency
        critical_warnings = self._sort_by_priority_recency(critical_warnings)

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
            critical_warnings=critical_warnings,
            focus_relevant=focus_relevant,
            other_active=other_active,
            recently_resolved=recently_resolved,
            recent_mutations=mutations,
            potentially_stale=stale,
        )

    @staticmethod
    def _default_since() -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=7)
        return dt.isoformat()

    @staticmethod
    def _scope_relevance(event: Event, focus_path: str) -> int:
        """Score how relevant an event's scope is to the focus path.

        Returns:
            3 = exact scope match
            2 = event scope is parent of focus
            1 = event scope is child of focus
            0 = no match
        """
        if not event.scope:
            return 0

        for s in event.scope:
            if s == focus_path:
                return 3
            if focus_path.startswith(s):
                return 2  # event scope is parent of focus
            if s.startswith(focus_path):
                return 1  # event scope is child of focus
        return 0

    @staticmethod
    def _sort_by_priority_recency(events: list[Event]) -> list[Event]:
        """Sort events by priority (critical first) then recency (newest first)."""
        # Two stable sorts: first by timestamp descending, then by priority ascending
        events_sorted = sorted(events, key=lambda e: e.timestamp, reverse=True)
        events_sorted = sorted(events_sorted, key=lambda e: _PRIORITY_ORDER.get(e.priority, 2))
        return events_sorted

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
