"""Intelligence endpoints: scheduling, conflicts, reminders, briefs, analytics, focus, assistant."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.ai.gateway import ClaudeGateway
from app.api.deps import gateway_dep, http_errors, now_dep, session_dep
from app.clock import parse_utc
from app.domain.classify import categorize
from app.domain.timeutils import iso, to_local, week_start
from app.engines import analytics, conflicts, focus, forecast, insights, reminders
from app.engines.scheduler import SlotRequest, explain_weights, find_slots, learn_weights
from app.models import ReminderSetting
from app.services import assistant, ops
from app.services.store import event_dict, load_people, load_snapshot, user_id, user_prefs

router = APIRouter(prefix="/api")


# --- F1 scheduling -------------------------------------------------------------------------------
class SuggestBody(BaseModel):
    attendee_ids: list[str] = []
    optional_ids: list[str] = []
    duration_min: int = 30
    window_start: str | None = None
    window_end: str | None = None
    preferred_period: str = "any"
    earliest_local: str | None = None
    latest_local: str | None = None
    respect_focus: bool = True
    exclude_event_id: str | None = None
    max_results: int = 5
    stretch_hours_min: int = 0
    min_notice_min: int = 60

    def to_request(self, uid: str) -> SlotRequest:
        return SlotRequest(
            organizer_id=uid, attendee_ids=[a for a in self.attendee_ids if a != uid], duration_min=self.duration_min,
            window_start=parse_utc(self.window_start) if self.window_start else None,
            window_end=parse_utc(self.window_end) if self.window_end else None,
            optional_ids=self.optional_ids, preferred_period=self.preferred_period, earliest_local=self.earliest_local,
            latest_local=self.latest_local, respect_focus=self.respect_focus, exclude_event_id=self.exclude_event_id,
            max_results=min(self.max_results, 10), stretch_hours_min=self.stretch_hours_min, min_notice_min=self.min_notice_min,
        )


@router.post("/schedule/suggest")
def suggest(body: SuggestBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    if not 5 <= body.duration_min <= 480:
        raise HTTPException(400, "duration must be 5-480 minutes")
    people = load_people(session)
    unknown = [a for a in body.attendee_ids + body.optional_ids if a not in people]
    if unknown:
        raise HTTPException(400, f"unknown people: {unknown}")
    req = body.to_request(uid)
    end = req.window_end or now + timedelta(days=7)
    snap = load_snapshot(session, now - timedelta(days=1), end + timedelta(days=8))
    res = find_slots(snap, req, now, snap.pref(uid).learned_weights)
    ops.track(session, "suggestion_shown", now, {"kind": "slots", "count": len(res.slots)})
    return res.to_dict()


class BookBody(BaseModel):
    title: str
    start: str
    end: str
    attendee_ids: list[str] = []
    optional_ids: list[str] = []
    agenda: str = ""
    mode: str = "new"  # new | reschedule
    event_id: str | None = None
    chosen_rank: int | None = None
    chosen_components: dict[str, float] | None = None
    shown_components: list[dict[str, float]] = []


@router.post("/schedule/book")
@http_errors
def book(body: BookBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    known = load_people(session)
    unknown = [a for a in body.attendee_ids + body.optional_ids if a not in known]
    if unknown:
        raise HTTPException(400, f"unknown people: {unknown}")
    s, e = parse_utc(body.start), parse_utc(body.end)
    snap = load_snapshot(session, s - timedelta(days=1), e + timedelta(days=1))
    required = [uid, *body.attendee_ids]
    if body.mode == "reschedule" and body.event_id:
        ev = snap.event(body.event_id)
        if ev is None:
            raise HTTPException(404, "event not found")
        required = [p for p in ev.participant_ids() if ev.attending(p)]
    for pid in required:  # optimistic re-check: someone may have booked the slot meanwhile
        if pid in snap.people and snap.busy(pid, s, e, exclude_ids={body.event_id} if body.event_id else None).overlaps(s, e):
            raise HTTPException(409, f"{snap.people[pid].name} is no longer free at that time - refresh suggestions")
    if body.mode == "reschedule" and body.event_id:
        op = {"op": "update", "event_id": body.event_id, "changes": {"start": body.start, "end": body.end}}
        summary = f"Moved “{body.title}”"
        action = "reschedule"
    else:
        people = load_people(session)
        atts = [{"person_id": uid, "response": "accepted", "optional": False}]
        atts += [{"person_id": p, "response": "needsAction", "optional": False} for p in body.attendee_ids if p != uid]
        atts += [{"person_id": p, "response": "needsAction", "optional": True} for p in body.optional_ids if p != uid]
        cat = categorize(body.title, "meeting", [people[a["person_id"]] for a in atts if a["person_id"] in people])
        op = {"op": "create", "event": {"title": body.title, "start": body.start, "end": body.end, "organizer_id": uid,
                                         "attendees": atts, "description": body.agenda, "category": cat, "source": "ai",
                                         "ai_generated": True}}
        summary = f"Booked “{body.title}”"
        action = "book_meeting"
    entry = ops.apply_operations(session, [op], action=action, summary=summary, now=now, actor="user")
    learned = None
    if body.chosen_components and body.shown_components:
        prefs = user_prefs(session)
        prefs.learned_weights = learn_weights(prefs.learned_weights, body.chosen_components, body.shown_components)
        session.add(prefs)
        session.commit()
        learned = explain_weights(prefs.learned_weights)[:3]
    ops.track(session, "slot_booked", now, {"rank": body.chosen_rank, "mode": body.mode})
    return {"audit_id": entry.id, "event_id": entry.changes[0]["event_id"], "summary": summary, "learned": learned}


# --- F2 conflicts ----------------------------------------------------------------------------------
@router.get("/conflicts")
def list_conflicts(days: int = Query(14, ge=1, le=42), session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> list[dict[str, Any]]:
    uid = user_id()
    snap = load_snapshot(session, now - timedelta(days=1), now + timedelta(days=days + 10))
    return [c.to_dict() for c in conflicts.detect_conflicts(snap, uid, now, now + timedelta(days=days), now)]


class ResolveBody(BaseModel):
    conflict_id: str
    option_id: str


@router.post("/conflicts/resolve")
@http_errors
def resolve(body: ResolveBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    snap = load_snapshot(session, now - timedelta(days=1), now + timedelta(days=52))
    found = next((c for c in conflicts.detect_conflicts(snap, uid, now, now + timedelta(days=42), now) if c.id == body.conflict_id), None)
    if found is None:
        raise HTTPException(404, "conflict not found (already resolved?)")
    option = next((o for o in found.options if o.id == body.option_id), None)
    if option is None:
        raise HTTPException(404, "option not found")
    entry = ops.apply_operations(session, option.operations, action="resolve_conflict", summary=option.label, now=now)
    ops.track(session, "proposal_applied", now, {"kind": "conflict", "option": option.kind})
    return {"audit_id": entry.id, "summary": option.label, "draft": option.draft}


# --- F3 reminders & briefs ------------------------------------------------------------------------
def _overrides(session: Session, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not event_ids:
        return out
    rows = session.exec(select(ReminderSetting).where(ReminderSetting.event_id.in_(event_ids))).all()  # type: ignore[attr-defined]
    for r in rows:
        out.setdefault(r.event_id, {})[r.kind] = r
    return out


@router.get("/events/{event_id}/reminders")
def event_reminders(event_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    snap = load_snapshot(session, now - timedelta(days=95), now + timedelta(days=60))
    ev = snap.event(event_id)
    if ev is None:
        raise HTTPException(404, "event not found")
    plan = reminders.plan_event(snap, ev, uid, now, _overrides(session, [event_id]).get(event_id))
    return {"event_id": event_id, "reminders": [r.to_dict() for r in plan]}


class ToggleBody(BaseModel):
    enabled: bool


@router.patch("/events/{event_id}/reminders/{kind}")
def toggle_reminder(event_id: str, kind: str, body: ToggleBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    if kind not in ("prep", "leave", "join", "followup", "custom"):
        raise HTTPException(400, "unknown reminder kind")
    rid = f"{event_id}:{kind}"
    row = session.get(ReminderSetting, rid) or ReminderSetting(id=rid, event_id=event_id, kind=kind, updated_at=now)
    row.enabled, row.updated_at = body.enabled, now
    session.add(row)
    session.commit()
    ops.track(session, "reminder_toggled", now, {"kind": kind, "enabled": body.enabled})
    return {"id": rid, "enabled": row.enabled}


@router.get("/reminders/upcoming")
def upcoming_reminders(hours: int = Query(48, ge=1, le=168), session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> list[dict[str, Any]]:
    uid = user_id()
    snap = load_snapshot(session, now - timedelta(days=95), now + timedelta(hours=hours + 24))
    ids = [e.id for e in snap.events_for(uid, now - timedelta(hours=1), now + timedelta(hours=hours))]
    out = []
    for r in reminders.upcoming(snap, uid, now, hours, _overrides(session, ids)):
        d = r.to_dict()
        d["due"] = r.fire_at <= now
        out.append(d)
    return out


@router.get("/digest")
def get_digest(day: str | None = None, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    snap = load_snapshot(session, now - timedelta(days=95), now + timedelta(days=14))
    tzname = snap.person(uid).timezone
    d = date.fromisoformat(day) if day else to_local(now, tzname).date()
    cs = conflicts.detect_conflicts(snap, uid, now, now + timedelta(days=14), now, with_options=False)
    count = sum(1 for c in cs if c.day == d.isoformat())
    return reminders.digest(snap, uid, d, now, count)


@router.get("/events/{event_id}/brief")
@http_errors
def brief(event_id: str, refresh: bool = False, session: Session = Depends(session_dep), now: datetime = Depends(now_dep),
          gw: ClaudeGateway = Depends(gateway_dep)) -> dict[str, Any]:
    return assistant.get_brief(session, event_id, now, gw, refresh)


@router.get("/events/{event_id}")
def get_event(event_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    snap = load_snapshot(session, now - timedelta(days=95), now + timedelta(days=60))
    ev = snap.event(event_id)
    if ev is None:
        raise HTTPException(404, "event not found")
    d = event_dict(ev, snap, uid)
    rate = sum(snap.people[p].hourly_rate for p in ev.participant_ids() if p in snap.people and ev.attending(p))
    d["cost"] = round(ev.minutes / 60 * rate)
    series = snap.series.get(ev.series_id) if ev.series_id else None
    d["series"] = series.model_dump() if series else None
    tip = None
    if series and series.avg_actual_min and series.avg_actual_min <= 0.8 * series.duration_min:
        tip = f"This series usually wraps after ~{int(series.avg_actual_min)} of {series.duration_min} min — consider shortening it."
    elif ev.is_optional_for(uid):
        tip = "You're optional here — follow the notes asynchronously if the agenda doesn't need you."
    elif len(d["attendees"]) >= 8:
        tip = "Large meeting: send status as a pre-read and keep the live time for decisions."
    d["necessity_tip"] = tip
    return d


# --- F4/F7 analytics ---------------------------------------------------------------------------------
def _analytics_snapshot(session: Session, now: datetime) -> Any:
    return load_snapshot(session, now - timedelta(weeks=13), now + timedelta(weeks=6))


@router.get("/analytics/summary")
def analytics_summary(session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    return analytics.summary(_analytics_snapshot(session, now), user_id(), now)


@router.get("/analytics/forecast")
def analytics_forecast(session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    return forecast.forecast(_analytics_snapshot(session, now), user_id(), now)


@router.get("/analytics/recurring")
def analytics_recurring(session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> list[dict[str, Any]]:
    return analytics.recurring_audit(_analytics_snapshot(session, now), user_id(), now)


@router.post("/analytics/recurring/{series_id}/proposal")
@http_errors
def recurring_proposal(series_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    plan = analytics.series_action_ops(_analytics_snapshot(session, now), user_id(), series_id, now)
    sug = plan["series"]["suggestion"]
    if not plan["operations"]:
        return {"proposal": None, "draft": plan["draft"], "message": "Nothing to change automatically; a message draft is ready." if plan["draft"]
                else f"{sug['label']}: no automatic change (you don't organise this series)."}
    prop = ops.create_proposal(session, kind="series_change", title=f"{sug['label']}: {plan['series']['title']}",
                               summary=sug["detail"], operations=plan["operations"],
                               explanation={"draft": plan["draft"], "saves_hours_month": sug["saves_hours_month"]}, now=now)
    return {"proposal": ops.proposal_dict(prop), "draft": plan["draft"]}


@router.get("/insights")
def get_insights(session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> list[dict[str, Any]]:
    uid = user_id()
    snap = _analytics_snapshot(session, now)
    cs = conflicts.detect_conflicts(snap, uid, now, now + timedelta(days=14), now)
    fc = forecast.forecast(snap, uid, now)
    audit = analytics.recurring_audit(snap, uid, now)
    fair = analytics.fairness(snap, uid, now)
    ids = [e.id for e in snap.events_for(uid, now, now + timedelta(hours=48))]
    up = reminders.upcoming(snap, uid, now, 48, _overrides(session, ids))
    cards = insights.build_feed(cs, fc, audit, fair, up, snap.pref(uid).focus_goal_hours, now)
    ops.track(session, "suggestion_shown", now, {"kind": "insights", "count": len(cards)})
    return cards


# --- F5 focus ------------------------------------------------------------------------------------------
class WeekBody(BaseModel):
    week_start: str | None = None


def _monday(body: WeekBody, now: datetime, tzname: str) -> date:
    if body.week_start:
        return week_start(date.fromisoformat(body.week_start))
    today = to_local(now, tzname).date()
    return week_start(today) + timedelta(weeks=1 if today.weekday() >= 3 else 0)


@router.post("/focus/protect")
def focus_protect(body: WeekBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    snap = _analytics_snapshot(session, now)
    monday = _monday(body, now, snap.person(uid).timezone)
    plan = focus.plan_protection(snap, uid, monday, now)
    if not plan["operations"]:
        return {"plan": plan, "proposal": None, "applied": False}
    prop = ops.create_proposal(session, kind="protect_focus", title=f"Protect {plan['added_hours']:g}h of focus (week of {plan['week_start']})",
                               summary=", ".join(b["label"] for b in plan["blocks"]), operations=plan["operations"],
                               explanation=plan, now=now)
    if snap.pref(uid).autonomy.get("focus") == "auto":
        entry = ops.apply_proposal(session, prop.id, now, actor="ai")
        return {"plan": plan, "proposal": ops.proposal_dict(prop), "applied": True, "audit_id": entry.id}
    return {"plan": plan, "proposal": ops.proposal_dict(prop), "applied": False}


@router.post("/focus/defrag")
def focus_defrag(body: WeekBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    uid = user_id()
    snap = _analytics_snapshot(session, now)
    monday = _monday(body, now, snap.person(uid).timezone)
    plan = focus.plan_defrag(snap, uid, monday, now)
    if not plan["operations"]:
        return {"plan": plan, "proposal": None}
    prop = ops.create_proposal(session, kind="defrag", title=f"Defrag week of {plan['week_start']}",
                               summary=f"Deep-work time {plan['before_hours']}h → {plan['after_hours']}h ({len(plan['moves'])} moves)",
                               operations=plan["operations"], explanation=plan, now=now)
    return {"plan": plan, "proposal": ops.proposal_dict(prop)}


# --- F6 assistant -----------------------------------------------------------------------------------------
class CommandBody(BaseModel):
    text: str


@router.post("/assistant/command")
def command(body: CommandBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep),
            gw: ClaudeGateway = Depends(gateway_dep)) -> dict[str, Any]:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty command")
    if len(text) > 500:
        raise HTTPException(400, "command too long (max 500 characters)")
    return assistant.handle_command(session, text, now, gw)


class DraftBody(BaseModel):
    subject: str
    body: str


@router.post("/ai/draft")
def polish(body: DraftBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep),
           gw: ClaudeGateway = Depends(gateway_dep)) -> dict[str, Any]:
    return assistant.polish_draft(session, body.subject, body.body, now, gw)


@router.get("/ai/status")
def ai_status(session: Session = Depends(session_dep), gw: ClaudeGateway = Depends(gateway_dep)) -> dict[str, Any]:
    from app.models import AiCallLog

    rows = session.exec(select(AiCallLog).order_by(AiCallLog.id.desc()).limit(25)).all()  # type: ignore[union-attr]
    return {"status": gw.status(), "calls": [
        {"task": r.task, "engine": r.engine, "model": r.model, "latency_ms": r.latency_ms, "input_tokens": r.input_tokens,
         "output_tokens": r.output_tokens, "outcome": r.outcome, "detail": r.detail, "at": iso(r.created_at)} for r in rows]}
