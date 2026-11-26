"""Read side: turn database rows into engine-ready snapshots and API-ready dicts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.config import get_settings
from app.domain.calendar_data import CATEGORY_META, Ev, Snapshot
from app.domain.classify import category_label, priority
from app.domain.timeutils import iso
from app.models import Event, Person, Preferences, Series


def user_id() -> str:
    return get_settings().user_id


def load_people(session: Session) -> dict[str, Person]:
    return {p.id: p for p in session.exec(select(Person)).all()}


def load_prefs(session: Session) -> dict[str, Preferences]:
    return {p.person_id: p for p in session.exec(select(Preferences)).all()}


def user_prefs(session: Session) -> Preferences:
    uid = user_id()
    prefs = session.get(Preferences, uid)
    if prefs is None:
        prefs = Preferences(person_id=uid)
        session.add(prefs)
        session.commit()
    return prefs


def load_snapshot(session: Session, start: datetime, end: datetime, pad_days: int = 1) -> Snapshot:
    lo, hi = start - timedelta(days=pad_days), end + timedelta(days=pad_days)
    rows = session.exec(
        select(Event).where(Event.start < hi, Event.end > lo, Event.status != "cancelled")  # type: ignore[arg-type]
    ).all()
    series = {s.id: s for s in session.exec(select(Series)).all()}
    return Snapshot(load_people(session), load_prefs(session), [Ev.from_row(r) for r in rows], series, (start, end))


def person_dict(p: Person) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "first_name": p.first_name,
        "email": p.email,
        "title": p.title,
        "team": p.team,
        "company": p.company,
        "timezone": p.timezone,
        "country": p.country,
        "city": p.city,
        "work_start": p.work_start,
        "work_end": p.work_end,
        "work_days": p.work_days,
        "is_external": p.is_external,
        "color": p.color,
        "seniority": p.seniority,
        "hourly_rate": p.hourly_rate,
        "manager_id": p.manager_id,
    }


def event_dict(ev: Ev, snap: Snapshot, uid: str, flags: list[str] | None = None) -> dict[str, Any]:
    score, factors = priority(ev, snap, uid)
    meta = CATEGORY_META.get(ev.category, CATEGORY_META["admin"])
    attendees = []
    seen = set()
    for pid in ev.participant_ids():
        if pid in seen or pid not in snap.people:
            continue
        seen.add(pid)
        p = snap.people[pid]
        a = ev.attendee(pid)
        attendees.append(
            {
                "person_id": pid,
                "name": p.name,
                "title": p.title,
                "company": p.company,
                "timezone": p.timezone,
                "is_external": p.is_external,
                "response": a.response if a else "accepted",
                "optional": a.optional if a else False,
                "organizer": pid == ev.organizer_id,
            }
        )
    my = ev.attendee(uid)
    return {
        "id": ev.id,
        "title": ev.title,
        "description": ev.description,
        "start": iso(ev.start),
        "end": iso(ev.end),
        "organizer_id": ev.organizer_id,
        "attendees": attendees,
        "kind": ev.kind,
        "category": ev.category,
        "category_label": category_label(ev.category),
        "color": meta["color"],
        "location": ev.location,
        "is_virtual": ev.is_virtual,
        "is_movable": ev.is_movable,
        "series_id": ev.series_id,
        "status": ev.status,
        "source": ev.source,
        "ai_generated": ev.ai_generated,
        "version": ev.version,
        "my_response": my.response if my else ("accepted" if ev.organizer_id == uid else None),
        "optional_for_me": ev.is_optional_for(uid),
        "priority": score,
        "priority_factors": factors,
        "flags": flags or [],
    }
