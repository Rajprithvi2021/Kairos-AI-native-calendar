"""Core resources: health, profile & preferences, people, events, demo controls, integrations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app import __version__
from app.ai.gateway import ClaudeGateway
from app.api.deps import gateway_dep, http_errors, now_dep, session_dep
from app.clock import clock, parse_utc
from app.config import get_settings
from app.domain.calendar_data import holidays_for
from app.domain.classify import categorize
from app.domain.timeutils import iso, to_local
from app.engines.conflicts import conflict_flags, detect_conflicts
from app.engines.scheduler import explain_weights
from app.integrations import google_calendar, ics
from app.models import Event, Person
from app.seed.generator import seed_database
from app.services import ops
from app.services.store import event_dict, load_people, load_snapshot, person_dict, user_id, user_prefs

router = APIRouter(prefix="/api")


@router.get("/health")
def health(session: Session = Depends(session_dep), now: datetime = Depends(now_dep), gw: ClaudeGateway = Depends(gateway_dep)) -> dict[str, Any]:
    count = session.exec(select(func.count()).select_from(Event)).one()
    return {"status": "ok", "version": __version__, "now": iso(now), "simulated_clock": clock.is_simulated,
            "events": count, "ai": gw.status()}


# --- profile & preferences -----------------------------------------------------------------------
@router.get("/me")
def me(session: Session = Depends(session_dep), gw: ClaudeGateway = Depends(gateway_dep)) -> dict[str, Any]:
    uid = user_id()
    person = session.get(Person, uid)
    if person is None:
        raise HTTPException(404, "user not found - reset the demo")
    prefs = user_prefs(session)
    return {"person": person_dict(person), "preferences": prefs.model_dump(), "ai": gw.status(),
            "learned": explain_weights(prefs.learned_weights)[:4]}


class PrefsBody(BaseModel):
    focus_goal_hours: float | None = None
    min_focus_block_min: int | None = None
    preferred_period: str | None = None
    buffer_min: int | None = None
    max_meeting_hours_day: float | None = None
    max_meeting_hours_week: float | None = None
    lunch_start: str | None = None
    lunch_end: str | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    no_meeting_days: list[int] | None = None
    autonomy: dict[str, str] | None = None
    privacy: dict[str, bool] | None = None
    work_start: str | None = None
    work_end: str | None = None
    timezone: str | None = None
    reset_learning: bool = False


@router.put("/me/preferences")
def update_prefs(body: PrefsBody, session: Session = Depends(session_dep)) -> dict[str, Any]:
    prefs = user_prefs(session)
    person = session.get(Person, user_id())
    data = body.model_dump(exclude_none=True)
    for k in ("work_start", "work_end", "timezone"):
        if k in data and person is not None:
            setattr(person, k, data.pop(k))
    if data.pop("reset_learning", False):
        prefs.learned_weights = {}
    if "autonomy" in data:
        data["autonomy"] = {**prefs.autonomy, **data["autonomy"]}
    if "privacy" in data:
        data["privacy"] = {**prefs.privacy, **data["privacy"]}
    for k, v in data.items():
        setattr(prefs, k, v)
    session.add(prefs)
    session.commit()
    return {"preferences": prefs.model_dump(), "person": person_dict(person) if person else None}


@router.get("/people")
def people(session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
    return [person_dict(p) for p in sorted(load_people(session).values(), key=lambda p: (p.is_external, p.name))]


# --- events --------------------------------------------------------------------------------------
@router.get("/events")
@http_errors
def list_events(
    start: str = Query(..., description="ISO datetime (UTC)"),
    end: str = Query(..., description="ISO datetime (UTC)"),
    session: Session = Depends(session_dep),
    now: datetime = Depends(now_dep),
) -> dict[str, Any]:
    s, e = parse_utc(start), parse_utc(end)
    if e <= s or e - s > timedelta(days=62):
        raise HTTPException(400, "invalid range (max 62 days)")
    uid = user_id()
    snap = load_snapshot(session, s, e)
    flags = conflict_flags(detect_conflicts(snap, uid, s, e, now, with_options=False))
    evs = [event_dict(ev, snap, uid, flags.get(ev.id)) for ev in snap.events_for(uid, s, e)]
    person = snap.person(uid)
    hol = holidays_for(person.country, to_local(s, person.timezone).date(), to_local(e, person.timezone).date())
    return {"events": evs, "holidays": [{"date": d.isoformat(), "name": n, "country": person.country} for d, n in sorted(hol.items())],
            "timezone": person.timezone}


class EventBody(BaseModel):
    title: str
    start: str
    end: str
    attendee_ids: list[str] = []
    optional_ids: list[str] = []
    description: str = ""
    location: str | None = None
    is_virtual: bool = True
    kind: str = "meeting"


@router.post("/events")
@http_errors
def create_event(body: EventBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    people_map = load_people(session)
    atts = [{"person_id": uid, "response": "accepted", "optional": False}]
    atts += [{"person_id": p, "response": "needsAction", "optional": False} for p in body.attendee_ids if p in people_map and p != uid]
    atts += [{"person_id": p, "response": "needsAction", "optional": True} for p in body.optional_ids if p in people_map and p != uid]
    cat = categorize(body.title, body.kind, [people_map[a["person_id"]] for a in atts])
    op = {"op": "create", "event": {"title": body.title, "start": body.start, "end": body.end, "organizer_id": uid,
                                     "attendees": atts, "description": body.description, "location": body.location,
                                     "is_virtual": body.is_virtual, "kind": body.kind, "category": cat, "source": "user"}}
    entry = ops.apply_operations(session, [op], action="create_event", summary=f"Created “{body.title}”", now=now)
    return {"audit_id": entry.id, "event_id": entry.changes[0]["event_id"]}


class EventPatch(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    location: str | None = None
    is_virtual: bool | None = None
    expected_version: int | None = None


@router.patch("/events/{event_id}")
@http_errors
def update_event(event_id: str, body: EventPatch, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    changes = body.model_dump(exclude_none=True)
    expected = changes.pop("expected_version", None)
    op = {"op": "update", "event_id": event_id, "changes": changes, "expected_version": expected}
    entry = ops.apply_operations(session, [op], action="update_event", summary="Edited event", now=now)
    return {"audit_id": entry.id}


@router.delete("/events/{event_id}")
@http_errors
def delete_event(event_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    entry = ops.apply_operations(session, [{"op": "delete", "event_id": event_id}], action="delete_event", summary="Cancelled event", now=now)
    return {"audit_id": entry.id}


# --- demo controls -------------------------------------------------------------------------------
@router.post("/demo/reset")
def demo_reset(session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    return seed_database(session, now, get_settings().seed)


class ClockBody(BaseModel):
    now: str | None = None


@router.post("/demo/clock")
@http_errors
def demo_clock(body: ClockBody) -> dict[str, Any]:
    if body.now:
        clock.freeze(parse_utc(body.now))
    else:
        clock.reset()
    return {"now": iso(clock.now()), "simulated": clock.is_simulated}


# --- integrations --------------------------------------------------------------------------------
@router.post("/import/ics")
@http_errors
async def import_ics(file: UploadFile = File(...), session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > 5_000_000:
        raise HTTPException(413, "file too large (max 5 MB)")
    people_map = load_people(session)
    uid = user_id()
    try:
        events = ics.parse_ics(raw, uid, people_map, now)
    except ValueError as e:
        raise HTTPException(400, f"could not read calendar file: {e}") from e
    if not events:
        return {"imported": 0, "skipped": 0}
    existing = {r for r in session.exec(select(Event.external_ref).where(Event.source == "ics")).all() if r}
    fresh = [ev for ev in events if ev["external_ref"] not in existing]
    if fresh:
        ops.apply_operations(session, [{"op": "create", "event": ev} for ev in fresh], action="import_ics",
                             summary=f"Imported {len(fresh)} events from {file.filename}", now=now)
    return {"imported": len(fresh), "skipped": len(events) - len(fresh)}


@router.get("/integrations/google/status")
def google_status() -> dict[str, Any]:
    return google_calendar.status(get_settings())


@router.post("/integrations/google/sync")
def google_sync() -> dict[str, Any]:
    st = google_calendar.status(get_settings())
    if not st["configured"]:
        raise HTTPException(501, st["message"])
    raise HTTPException(501, "Live sync runs through the OAuth flow; see docs/04-technical-architecture.md#integrations")
