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
    return f"[{ts}] [{event.event_type.value}] [{event.agent_id}]{scope_part} {event.content}"


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
    """Token-efficient briefing for LLM context."""
    lines = [
        f"# Engram Briefing — {briefing.project_name} ({_short_timestamp(briefing.generated_at)} UTC)",
        f"# {briefing.total_events} events | {briefing.time_range}",
        "",
    ]

    sections = [
        ("Warnings", briefing.active_warnings),
        ("Recent Decisions", briefing.recent_decisions),
        ("Recent Changes", briefing.recent_mutations),
        ("Discoveries", briefing.recent_discoveries),
        ("Outcomes", briefing.recent_outcomes),
    ]

    for title, events in sections:
        if events:
            lines.append(f"## {title} ({len(events)})")
            for e in events:
                lines.append(format_event_compact(e))
            lines.append("")

    return "\n".join(lines).rstrip()


def format_briefing_json(briefing: BriefingResult) -> str:
    """Full JSON briefing."""
    d = asdict(briefing)
    # Fix EventType enum serialization
    for key in ("recent_mutations", "active_warnings", "recent_decisions",
                "recent_discoveries", "recent_outcomes"):
        for event in d[key]:
            event["event_type"] = event["event_type"].value if hasattr(event["event_type"], "value") else event["event_type"]
    return json.dumps(d, indent=2)
