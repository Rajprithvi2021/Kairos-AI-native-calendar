"""Structured-output contracts shared by Claude and the offline twins (one schema, two engines)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Action = Literal[
    "schedule_meeting",
    "reschedule_event",
    "cancel_event",
    "block_focus",
    "find_conflicts",
    "show_analytics",
    "defrag_week",
    "brief_event",
    "set_reminder",
    "unknown",
]


class DateWindow(BaseModel):
    start_date: str = Field(description="First day to consider, YYYY-MM-DD, in the user's time zone")
    end_date: str = Field(description="Last day to consider (inclusive), YYYY-MM-DD, in the user's time zone")


class ParsedCommand(BaseModel):
    action: Action = Field(description="What the user wants Kairos to do")
    title: str | None = Field(default=None, description="Meeting or focus-block title if stated or implied")
    attendees: list[str] = Field(default_factory=list, description="Required people, copied exactly as the user named them")
    optional_attendees: list[str] = Field(default_factory=list, description="People the user marked as optional")
    duration_minutes: int | None = Field(default=None, description="Meeting length in minutes")
    window: DateWindow | None = Field(default=None, description="Date range to search; null if not stated")
    time_of_day: Literal["morning", "afternoon", "evening", "any"] | None = None
    earliest_time: str | None = Field(default=None, description="Earliest start, HH:MM 24h, user's time zone")
    latest_time: str | None = Field(default=None, description="Latest end, HH:MM 24h, user's time zone")
    target_event: str | None = Field(default=None, description="Words identifying an existing event (reschedule/cancel/brief/reminder)")
    focus_hours: float | None = Field(default=None, description="Hours of focus time to block")
    reminder_minutes_before: int | None = Field(default=None, description="For reminders: minutes before the event")
    confidence: float = Field(default=0.8, description="0-1 confidence in this interpretation")


class AgendaItem(BaseModel):
    item: str
    minutes: int


class MeetingBrief(BaseModel):
    purpose: str = Field(description="One sentence: why this meeting exists")
    context: list[str] = Field(description="3-5 factual bullets of relevant context")
    agenda: list[AgendaItem] = Field(description="Suggested agenda that fits the meeting length")
    talking_points: list[str] = Field(description="2-4 points the user should raise")
    prep_checklist: list[str] = Field(description="2-4 concrete prep actions")
    watch_outs: list[str] = Field(description="Risks or sensitivities (time zones, first meeting, etc.)")


class Draft(BaseModel):
    subject: str
    body: str
