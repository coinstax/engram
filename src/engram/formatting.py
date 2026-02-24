"""Output formatters for events and briefings."""

import json
from dataclasses import asdict

from engram.models import BriefingResult, Event


def _short_timestamp(ts: str) -> str:
    """Convert ISO timestamp to compact form: '2026-02-23 14:30'."""
    return ts[:16].replace("T", " ")


def _scope_str(scope: list[str] | None) -> str:
    """Format scope list for compact output."""
    if not scope:
        return ""
    if len(scope) == 1:
        return scope[0]
    return f"{scope[0]} +{len(scope) - 1} more"


def format_event_compact(event: Event) -> str:
    """Single-line compact format for one event."""
    ts = _short_timestamp(event.timestamp)
    scope = _scope_str(event.scope)
    scope_part = f" {scope} —" if scope else " —"
    links = f" (links: {len(event.related_ids)})" if event.related_ids else ""
    priority_tag = f" [{event.priority.upper()}]" if event.priority not in ("normal", None) else ""
    return f"[{ts}] [{event.event_type.value}]{priority_tag} [{event.agent_id}]{scope_part} {event.content}{links}"


def format_compact(events: list[Event]) -> str:
    """Compact multi-line output for a list of events."""
    if not events:
        return "(no events)"
    return "\n".join(format_event_compact(e) for e in events)


def format_json(events: list[Event]) -> str:
    """JSON array output."""
    data = []
    for e in events:
        d = asdict(e)
        d["event_type"] = e.event_type.value
        data.append(d)
    return json.dumps(data, indent=2)


def format_briefing_compact(briefing: BriefingResult) -> str:
    """Token-efficient briefing for LLM context. 4-section structure."""
    lines = [
        f"# Engram Briefing — {briefing.project_name} ({_short_timestamp(briefing.generated_at)} UTC)",
        f"# {briefing.total_events} events | {briefing.time_range}",
        "",
    ]

    if briefing.potentially_stale:
        lines.append(f"## Possibly Stale ({len(briefing.potentially_stale)})")
        for e in briefing.potentially_stale:
            lines.append(f"[POSSIBLY STALE] {format_event_compact(e)}")
        lines.append("")

    sections = [
        ("Critical Warnings", briefing.critical_warnings),
        ("Focus-Relevant", briefing.focus_relevant),
        ("Other Active", briefing.other_active),
        ("Recently Resolved", briefing.recently_resolved),
        ("Recent Changes", briefing.recent_mutations),
    ]

    for title, events in sections:
        if events:
            lines.append(f"## {title} ({len(events)})")
            for e in events:
                prefix = ""
                if title == "Recently Resolved" and e.resolved_reason:
                    prefix = f"[resolved: {e.resolved_reason}] "
                lines.append(f"{prefix}{format_event_compact(e)}")
            lines.append("")

    return "\n".join(lines).rstrip()


def format_briefing_json(briefing: BriefingResult) -> str:
    """Full JSON briefing."""
    d = asdict(briefing)
    # Fix EventType enum serialization in all event list fields
    event_keys = ("critical_warnings", "focus_relevant", "other_active",
                  "recently_resolved", "recent_mutations", "potentially_stale")
    for key in event_keys:
        for event in d.get(key, []):
            if hasattr(event.get("event_type"), "value"):
                event["event_type"] = event["event_type"].value
    return json.dumps(d, indent=2)
