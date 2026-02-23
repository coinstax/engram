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


@dataclass
class QueryFilter:
    text: str | None = None
    event_types: list[EventType] | None = None
    agent_id: str | None = None
    scope: str | None = None
    since: str | None = None
    limit: int = 50


@dataclass
class BriefingResult:
    project_name: str
    generated_at: str
    total_events: int
    time_range: str
    recent_mutations: list[Event] = field(default_factory=list)
    active_warnings: list[Event] = field(default_factory=list)
    recent_decisions: list[Event] = field(default_factory=list)
    recent_discoveries: list[Event] = field(default_factory=list)
    recent_outcomes: list[Event] = field(default_factory=list)
