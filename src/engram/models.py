"""Data models for Engram events and queries."""

from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    DISCOVERY = "discovery"
    DECISION = "decision"
    WARNING = "warning"
    MUTATION = "mutation"
    OUTCOME = "outcome"


@dataclass
class Event:
    id: str
    timestamp: str
    event_type: EventType
    agent_id: str
    content: str
    scope: list[str] | None = None
    related_ids: list[str] | None = None
    status: str = "active"
    priority: str = "normal"
    resolved_reason: str | None = None
    superseded_by: str | None = None


@dataclass
class QueryFilter:
    text: str | None = None
    event_types: list[EventType] | None = None
    agent_id: str | None = None
    scope: str | None = None
    since: str | None = None
    limit: int = 50
    related_to: str | None = None


@dataclass
class BriefingResult:
    project_name: str
    generated_at: str
    total_events: int
    time_range: str
    # New 4-section structure (P0)
    critical_warnings: list[Event] = field(default_factory=list)
    focus_relevant: list[Event] = field(default_factory=list)
    other_active: list[Event] = field(default_factory=list)
    recently_resolved: list[Event] = field(default_factory=list)
    # Retained from v1
    recent_mutations: list[Event] = field(default_factory=list)
    potentially_stale: list[Event] = field(default_factory=list)
