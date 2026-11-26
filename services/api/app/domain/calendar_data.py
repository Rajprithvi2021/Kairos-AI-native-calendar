"""In-memory calendar snapshot used by all engines (pure, side-effect free).

Services load a snapshot from the database; engines (scheduler, conflicts, reminders,
analytics, forecast, defrag) operate on it. Defrag/what-if analysis clones the snapshot.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import holidays as pyholidays

from app.domain.timeutils import Interval, IntervalSet, local_date, working_intervals

CATEGORY_META: dict[str, dict[str, str]] = {
    "focus": {"label": "Focus", "color": "#10b981"},
    "one_on_one": {"label": "1:1", "color": "#6366f1"},
    "team": {"label": "Team sync", "color": "#3b82f6"},
    "customer": {"label": "Customer", "color": "#f59e0b"},
    "hiring": {"label": "Hiring", "color": "#ec4899"},
    "planning": {"label": "Planning & reviews", "color": "#8b5cf6"},
    "leadership": {"label": "Leadership", "color": "#0ea5e9"},
    "external": {"label": "Partners & vendors", "color": "#f97316"},
    "personal": {"label": "Personal", "color": "#94a3b8"},
    "admin": {"label": "Admin & other", "color": "#64748b"},
}

HQ_LOCATION = "Lumora HQ, San Francisco"


@lru_cache(maxsize=64)
def _country_holidays(country: str, year: int) -> dict[date, str]:
    try:
        return dict(pyholidays.country_holidays(country, years=year))
    except Exception:  # unknown country code
        return {}


def holidays_for(country: str, start: date, end: date) -> dict[date, str]:
    out: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        for d, name in _country_holidays(country, year).items():
            if start <= d <= end:
                out[d] = name
    return out


@dataclass
class Attendee:
    person_id: str
    response: str = "accepted"
    optional: bool = False


@dataclass
class Ev:
    id: str
    title: str
    start: datetime
    end: datetime
    organizer_id: str
    attendees: list[Attendee]
    kind: str = "meeting"
    category: str = "admin"
    location: str | None = None
    is_virtual: bool = True
    is_movable: bool = True
    series_id: str | None = None
    status: str = "confirmed"
    source: str = "seed"
    ai_generated: bool = False
    created_at: datetime | None = None
    description: str = ""
    version: int = 1

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    @property
    def is_meeting(self) -> bool:
        return self.kind == "meeting"

    @property
    def is_focus(self) -> bool:
        return self.kind in ("focus", "prep")

    def participant_ids(self) -> list[str]:
        ids = [self.organizer_id] + [a.person_id for a in self.attendees]
        return list(dict.fromkeys(ids))

    def attending(self, person_id: str) -> bool:
        """True if person is on the event and has not declined."""
        if self.status == "cancelled":
            return False
        for a in self.attendees:
            if a.person_id == person_id:
                return a.response != "declined"
        return self.organizer_id == person_id

    def attendee(self, person_id: str) -> Attendee | None:
        return next((a for a in self.attendees if a.person_id == person_id), None)

    def is_optional_for(self, person_id: str) -> bool:
        a = self.attendee(person_id)
        return bool(a and a.optional)

    @staticmethod
    def from_row(row: Any) -> Ev:
        return Ev(
            id=row.id,
            title=row.title,
            start=row.start,
            end=row.end,
            organizer_id=row.organizer_id,
            attendees=[
                Attendee(a["person_id"], a.get("response", "accepted"), bool(a.get("optional", False)))
                for a in (row.attendees or [])
            ],
            kind=row.kind,
            category=row.category,
            location=row.location,
            is_virtual=row.is_virtual,
            is_movable=row.is_movable,
            series_id=row.series_id,
            status=row.status,
            source=row.source,
            ai_generated=row.ai_generated,
            created_at=row.created_at,
            description=row.description or "",
            version=row.version,
        )


@dataclass
class Snapshot:
    """Everything engines need: people, preferences, series metadata and events in a window."""

    people: dict[str, Any]
    prefs: dict[str, Any]
    events: list[Ev]
    series: dict[str, Any] = field(default_factory=dict)
    window: Interval | None = None

    # --- people / prefs -------------------------------------------------
    def person(self, pid: str) -> Any:
        return self.people[pid]

    def pref(self, pid: str) -> Any:
        from app.models import Preferences

        return self.prefs.get(pid) or Preferences(person_id=pid)

    # --- events ---------------------------------------------------------
    def event(self, eid: str) -> Ev | None:
        return next((e for e in self.events if e.id == eid), None)

    def events_for(
        self,
        pid: str,
        start: datetime | None = None,
        end: datetime | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> list[Ev]:
        out = []
        for e in self.events:
            if not e.attending(pid):
                continue
            if kinds and e.kind not in kinds:
                continue
            if start and e.end <= start:
                continue
            if end and e.start >= end:
                continue
            out.append(e)
        return sorted(out, key=lambda e: (e.start, e.end))

    def busy(
        self,
        pid: str,
        start: datetime,
        end: datetime,
        *,
        include_focus: bool = True,
        exclude_ids: set[str] | None = None,
    ) -> IntervalSet:
        exclude_ids = exclude_ids or set()
        kinds = None if include_focus else ("meeting", "personal")
        evs = self.events_for(pid, start, end, kinds)
        return IntervalSet((e.start, e.end) for e in evs if e.id not in exclude_ids and e.status != "cancelled")

    def holidays(self, pid: str, start: datetime, end: datetime) -> dict[date, str]:
        p = self.people[pid]
        return holidays_for(p.country, local_date(start, p.timezone), local_date(end, p.timezone))

    def working(self, pid: str, start: datetime, end: datetime, stretch_min: int = 0) -> IntervalSet:
        p = self.people[pid]
        hol = set(self.holidays(pid, start, end))
        return IntervalSet(
            working_intervals(p.timezone, p.work_start, p.work_end, p.work_days, start, end, hol, stretch_min)
        )

    # --- what-if --------------------------------------------------------
    def clone(self) -> Snapshot:
        return Snapshot(self.people, self.prefs, copy.deepcopy(self.events), self.series, self.window)

    def move(self, eid: str, start: datetime, end: datetime) -> None:
        ev = self.event(eid)
        if ev is None:
            raise KeyError(eid)
        ev.start, ev.end = start, end
