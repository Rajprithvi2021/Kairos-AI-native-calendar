"""Conflict detection and ranked resolution (F2).

Detects: overlap (double-booking), travel (impossible in-person sequence), focus (meeting inside a
protected focus block), overload (day above the user's meeting cap / 3h+ marathons) and
outside_hours. Each conflict gets up to 4 resolution options (at least one) ranked by
    score = value kept - 0.5 * disruption (people affected, weighted for short notice)
and every option carries concrete operations, so applying it is one audited, undoable step.
Moves are computed by the scheduler, so a resolution can never create a new double-booking.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.domain import drafts
from app.domain.calendar_data import Ev, Snapshot
from app.domain.classify import is_in_person, priority, travel_minutes
from app.domain.timeutils import fmt_local, fmt_time, iso, minutes_of, overlap_minutes, parse_hhmm, to_local
from app.engines.scheduler import SlotRequest, find_slots


@dataclass
class Option:
    id: str
    kind: str
    label: str
    description: str
    operations: list[dict[str, Any]]
    people_affected: int
    score: float
    reasons: list[str] = field(default_factory=list)
    draft: dict[str, str] | None = None
    preview: dict[str, Any] | None = None


@dataclass
class Conflict:
    id: str
    type: str
    severity: str
    title: str
    description: str
    event_ids: list[str]
    day: str
    starts_at: str
    options: list[Option] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TYPE_LABEL = {
    "overlap": "Double-booked",
    "travel": "Not enough travel time",
    "focus": "Meeting inside focus time",
    "overload": "Overloaded day",
    "outside_hours": "Outside your working hours",
}


def conflict_id(kind: str, ids: list[str]) -> str:
    return "cf_" + hashlib.sha1((kind + "|" + "+".join(sorted(ids))).encode()).hexdigest()[:10]


def _opt_id(cid: str, kind: str, n: int) -> str:
    return f"{cid}:{kind}:{n}"


def _score(value_kept: float, people: int, hours_until: float) -> float:
    urgency = 1.3 if hours_until < 24 else 1.0
    disruption = min(1.0, people * urgency / 10)
    return round(100 * (value_kept - 0.5 * disruption), 1)


def _others(ev: Ev, uid: str) -> list[str]:
    return [p for p in ev.participant_ids() if p != uid and (ev.attendee(p) is None or ev.attendee(p).response != "declined")]


def _best_move(snap: Snapshot, ev: Ev, uid: str, now: datetime, days: int = 5, exclude_day: date | None = None) -> Any:
    tzname = snap.people[uid].timezone
    req = SlotRequest(
        organizer_id=uid,
        attendee_ids=_others(ev, uid),
        duration_min=int(ev.minutes),
        window_start=max(now, ev.start - timedelta(days=1)),
        window_end=ev.start + timedelta(days=days),
        exclude_event_id=ev.id,
        max_results=6,
        min_notice_min=120,
    )
    res = find_slots(snap, req, now, snap.pref(uid).learned_weights, explore=False)
    slots = res.slots
    if exclude_day is not None:
        slots = [s for s in slots if to_local(s.start, tzname).date() != exclude_day]
    return slots[0] if slots else None


def detect_conflicts(
    snap: Snapshot, uid: str, start: datetime, end: datetime, now: datetime, *, with_options: bool = True
) -> list[Conflict]:
    user = snap.person(uid)
    prefs = snap.pref(uid)
    tzname = user.timezone
    evs = [e for e in snap.events_for(uid, start, end) if e.end > now]
    meetings = [e for e in evs if e.kind == "meeting"]
    focus_blocks = [e for e in evs if e.is_focus]
    out: list[Conflict] = []

    def add(kind: str, severity: str, title: str, desc: str, ids: list[str], first: Ev, builder: Any) -> None:
        cid = conflict_id(kind, ids)
        if cid in prefs.dismissed_conflicts:
            return
        c = Conflict(cid, kind, severity, title, desc, ids, to_local(first.start, tzname).date().isoformat(), iso(first.start) or "")
        if with_options:
            c.options = sorted(builder(c), key=lambda o: -o.score)[:4]
        out.append(c)

    # --- overlaps -------------------------------------------------------------------------------
    ms = sorted(meetings, key=lambda e: (e.start, e.end))
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            if b.start >= a.end:
                break
            ov = overlap_minutes(a.start, a.end, b.start, b.end)
            optional = a.is_optional_for(uid) or b.is_optional_for(uid)
            severity = "high" if ov >= 15 and not optional else ("medium" if not optional else "low")
            add(
                "overlap", severity, f"{a.title} × {b.title}",
                f"{fmt_local(max(a.start, b.start), tzname)}: {int(ov)} min overlap.",
                [a.id, b.id], min(a, b, key=lambda x: x.start),
                lambda c, a=a, b=b: _overlap_options(snap, c, a, b, uid, now),
            )

    # --- focus intrusions -------------------------------------------------------------------------
    for f in focus_blocks:
        for m in meetings:
            if m.start < f.end and f.start < m.end:
                add(
                    "focus", "medium", f"{m.title} inside “{f.title}”",
                    f"{fmt_local(m.start, tzname)}: {int(overlap_minutes(m.start, m.end, f.start, f.end))} min of protected focus time.",
                    [m.id, f.id], m, lambda c, m=m, f=f: _focus_options(snap, c, m, f, uid, now),
                )

    # --- travel ---------------------------------------------------------------------------------
    by_day: dict[date, list[Ev]] = defaultdict(list)
    for m in meetings:
        by_day[to_local(m.start, tzname).date()].append(m)
    for _day, items in sorted(by_day.items()):
        inperson = sorted([m for m in items if is_in_person(m)], key=lambda e: e.start)
        for a, b in zip(inperson, inperson[1:], strict=False):
            if b.start < a.end:
                continue  # already an overlap
            need = travel_minutes(a.location, b.location)
            gap = (b.start - a.end).total_seconds() / 60
            if need > gap:
                add(
                    "travel", "high" if need - gap >= 15 else "medium", f"{a.title} → {b.title}",
                    f"{a.location} → {b.location} takes ~{need} min but you have {int(gap)} min.",
                    [a.id, b.id], a, lambda c, a=a, b=b, need=need, gap=gap: _travel_options(snap, c, a, b, uid, now, need, gap),
                )

    # --- overload ---------------------------------------------------------------------------------
    cap = prefs.max_meeting_hours_day * 60
    for day, items in sorted(by_day.items()):
        total = sum(m.minutes for m in items if not m.is_optional_for(uid))
        if total > cap:
            ids = [m.id for m in sorted(items, key=lambda e: e.start)]
            add(
                "overload", "medium", f"{day:%a %b} {day.day}: {total / 60:.1f}h of meetings",
                f"Your cap is {cap / 60:g}h. Long meeting days leave no time to prepare or follow up.",
                ids, min(items, key=lambda e: e.start), lambda c, items=items, total=total: _overload_options(snap, c, items, uid, now, total, cap),
            )

    # --- outside working hours ----------------------------------------------------------------------
    ws, we = minutes_of(parse_hhmm(user.work_start)), minutes_of(parse_hhmm(user.work_end))
    for m in meetings:
        if m.is_optional_for(uid):
            continue  # optional invites outside hours aren't worth a notification
        ls, le = to_local(m.start, tzname), to_local(m.end, tzname)
        sm, em = ls.hour * 60 + ls.minute, le.hour * 60 + le.minute + (1440 if le.date() > ls.date() else 0)
        if sm < ws or em > we or ls.weekday() not in user.work_days:
            add(
                "outside_hours", "low", f"{m.title} at {fmt_time(m.start, tzname)}",
                f"Starts {fmt_local(m.start, tzname)}, outside your {user.work_start}–{user.work_end} working hours.",
                [m.id], m, lambda c, m=m: _outside_options(snap, c, m, uid, now),
            )

    sev = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda c: (c.starts_at, sev[c.severity]))


# --- option builders -------------------------------------------------------------------------------
def _hours_until(ev: Ev, now: datetime) -> float:
    return (ev.start - now).total_seconds() / 3600


def _move_option(snap: Snapshot, c: Conflict, ev: Ev, keep: Ev | None, uid: str, now: datetime, n: int, value: float = 0.92) -> Option | None:
    if ev.organizer_id != uid or not ev.is_movable:
        return None
    slot = _best_move(snap, ev, uid, now)
    if slot is None:
        return None
    reasons = list(slot.reasons[:2])
    if keep is not None:
        pk, pe = priority(keep, snap, uid)[0], priority(ev, snap, uid)[0]
        reasons.insert(0, f"Keeps “{keep.title}” (priority {pk} vs {pe})")
    people = len(_others(ev, uid))
    return Option(
        _opt_id(c.id, "move", n), "move", f"Move “{ev.title}” to {slot.label}",
        "Everyone on the invite is free at the new time.",
        [{"op": "update", "event_id": ev.id, "changes": {"start": iso(slot.start), "end": iso(slot.end)}}],
        people, _score(value + 0.05 * slot.score / 100, people, _hours_until(ev, now)), reasons, None,
        {"event_id": ev.id, "start": iso(slot.start), "end": iso(slot.end)},
    )


def _decline_option(snap: Snapshot, c: Conflict, ev: Ev, because: Ev | None, uid: str, now: datetime, n: int) -> Option:
    p = priority(ev, snap, uid)[0]
    if ev.organizer_id == uid:
        ops = [{"op": "delete", "event_id": ev.id}]
        label, desc = f"Cancel “{ev.title}”", "You organise it; attendees get a cancellation note."
        people = len(_others(ev, uid))
    else:
        ops = [{"op": "respond", "event_id": ev.id, "person_id": uid, "response": "declined"}]
        label, desc = f"Decline “{ev.title}”", "Kairos drafts a note asking for notes/recording."
        people = 0
    return Option(
        _opt_id(c.id, "decline", n), "decline", label, desc, ops, people,
        _score(1 - 0.9 * p / 100, people, _hours_until(ev, now)), [f"Lower priority for you ({p}/100)"],
        drafts.decline_note(ev, because, snap, uid),
    )


def _overlap_options(snap: Snapshot, c: Conflict, a: Ev, b: Ev, uid: str, now: datetime) -> list[Option]:
    pa, pb = priority(a, snap, uid)[0], priority(b, snap, uid)[0]
    keep, other = (a, b) if pa >= pb else (b, a)
    opts: list[Option] = []
    mv = _move_option(snap, c, other, keep, uid, now, 1) or _move_option(snap, c, keep, other, uid, now, 2, value=0.85)
    if mv:
        opts.append(mv)
    opts.append(_decline_option(snap, c, other, keep, uid, now, 1))
    if other.organizer_id != uid:
        opts.append(
            Option(
                _opt_id(c.id, "propose", 1), "propose_time", f"Ask {snap.people[other.organizer_id].first_name} to reschedule",
                "Marks you tentative and drafts a reschedule request.",
                [{"op": "respond", "event_id": other.id, "person_id": uid, "response": "tentative"}], 1,
                _score(0.7, 1, _hours_until(other, now)), ["You don't organise it"],
                drafts.reschedule_request(other, snap, uid),
            )
        )
    ov = overlap_minutes(a.start, a.end, b.start, b.end)
    first, second = (a, b) if a.start <= b.start else (b, a)
    if ov <= 15 and first.organizer_id == uid and first.end > second.start:
        new_end = second.start
        opts.append(
            Option(
                _opt_id(c.id, "shorten", 1), "shorten", f"End “{first.title}” {int(ov)} min early",
                "Small overlap: trim the earlier meeting you organise.",
                [{"op": "update", "event_id": first.id, "changes": {"end": iso(new_end)}}],
                len(_others(first, uid)), _score(0.85, len(_others(first, uid)), _hours_until(first, now)),
                ["Overlap is only a few minutes"],
            )
        )
    return opts


def _focus_options(snap: Snapshot, c: Conflict, m: Ev, f: Ev, uid: str, now: datetime) -> list[Option]:
    tzname = snap.people[uid].timezone
    opts: list[Option] = []
    req = SlotRequest(uid, [], int(f.minutes), max(now, f.start - timedelta(hours=12)), f.start + timedelta(days=3),
                      exclude_event_id=f.id, max_results=4, min_notice_min=60, granularity_min=30)
    res = find_slots(snap, req, now, None, explore=False)
    if res.slots:
        s = res.slots[0]
        opts.append(
            Option(
                _opt_id(c.id, "move_focus", 1), "move_focus", f"Move the focus block to {s.label}",
                "Keeps the meeting and re-protects the same amount of deep work.",
                [{"op": "update", "event_id": f.id, "changes": {"start": iso(s.start), "end": iso(s.end)}}],
                0, _score(0.9, 0, _hours_until(m, now)), ["No one else is affected", *s.reasons[:1]], None,
                {"event_id": f.id, "start": iso(s.start), "end": iso(s.end)},
            )
        )
    before = (m.start - f.start).total_seconds() / 60
    after = (f.end - m.end).total_seconds() / 60
    if max(before, after) >= 45:
        ns, ne = (f.start, m.start) if before >= after else (m.end, f.end)
        opts.append(
            Option(
                _opt_id(c.id, "trim_focus", 1), "trim_focus",
                f"Trim focus to {fmt_time(ns, tzname)}–{fmt_time(ne, tzname)}",
                "Keeps the longer part of the focus block.",
                [{"op": "update", "event_id": f.id, "changes": {"start": iso(ns), "end": iso(ne)}}],
                0, _score(0.72, 0, _hours_until(m, now)), [f"Keeps {int(max(before, after))} min of focus"],
            )
        )
    if m.organizer_id != uid:
        opts.append(_decline_option(snap, c, m, f, uid, now, 1))
    mv = _move_option(snap, c, m, f, uid, now, 1)
    if mv:
        opts.append(mv)
    return opts


def _travel_options(snap: Snapshot, c: Conflict, a: Ev, b: Ev, uid: str, now: datetime, need: int, gap: float) -> list[Option]:
    opts: list[Option] = []
    if b.organizer_id == uid:
        opts.append(
            Option(
                _opt_id(c.id, "virtual", 1), "virtual", f"Make “{b.title}” a video call",
                "You organise it; attendees get the updated location.",
                [{"op": "update", "event_id": b.id, "changes": {"is_virtual": True, "location": "Video call"}}],
                len(_others(b, uid)), _score(0.9, len(_others(b, uid)) // 2, _hours_until(b, now)), [f"Saves ~{need} min of travel"],
            )
        )
    else:
        opts.append(
            Option(
                _opt_id(c.id, "remote", 1), "remote_join", f"Join “{b.title}” by video",
                "Kairos drafts a heads-up to the organiser and marks this resolved.",
                [{"op": "dismiss_conflict", "person_id": uid, "conflict_id": c.id}], 1,
                _score(0.88, 1, _hours_until(b, now)), [f"Saves ~{need} min of travel", "Organiser keeps the in-person format"],
                drafts.remote_join_note(b, snap, uid, need),
            )
        )
    mv = _move_option(snap, c, b, a, uid, now, 1)
    if mv:
        opts.append(mv)
    opts.append(_decline_option(snap, c, b, a, uid, now, 1))
    return opts


def _overload_options(snap: Snapshot, c: Conflict, items: list[Ev], uid: str, now: datetime, total: float, cap: float) -> list[Option]:
    tzname = snap.people[uid].timezone
    day = to_local(items[0].start, tzname).date()
    # One-off internal meetings only: moving a single instance of a series, or a customer meeting,
    # is a bigger ask than a rebalance should make.
    movable = [m for m in items if m.organizer_id == uid and m.is_movable and m.start > now and not m.series_id
               and not any(snap.people[p].is_external for p in m.participant_ids() if p in snap.people)]
    movable.sort(key=lambda m: priority(m, snap, uid)[0])
    opts: list[Option] = []
    moves: list[tuple[Ev, Any]] = []
    for i, m in enumerate(movable[:3], 1):
        slot = _best_move(snap, m, uid, now, days=7, exclude_day=day)
        if slot is None:
            continue
        moves.append((m, slot))
        people = len(_others(m, uid))
        opts.append(
            Option(
                _opt_id(c.id, "move", i), "move", f"Move “{m.title}” to {slot.label}",
                f"Frees {int(m.minutes)} min on {day:%a}.",
                [{"op": "update", "event_id": m.id, "changes": {"start": iso(slot.start), "end": iso(slot.end)}}],
                people, _score(0.9, people, _hours_until(m, now)), [f"Lowest priority on {day:%a} ({priority(m, snap, uid)[0]}/100)", *slot.reasons[:1]],
                None, {"event_id": m.id, "start": iso(slot.start), "end": iso(slot.end)},
            )
        )
    if len(moves) >= 2:
        chosen, freed = [], 0.0
        for m, slot in moves:
            if total - freed <= cap:
                break
            chosen.append((m, slot))
            freed += m.minutes
        if len(chosen) >= 2:
            people = sum(len(_others(m, uid)) for m, _ in chosen)
            opts.append(
                Option(
                    _opt_id(c.id, "rebalance", 1), "rebalance",
                    f"Rebalance: move {len(chosen)} meetings to lighter days",
                    f"Brings {day:%a} to {(total - freed) / 60:.1f}h.",
                    [{"op": "update", "event_id": m.id, "changes": {"start": iso(s.start), "end": iso(s.end)}} for m, s in chosen],
                    people, _score(0.97, people // 2, 48), [f"{m.title} → {s.label}" for m, s in chosen],
                )
            )
    opts.append(
        Option(
            _opt_id(c.id, "keep", 1), "keep", "Keep the day as is", "Mark this day as an accepted exception.",
            [{"op": "dismiss_conflict", "person_id": uid, "conflict_id": c.id}], 0, _score(0.45, 0, 48), ["Sometimes a heavy day is unavoidable"],
        )
    )
    return opts


def _outside_options(snap: Snapshot, c: Conflict, m: Ev, uid: str, now: datetime) -> list[Option]:
    opts: list[Option] = []
    mv = _move_option(snap, c, m, None, uid, now, 1, value=0.9)
    if mv:
        mv.description = "Moves it into everyone's working hours."
        opts.append(mv)
    opts.append(
        Option(
            _opt_id(c.id, "keep", 1), "keep", "Keep as an exception", "Some cross-time-zone meetings need early starts.",
            [{"op": "dismiss_conflict", "person_id": uid, "conflict_id": c.id}], 0, _score(0.6, 0, 48), ["No one else is affected"],
        )
    )
    return opts


def conflict_flags(conflicts: list[Conflict]) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = defaultdict(list)
    for c in conflicts:
        for eid in c.event_ids if c.type != "overload" else []:
            flags[eid].append(c.type)
    return flags
