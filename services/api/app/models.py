"""Persistence model (SQLModel). All datetimes are stored as UTC and returned timezone-aware.

The prototype keeps attendees as a JSON column for simplicity; the production schema
(docs/04-technical-architecture.md) normalises them into an attendee table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in SQLite, always hands back aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected - use timezone-aware UTC")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utc_col(nullable: bool = False, index: bool = False) -> Any:
    return Field(sa_column=Column(UTCDateTime(), nullable=nullable, index=index))


def json_col(default_factory: Any) -> Any:
    return Field(default_factory=default_factory, sa_column=Column(JSON, nullable=False))


class Person(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    email: str
    title: str = ""
    team: str = ""
    company: str = "Lumora"
    timezone: str = "America/Los_Angeles"
    country: str = "US"
    city: str = ""
    work_start: str = "09:00"
    work_end: str = "17:30"
    work_days: list[int] = json_col(lambda: [0, 1, 2, 3, 4])
    seniority: int = 2  # 1 (junior) .. 5 (CEO)
    is_external: bool = False
    hourly_rate: float = 90.0
    color: str = "#6366f1"
    manager_id: str | None = None

    @property
    def first_name(self) -> str:
        return self.name.split(" ")[0]


class Preferences(SQLModel, table=True):
    person_id: str = Field(primary_key=True)
    focus_goal_hours: float = 10.0
    min_focus_block_min: int = 90
    preferred_period: str = "any"  # any | morning | afternoon
    buffer_min: int = 10
    max_meeting_hours_day: float = 5.0
    max_meeting_hours_week: float = 22.0
    lunch_start: str = "12:00"
    lunch_end: str = "13:00"
    quiet_start: str = "20:00"
    quiet_end: str = "07:30"
    no_meeting_days: list[int] = json_col(list)
    autonomy: dict[str, str] = json_col(
        lambda: {"scheduling": "suggest", "focus": "ask", "reminders": "auto", "conflicts": "suggest"}
    )
    privacy: dict[str, bool] = json_col(lambda: {"send_titles_to_ai": True, "redact_external_names": True})
    learned_weights: dict[str, float] = json_col(dict)
    dismissed_conflicts: list[str] = json_col(list)


class Series(SQLModel, table=True):
    """Metadata for a recurring meeting series (instances live in Event)."""

    id: str = Field(primary_key=True)
    title: str
    organizer_id: str
    cadence: str
    duration_min: int
    category: str
    avg_actual_min: float | None = None
    user_attendance_rate: float | None = None
    user_optional: bool = False
    notes: str = ""


class Event(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    description: str = ""
    start: datetime = utc_col(index=True)
    end: datetime = utc_col(index=True)
    organizer_id: str = Field(index=True)
    # [{"person_id": str, "response": "accepted|tentative|declined|needsAction", "optional": bool}]
    attendees: list[dict[str, Any]] = json_col(list)
    kind: str = "meeting"  # meeting | focus | prep | personal
    category: str = "admin"
    location: str | None = None
    is_virtual: bool = True
    is_movable: bool = True
    series_id: str | None = Field(default=None, index=True)
    status: str = "confirmed"  # confirmed | tentative | cancelled
    source: str = "seed"  # seed | user | ai | ics | google
    ai_generated: bool = False
    created_at: datetime = utc_col()
    version: int = 1
    external_ref: str | None = None


class ReminderSetting(SQLModel, table=True):
    """User overrides on top of the computed smart-reminder plan."""

    id: str = Field(primary_key=True)  # f"{event_id}:{kind}"
    event_id: str = Field(index=True)
    kind: str  # prep | leave | join | followup | custom
    enabled: bool = True
    minutes_before: int | None = None  # for custom reminders
    message: str = ""
    updated_at: datetime = utc_col()


class Proposal(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: str
    title: str
    summary: str = ""
    operations: list[dict[str, Any]] = json_col(list)
    explanation: dict[str, Any] = json_col(dict)
    status: str = "pending"  # pending | applied | discarded | undone
    source: str = "engine"  # engine | assistant | user
    created_at: datetime = utc_col()
    audit_id: str | None = None


class AuditEntry(SQLModel, table=True):
    id: str = Field(primary_key=True)
    proposal_id: str | None = None
    action: str
    actor: str = "user"  # user | ai
    summary: str
    changes: list[dict[str, Any]] = json_col(list)
    created_at: datetime = utc_col(index=True)
    undone: bool = False


class Feedback(SQLModel, table=True):
    id: str = Field(primary_key=True)
    target_type: str
    target_id: str
    rating: int  # +1 / -1
    reasons: list[str] = json_col(list)
    comment: str = ""
    participant_id: str | None = None
    created_at: datetime = utc_col()


class TelemetryEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    props: dict[str, Any] = json_col(dict)
    participant_id: str | None = None
    created_at: datetime = utc_col(index=True)


class StudyResult(SQLModel, table=True):
    id: str = Field(primary_key=True)
    participant_id: str
    task_id: str
    duration_s: float | None = None
    success: str = "yes"  # yes | partial | no
    seq: int | None = None
    notes: str = ""
    created_at: datetime = utc_col()


class AiCallLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task: str
    engine: str  # claude | offline
    model: str | None = None
    latency_ms: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    outcome: str = "ok"  # ok | fallback | refusal | error
    detail: str = ""
    created_at: datetime = utc_col(index=True)


class BriefCache(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    engine: str
    content: dict[str, Any] = json_col(dict)
    created_at: datetime = utc_col()
