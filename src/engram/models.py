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
    session_id: str | None = None


@dataclass
class Session:
    id: str
    agent_id: str
    focus: str
    scope: list[str] | None = None
    started_at: str = ""
    ended_at: str | None = None
    description: str | None = None


@dataclass
class Checkpoint:
    id: str
    file_path: str
    agent_id: str
    created_at: str
    event_count_at_creation: int
    enriched_sections: list[str] | None = None
    session_id: str | None = None


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
    # Sessions
    active_sessions: list[Session] = field(default_factory=list)
    # 4-section structure
    critical_warnings: list[Event] = field(default_factory=list)
    focus_relevant: list[Event] = field(default_factory=list)
    other_active: list[Event] = field(default_factory=list)
    recently_resolved: list[Event] = field(default_factory=list)
    # Retained from v1
    recent_mutations: list[Event] = field(default_factory=list)
    potentially_stale: list[Event] = field(default_factory=list)
