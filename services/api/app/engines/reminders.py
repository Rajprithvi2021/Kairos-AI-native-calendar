"""Smart reminders (F3): context-aware timing, explained, and deliberately low-noise.

Instead of a fixed "10 minutes before", each meeting gets a plan:
- prep:      sized by category, priority, first contact with external attendees and whether the user
             runs it; placed at the latest real free gap before the meeting (or the day before).
- leave:     for in-person meetings, travel time from the previous location (or HQ) + 10 min buffer.
- join:      for virtual meetings; earlier when the previous meeting runs back-to-back.
- followup:  after customer/decision meetings, with a drafted recap.
Routine recurring meetings get no reminders at all (noise control), and quiet hours are respected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.domain.calendar_data import HQ_LOCATION, Ev, Snapshot
from app.domain.classify import category_label, is_in_person, priority, travel_minutes
from app.domain.drafts import followup_recap
from app.domain.timeutils import (
    IntervalSet,
    fmt_local,
    fmt_time,
    iso,
    local_to_utc,
    parse_hhmm,
    subtract,
    to_local,
)

PREP_BASE = {
    "customer": 30,
    "leadership": 30,
    "planning": 20,
    "hiring": 15,
    "external": 15,
    "one_on_one": 10,
}
FOLLOWUP_CATEGORIES = {"customer", "planning", "leadership", "external", "hiring"}


@dataclass
class PlannedReminder:
    id: str
    event_id: str
    event_title: str
    kind: str
    fire_at: datetime
    title: str
    rationale: str
    enabled: bool = True
    suppressed: bool = False
    channel: str = "push"
    action: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fire_at"] = iso(self.fire_at)
        return d


def is_routine(ev: Ev, snap: Snapshot, uid: str) -> bool:
    if not ev.series_id:
        return False
    return ev.category == "team" or (ev.category == "one_on_one" and priority(ev, snap, uid)[0] < 60)


def _met_before(snap: Snapshot, uid: str, external_ids: list[str], ev: Ev) -> bool:
    horizon = ev.start - timedelta(days=90)
    for e in snap.events:
        if e.id == ev.id or e.end > ev.start or e.start < horizon or not e.attending(uid):
            continue
        if any(e.attending(x) for x in external_ids):
            return True
    return False


def _free_gaps(snap: Snapshot, uid: str, day: date, until: datetime | None) -> list[tuple[datetime, datetime]]:
    p = snap.person(uid)
    ws = local_to_utc(day, parse_hhmm(p.work_start), p.timezone)
    we = local_to_utc(day, parse_hhmm(p.work_end), p.timezone)
    end = min(we, until) if until else we
    if end <= ws:
        return []
    busy = snap.busy(uid, ws, end, include_focus=True)
    return subtract((ws, end), busy.items)


def _in_quiet_hours(dt: datetime, snap: Snapshot, uid: str) -> bool:
    prefs = snap.pref(uid)
    t = to_local(dt, snap.person(uid).timezone).time()
    qs, qe = parse_hhmm(prefs.quiet_start), parse_hhmm(prefs.quiet_end)
    return t >= qs or t < qe


def plan_event(snap: Snapshot, ev: Ev, uid: str, now: datetime, overrides: dict[str, Any] | None = None) -> list[PlannedReminder]:
    overrides = overrides or {}
    out: list[PlannedReminder] = []
    if ev.kind != "meeting" or not ev.attending(uid):
        return _customs(ev, overrides)
    tzname = snap.person(uid).timezone
    score, _ = priority(ev, snap, uid)
    routine = is_routine(ev, snap, uid)
    others = [p for p in ev.participant_ids() if p != uid]

    def mk(kind: str, fire_at: datetime, title: str, rationale: str, action: dict[str, Any] | None = None, suppressed: bool = False) -> None:
        r = PlannedReminder(f"{ev.id}:{kind}", ev.id, ev.title, kind, fire_at, title, rationale, True, suppressed, "push", action)
        if kind in overrides:
            r.enabled = bool(overrides[kind].enabled)
        if suppressed:
            r.enabled = False if kind not in overrides else r.enabled
        out.append(r)

    # Travel first: for in-person meetings, prep has to finish before the user leaves.
    leave_at: datetime | None = None
    origin, travel = HQ_LOCATION, 0
    if is_in_person(ev):
        day_events = [e for e in snap.events_for(uid, ev.start - timedelta(hours=6), ev.start) if e.end <= ev.start and is_in_person(e)]
        origin = day_events[-1].location if day_events else HQ_LOCATION
        travel = travel_minutes(origin, ev.location)
        if travel > 0:
            leave_at = ev.start - timedelta(minutes=travel + 10)

    # --- prep -------------------------------------------------------------------------------------
    prep = PREP_BASE.get(ev.category, 0)
    why = [f"{category_label(ev.category)} meeting ({prep} min)"] if prep else []
    if prep:
        if score >= 80:
            prep += 15
            why.append(f"high priority {score}/100 (+15)")
        externals = [p for p in others if snap.people.get(p) is not None and snap.people[p].is_external]
        if externals and not _met_before(snap, uid, externals, ev):
            prep += 15
            why.append("first meeting with these external attendees (+15)")
        if ev.organizer_id == uid and len(others) >= 3:
            prep += 10
            why.append("you're running it (+10)")
        prep = min(prep, 60)
    if routine:
        mk("prep", ev.start - timedelta(minutes=5), "No prep needed",
           "Routine recurring meeting — Kairos stays quiet here to cut notification noise.", suppressed=True)
    elif prep:
        day = to_local(ev.start, tzname).date()
        deadline = leave_at or ev.start
        gaps = [g for g in _free_gaps(snap, uid, day, deadline) if (g[1] - g[0]).total_seconds() / 60 >= prep]
        where = ""
        if gaps:
            g = gaps[-1]
            fire = g[1] - timedelta(minutes=prep)
            where = f"your free gap {fmt_time(g[0], tzname)}–{fmt_time(g[1], tzname)}"
            if leave_at:
                where += f", before you leave at {fmt_time(leave_at, tzname)}"
        else:
            prev_day = day - timedelta(days=1)
            while prev_day.weekday() >= 5:
                prev_day -= timedelta(days=1)
            prev_gaps = [g for g in _free_gaps(snap, uid, prev_day, None) if (g[1] - g[0]).total_seconds() / 60 >= prep]
            if prev_gaps:
                g = prev_gaps[-1]
                fire = g[1] - timedelta(minutes=prep)
                where = f"the previous workday at {fmt_local(fire, tzname)} — no free {prep}-min gap before then on the day"
            else:
                fire = deadline - timedelta(minutes=prep)
                where = "right before the meeting — your calendar has no free gap"
        block_ops = [{
            "op": "create",
            "event": {
                "title": f"Prep: {ev.title}", "start": iso(fire), "end": iso(fire + timedelta(minutes=prep)),
                "organizer_id": uid, "attendees": [{"person_id": uid, "response": "accepted", "optional": False}],
                "kind": "prep", "category": "focus", "source": "ai", "ai_generated": True,
            },
        }]
        mk("prep", fire, f"Prep {prep} min for “{ev.title}”",
           f"{'; '.join(why)}. Placed in {where}.", {"type": "block_prep", "label": "Block prep time", "operations": block_ops})

    # --- leave now (in person) ----------------------------------------------------------------------
    if leave_at is not None:
        mk("leave", leave_at, f"Leave by {fmt_time(leave_at, tzname)} for “{ev.title}”",
           f"~{travel} min from {origin} to {ev.location} + 10 min buffer (production: live traffic).")

    # --- join (virtual) --------------------------------------------------------------------------------
    if ev.is_virtual:
        prev = [e for e in snap.events_for(uid, ev.start - timedelta(hours=2), ev.start, ("meeting",))
                if e.id != ev.id and ev.start - timedelta(minutes=5) <= e.end <= ev.start + timedelta(minutes=1)]
        if routine:
            mk("join", ev.start - timedelta(minutes=1), "Join reminder off", "You reliably join this recurring meeting on time.", suppressed=True)
        elif prev:
            mk("join", ev.start - timedelta(minutes=5), f"Wrap up “{prev[-1].title}” — next: {ev.title}",
               "Back-to-back meetings: a 5-minute heads-up instead of a pop-up at the start time.")
        else:
            mk("join", ev.start - timedelta(minutes=2), f"Join “{ev.title}”", "Virtual meeting starting in 2 minutes.")

    # --- follow-up ---------------------------------------------------------------------------------------
    if ev.category in FOLLOWUP_CATEGORIES and not routine:
        mk("followup", ev.end + timedelta(minutes=15), f"Send the recap for “{ev.title}”",
           "Decisions decay fast — Kairos drafted a recap with decisions, owners and dates.",
           {"type": "draft", "label": "Open recap draft", "kind": "recap", "draft": followup_recap(ev, snap, uid)})

    # Quiet hours: never ping outside them (leave-now is the exception: being late is worse).
    for r in out:
        if r.kind != "leave" and _in_quiet_hours(r.fire_at, snap, uid) and not r.suppressed:
            r.rationale += " (Falls in your quiet hours — delivered in the morning digest instead.)"
            r.channel = "digest"
    out.extend(_customs(ev, overrides))
    return out


def _customs(ev: Ev, overrides: dict[str, Any]) -> list[PlannedReminder]:
    c = overrides.get("custom")
    if not c or not c.minutes_before:
        return []
    fire = ev.start - timedelta(minutes=c.minutes_before)
    return [PlannedReminder(f"{ev.id}:custom", ev.id, ev.title, "custom", fire, c.message or f"Reminder: {ev.title}",
                            f"You asked for a reminder {c.minutes_before} min before.", bool(c.enabled))]


def upcoming(
    snap: Snapshot, uid: str, now: datetime, hours: int = 48, overrides_by_event: dict[str, dict[str, Any]] | None = None
) -> list[PlannedReminder]:
    overrides_by_event = overrides_by_event or {}
    out: list[PlannedReminder] = []
    for ev in snap.events_for(uid, now - timedelta(hours=1), now + timedelta(hours=hours)):
        for r in plan_event(snap, ev, uid, now, overrides_by_event.get(ev.id)):
            if r.enabled and not r.suppressed and r.fire_at >= now - timedelta(minutes=10) and r.fire_at <= now + timedelta(hours=hours):
                out.append(r)
    return sorted(out, key=lambda r: r.fire_at)


def digest(snap: Snapshot, uid: str, day: date, now: datetime, conflict_count: int = 0) -> dict[str, Any]:
    p = snap.person(uid)
    prefs = snap.pref(uid)
    ws = local_to_utc(day, parse_hhmm(p.work_start), p.timezone)
    we = local_to_utc(day, parse_hhmm(p.work_end), p.timezone)
    meetings = [e for e in snap.events_for(uid, ws - timedelta(hours=4), we + timedelta(hours=6), ("meeting",))
                if to_local(e.start, p.timezone).date() == day]
    meeting_min = sum(m.minutes for m in meetings)
    busy = snap.busy(uid, ws, we, include_focus=False)
    free = subtract((ws, we), busy.items)
    deep = sum((b - a).total_seconds() / 60 for a, b in free if (b - a).total_seconds() / 60 >= prefs.min_focus_block_min)
    preps = []
    for m in meetings:
        for r in plan_event(snap, m, uid, now):
            if r.kind == "prep" and not r.suppressed:
                preps.append({"event_id": m.id, "title": m.title, "at": iso(r.fire_at), "label": r.title})
    inperson = [m.title for m in meetings if is_in_person(m)]
    return {
        "date": day.isoformat(),
        "meeting_count": len(meetings),
        "meeting_hours": round(meeting_min / 60, 1),
        "first_meeting": fmt_time(meetings[0].start, p.timezone) if meetings else None,
        "deep_work_hours": round(deep / 60, 1),
        "prep": preps,
        "in_person": inperson,
        "conflicts": conflict_count,
        "headline": _headline(len(meetings), meeting_min, deep, conflict_count),
        "busy_blocks": len(IntervalSet((m.start, m.end) for m in meetings)),
    }


def _headline(n: int, meeting_min: float, deep: float, conflicts: int) -> str:
    if n == 0:
        return "No meetings — a full day for deep work."
    parts = [f"{n} meeting{'s' if n != 1 else ''} ({meeting_min / 60:.1f}h)"]
    parts.append(f"{deep / 60:.1f}h of deep-work time" if deep else "no deep-work block")
    if conflicts:
        parts.append(f"{conflicts} conflict{'s' if conflicts != 1 else ''} to resolve")
    return ", ".join(parts) + "."
