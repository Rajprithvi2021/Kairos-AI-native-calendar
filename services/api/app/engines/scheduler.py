"""Intelligent scheduling (F1) + preference learning (F8).

Pipeline: candidate generation -> hard-constraint filter -> weighted, explainable scoring ->
diverse top-k -> (if needed) a relaxation ladder that says exactly what would have to give.

Hard constraints (never violated): every required attendee is inside working hours (optionally
stretched), nobody is double-booked, minimum notice, organiser's no-meeting days, explicit
time-of-day limits, and the organiser's protected focus blocks (unless the user relaxes it).
"""

from __future__ import annotations

import math
import time as _time
from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.domain.calendar_data import Ev, Snapshot
from app.domain.timeutils import (
    IntervalSet,
    fmt_local,
    fmt_time,
    iso,
    minutes_of,
    parse_hhmm,
    subtract,
    to_local,
    tz_abbrev,
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "fairness": 0.24,
    "focus": 0.22,
    "preference": 0.14,
    "batching": 0.10,
    "day_load": 0.10,
    "soonness": 0.10,
    "optional": 0.05,
    "lunch": 0.05,
}

COMPONENT_LABELS: dict[str, str] = {
    "fairness": "Time-zone fairness",
    "focus": "Focus time preserved",
    "preference": "Your preferred time of day",
    "batching": "Meeting batching",
    "day_load": "Light day",
    "soonness": "Sooner",
    "optional": "Optional attendees can join",
    "lunch": "Lunch protected",
}


@dataclass
class SlotRequest:
    organizer_id: str
    attendee_ids: list[str] = field(default_factory=list)
    duration_min: int = 30
    window_start: datetime | None = None
    window_end: datetime | None = None
    optional_ids: list[str] = field(default_factory=list)
    preferred_period: str = "any"  # any | morning | afternoon
    earliest_local: str | None = None  # HH:MM, organiser's time zone
    latest_local: str | None = None
    respect_focus: bool = True
    exclude_event_id: str | None = None  # when rescheduling an existing event
    min_notice_min: int = 60
    granularity_min: int = 15
    max_results: int = 5
    stretch_hours_min: int = 0
    allow_no_meeting_days: bool = False

    def required(self) -> list[str]:
        return list(dict.fromkeys([self.organizer_id, *self.attendee_ids]))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["window_start"] = iso(self.window_start)
        d["window_end"] = iso(self.window_end)
        return d


@dataclass
class AttendeeLocal:
    person_id: str
    name: str
    timezone: str
    tz_abbr: str
    local_label: str
    comfort: float
    status: str  # core | edge | outside
    optional: bool = False
    available: bool = True


@dataclass
class Slot:
    start: datetime
    end: datetime
    score: float
    components: dict[str, float]
    reasons: list[str]
    warnings: list[str]
    attendees: list[AttendeeLocal]
    label: str = ""
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["start"], d["end"] = iso(self.start), iso(self.end)
        d["score"] = round(self.score, 1)
        d["components"] = {k: round(v, 3) for k, v in self.components.items()}
        return d


@dataclass
class Relaxation:
    kind: str
    label: str
    description: str
    patch: dict[str, Any]
    slot_count: int
    preview: str = ""


@dataclass
class SlotResult:
    slots: list[Slot]
    relaxations: list[Relaxation]
    stats: dict[str, Any]
    request: SlotRequest

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": [s.to_dict() for s in self.slots],
            "relaxations": [asdict(r) for r in self.relaxations],
            "stats": self.stats,
            "request": self.request.to_dict(),
        }


@dataclass
class _PersonCtx:
    person: Any
    busy: IntervalSet
    work: IntervalSet
    free: IntervalSet  # meeting-free time inside normal working hours (focus blocks count as free)
    ws: int
    we: int


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    w = {k: max(0.0, float((weights or {}).get(k, v))) for k, v in DEFAULT_WEIGHTS.items()}
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def comfort(start_min: int, end_min: int, ws: int, we: int) -> float:
    """1.0 inside core hours (an hour in from either edge), lower at the edges, ~0 far outside."""
    core_s, core_e = ws + 60, we - 60
    if start_min >= core_s and end_min <= core_e:
        return 1.0
    if start_min >= ws and end_min <= we:
        d = max(core_s - start_min, 0) + max(end_min - core_e, 0)
        return max(0.55, 1 - 0.45 * min(d, 60) / 60)
    d = max(ws - start_min, 0) + max(end_min - we, 0)
    return max(0.0, 0.5 - 0.5 * min(d, 180) / 180)


def _ceil_to(dt: datetime, granularity_min: int) -> datetime:
    step = granularity_min * 60
    ts = math.ceil(dt.timestamp() / step) * step
    return datetime.fromtimestamp(ts, UTC)


def _deep(minutes: float, min_block: int) -> float:
    return minutes if minutes >= min_block else 0.0


def _focus_loss(pc: _PersonCtx, s: datetime, e: datetime, min_block: int) -> tuple[float, float]:
    """(deep-work minutes lost, deep minutes of the block hit)."""
    block = pc.free.block_containing(s, e)
    if block is None:
        return 0.0, 0.0
    total = (block[1] - block[0]).total_seconds() / 60
    left = (s - block[0]).total_seconds() / 60
    right = (block[1] - e).total_seconds() / 60
    before = _deep(total, min_block)
    return before - _deep(left, min_block) - _deep(right, min_block), before


def find_slots(
    snap: Snapshot,
    req: SlotRequest,
    now: datetime,
    weights: dict[str, float] | None = None,
    *,
    explore: bool = True,
) -> SlotResult:
    t0 = _time.perf_counter()
    w = normalize_weights(weights)
    org = snap.person(req.organizer_id)
    prefs = snap.pref(req.organizer_id)
    dur = timedelta(minutes=req.duration_min)
    win_s = req.window_start or now
    win_e = req.window_end or (now + timedelta(days=7))
    start_bound = max(win_s, now + timedelta(minutes=req.min_notice_min))
    req = replace(req, window_start=win_s, window_end=win_e)
    stats: dict[str, Any] = {"candidates": 0, "feasible": 0}
    if win_e - start_bound < dur:
        stats["elapsed_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
        return SlotResult([], [], stats, req)

    excl = {req.exclude_event_id} if req.exclude_event_id else set()
    pad = timedelta(days=1)
    lo, hi = win_s - pad, win_e + pad
    min_block = prefs.min_focus_block_min

    ctx: dict[str, _PersonCtx] = {}
    for pid in req.required():
        p = snap.person(pid)
        include_focus = not (pid == req.organizer_id and not req.respect_focus)
        busy = snap.busy(pid, lo, hi, include_focus=include_focus, exclude_ids=excl)
        work = snap.working(pid, lo, hi, req.stretch_hours_min)
        normal = snap.working(pid, lo, hi) if req.stretch_hours_min else work
        meetings = snap.busy(pid, lo, hi, include_focus=False, exclude_ids=excl)
        free: list[tuple[datetime, datetime]] = []
        for a, b in normal.items:
            free.extend(subtract((a, b), meetings.items))
        ctx[pid] = _PersonCtx(
            p, busy, work, IntervalSet(free), minutes_of(parse_hhmm(p.work_start)), minutes_of(parse_hhmm(p.work_end))
        )
    opt_busy = {
        pid: snap.busy(pid, lo, hi, exclude_ids=excl)
        for pid in req.optional_ids
        if pid in snap.people and pid not in ctx
    }
    org_days: dict[date, list[Ev]] = defaultdict(list)
    for ev in snap.events_for(req.organizer_id, lo, hi, ("meeting",)):
        if ev.id not in excl:
            org_days[to_local(ev.start, org.timezone).date()].append(ev)

    lunch_s, lunch_e = minutes_of(parse_hhmm(prefs.lunch_start)), minutes_of(parse_hhmm(prefs.lunch_end))
    earliest = minutes_of(parse_hhmm(req.earliest_local)) if req.earliest_local else None
    latest = minutes_of(parse_hhmm(req.latest_local)) if req.latest_local else None
    period = req.preferred_period if req.preferred_period != "any" else prefs.preferred_period
    cap = prefs.max_meeting_hours_day * 60

    scored: list[Slot] = []
    step = timedelta(minutes=req.granularity_min)
    for a, b in ctx[org.id].work.items:
        s = _ceil_to(max(a, start_bound), req.granularity_min)
        while s + dur <= min(b, win_e):
            e = s + dur
            stats["candidates"] += 1
            loc = to_local(s, org.timezone)
            sm = loc.hour * 60 + loc.minute
            em = sm + req.duration_min
            ok = not (not req.allow_no_meeting_days and loc.weekday() in prefs.no_meeting_days)
            ok = ok and (earliest is None or sm >= earliest) and (latest is None or em <= latest)
            if ok:
                for pc in ctx.values():
                    if not pc.work.contains(s, e) or pc.busy.overlaps(s, e):
                        ok = False
                        break
            if ok:
                stats["feasible"] += 1
                scored.append(
                    _score(snap, req, s, e, ctx, opt_busy, org_days, w, start_bound, min_block, period, cap, lunch_s, lunch_e)
                )
            s += step

    picked = _diversify(scored, req.max_results, org.timezone)
    if picked:
        earliest_slot = min(picked, key=lambda x: x.start)
        earliest_slot.reasons.append("Earliest good option")
    for i, sl in enumerate(picked, 1):
        sl.rank = i

    relaxations: list[Relaxation] = []
    if explore and len(picked) < 3:
        relaxations = _relaxations(snap, req, now, weights, has_slots=bool(picked))
    stats["elapsed_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    return SlotResult(picked, relaxations, stats, req)


def _score(
    snap: Snapshot,
    req: SlotRequest,
    s: datetime,
    e: datetime,
    ctx: dict[str, _PersonCtx],
    opt_busy: dict[str, IntervalSet],
    org_days: dict[date, list[Ev]],
    w: dict[str, float],
    start_bound: datetime,
    min_block: int,
    period: str,
    cap: float,
    lunch_s: int,
    lunch_e: int,
) -> Slot:
    org_id = req.organizer_id
    org = ctx[org_id].person
    dur_min = req.duration_min
    reasons: list[str] = []
    warnings: list[str] = []

    # 1) Time-zone fairness: protect the worst-off attendee (max-min), not just the average.
    locals_: list[AttendeeLocal] = []
    comforts: list[float] = []
    for pid, pc in ctx.items():
        lt = to_local(s, pc.person.timezone)
        smin = lt.hour * 60 + lt.minute
        c = comfort(smin, smin + dur_min, pc.ws, pc.we)
        comforts.append(c)
        status = "core" if c >= 0.999 else ("edge" if c >= 0.55 else "outside")
        locals_.append(
            AttendeeLocal(
                pid,
                pc.person.name,
                pc.person.timezone,
                tz_abbrev(s, pc.person.timezone),
                fmt_local(s, pc.person.timezone),
                round(c, 2),
                status,
            )
        )
    fairness = 0.6 * min(comforts) + 0.4 * (sum(comforts) / len(comforts))
    if fairness >= 0.999:
        reasons.append("Inside everyone's core working hours")
    elif min(comforts) >= 0.55:
        reasons.append("Within everyone's working hours")
    for al in locals_:
        if al.status == "outside":
            warnings.append(f"{al.name}: {al.local_label} {al.tz_abbr} - outside working hours")
        elif al.status == "edge" and al.person_id != org_id:
            warnings.append(f"{al.name}: {al.local_label} {al.tz_abbr} - edge of their day")

    # 2) Focus preservation (deep-work blocks >= min_block minutes).
    loss_org, deep_org = _focus_loss(ctx[org_id], s, e, min_block)
    org_focus = 1 - loss_org / deep_org if deep_org > 0 else 1.0
    others = []
    for pid, pc in ctx.items():
        if pid == org_id:
            continue
        loss, deep = _focus_loss(pc, s, e, min_block)
        others.append(1 - loss / deep if deep > 0 else 1.0)
        if loss >= 60:
            warnings.append(f"Breaks up a 90+ min free block for {pc.person.first_name}")
    focus = 0.6 * org_focus + 0.4 * (sum(others) / len(others)) if others else org_focus
    if loss_org == 0:
        reasons.append("Keeps your longer focus blocks intact")
    else:
        warnings.append(f"Uses {int(loss_org)} min of your deep-work time")

    # 3) Organiser's preferred time of day.
    lt = to_local(s, org.timezone)
    sm = lt.hour * 60 + lt.minute
    em = sm + dur_min
    if period == "morning":
        pref = 1.0 if em <= 12 * 60 + 30 else 0.35
    elif period == "afternoon":
        pref = 1.0 if sm >= 12 * 60 else 0.35
    else:
        pref = 1.0
    if period != "any" and pref == 1.0:
        reasons.append(f"Matches your preference for {period}s")

    # 4) Batching: sit next to existing meetings with a small buffer, avoid 3h+ marathons.
    day_meetings = sorted(org_days.get(lt.date(), []), key=lambda x: x.start)
    prev = max((m for m in day_meetings if m.end <= s), key=lambda m: m.end, default=None)
    nxt = min((m for m in day_meetings if m.start >= e), key=lambda m: m.start, default=None)
    gaps = []
    if prev:
        gaps.append(((s - prev.end).total_seconds() / 60, prev))
    if nxt:
        gaps.append(((nxt.start - e).total_seconds() / 60, nxt))
    prefs = snap.pref(org_id)
    if not gaps:
        batching = 0.45
    else:
        gap, neighbour = min(gaps, key=lambda g: g[0])
        if gap > 90:
            batching = 0.45
        elif gap < prefs.buffer_min:
            batching = 0.75
            warnings.append(f"Back-to-back with “{neighbour.title}”")
        elif gap <= 30:
            batching = 1.0
            reasons.append(f"Batched next to “{neighbour.title}” with a {int(gap)}-min buffer")
        else:
            batching = 0.6
    streak_s, streak_e = s, e
    for m in sorted(day_meetings, key=lambda x: x.start, reverse=True):
        if m.end <= streak_s and (streak_s - m.end).total_seconds() < 600:
            streak_s = m.start
    for m in day_meetings:
        if m.start >= streak_e and (m.start - streak_e).total_seconds() < 600:
            streak_e = m.end
    if (streak_e - streak_s).total_seconds() / 60 > 180:
        batching *= 0.4
        warnings.append("Creates 3h+ of back-to-back meetings")

    # 5) Day load vs the user's daily cap.
    load = sum(m.minutes for m in day_meetings)
    day_load = max(0.0, 1 - load / cap) if cap > 0 else 1.0
    if load + dur_min > cap:
        day_load *= 0.5
        warnings.append(f"Pushes {lt:%a} to {(load + dur_min) / 60:.1f}h of meetings (your cap is {cap / 60:g}h)")
    elif load <= 120:
        reasons.append(f"Light day for you ({load / 60:.1f}h of meetings)")

    # 6) Sooner is mildly better.
    soonness = math.exp(-((s - start_bound).total_seconds() / 86400) / 4)

    # 7) Optional attendees.
    if req.optional_ids:
        avail = [pid for pid, b in opt_busy.items() if not b.overlaps(s, e)]
        optional = len(avail) / max(1, len(req.optional_ids))
        for pid in req.optional_ids:
            if pid in snap.people:
                p = snap.people[pid]
                locals_.append(
                    AttendeeLocal(
                        pid, p.name, p.timezone, tz_abbrev(s, p.timezone), fmt_local(s, p.timezone), 1.0, "core",
                        optional=True, available=pid in avail,
                    )
                )
        reasons.append(f"{len(avail)}/{len(req.optional_ids)} optional attendees can join")
    else:
        optional = 1.0

    # 8) Lunch.
    lunch = 0.2 if (sm < lunch_e and em > lunch_s) else 1.0
    if lunch < 1:
        warnings.append("Overlaps your lunch")

    components = {
        "fairness": fairness,
        "focus": focus,
        "preference": pref,
        "batching": batching,
        "day_load": day_load,
        "soonness": soonness,
        "optional": optional,
        "lunch": lunch,
    }
    score = 100 * sum(w[k] * components[k] for k in w)
    label = f"{fmt_local(s, org.timezone)} - {fmt_time(e, org.timezone)}"
    return Slot(s, e, score, components, reasons, warnings, locals_, label)


def _diversify(scored: list[Slot], k: int, tzname: str) -> list[Slot]:
    """Greedy max-score selection that spreads options across days/times (MMR-style)."""
    ranked = sorted(scored, key=lambda x: (-x.score, x.start))
    picked: list[Slot] = []
    per_day: dict[date, int] = defaultdict(int)
    for c in ranked:
        d = to_local(c.start, tzname).date()
        if per_day[d] >= 2:
            continue
        if any(to_local(p.start, tzname).date() == d and abs((p.start - c.start).total_seconds()) < 90 * 60 for p in picked):
            continue
        picked.append(c)
        per_day[d] += 1
        if len(picked) == k:
            return picked
    for c in ranked:  # top up if diversity rules were too strict
        if len(picked) == k:
            break
        if c not in picked:
            picked.append(c)
    return sorted(picked, key=lambda x: -x.score)


def _relaxations(
    snap: Snapshot, req: SlotRequest, now: datetime, weights: dict[str, float] | None, has_slots: bool
) -> list[Relaxation]:
    out: list[Relaxation] = []

    def attempt(kind: str, label: str, desc: str, **patch: Any) -> SlotResult | None:
        res = find_slots(snap, replace(req, **patch), now, weights, explore=False)
        if res.slots:
            ser = {k: (iso(v) if isinstance(v, datetime) else v) for k, v in patch.items()}
            out.append(Relaxation(kind, label, desc, ser, len(res.slots), res.slots[0].label))
        return res

    if req.duration_min >= 30:
        attempt(
            "shorter",
            f"Shorten to {req.duration_min - 15} min",
            "A shorter meeting fits more gaps; keep the agenda tight.",
            duration_min=req.duration_min - 15,
        )
    if req.earliest_local or req.latest_local:
        attempt("time_limits", "Drop the time-of-day limit", "Consider the whole working day.", earliest_local=None, latest_local=None)
    if req.respect_focus:
        attempt("focus", "Allow booking over your focus blocks", "Kairos will offer to re-protect the focus time elsewhere.", respect_focus=False)
    assert req.window_end is not None
    attempt("window", "Look one more week", "Widen the search window by 7 days.", window_end=req.window_end + timedelta(days=7))
    for stretch in (60, 120, 180):
        res = find_slots(snap, replace(req, stretch_hours_min=stretch), now, weights, explore=False)
        if res.slots:
            top = res.slots[0]
            who = ", ".join(f"{a.name.split(' ')[0]} {a.local_label} {a.tz_abbr}" for a in top.attendees if a.status != "core" and not a.optional)
            out.append(
                Relaxation(
                    "stretch",
                    f"Stretch working hours by up to {stretch // 60}h",
                    f"No shared working hours exist; Kairos splits the inconvenience fairly ({who}).",
                    {"stretch_hours_min": stretch},
                    len(res.slots),
                    top.label,
                )
            )
            break
    return out


# --- F8: learning from choices --------------------------------------------------------------
def learn_weights(
    current: dict[str, float] | None,
    chosen: dict[str, float],
    shown: list[dict[str, float]],
    lr: float = 0.08,
) -> dict[str, float]:
    """Pairwise perceptron update: when the user picks a lower-ranked slot, shift weight towards
    the components where the chosen slot beat the ones ranked above it. Bounded and normalised."""
    w = normalize_weights(current)

    def dot(c: dict[str, float]) -> float:
        return sum(w[k] * c.get(k, 0.0) for k in w)

    chosen_score = dot(chosen)
    for other in shown:
        if other is chosen or other == chosen:
            continue
        if dot(other) >= chosen_score:
            for k in w:
                w[k] += lr * (chosen.get(k, 0.0) - other.get(k, 0.0))
    w = {k: min(0.6, max(0.02, v)) for k, v in w.items()}
    return normalize_weights(w)


def explain_weights(weights: dict[str, float] | None) -> list[dict[str, Any]]:
    w = normalize_weights(weights)
    out = []
    for k, v in w.items():
        delta = v - DEFAULT_WEIGHTS[k]
        out.append({"component": k, "label": COMPONENT_LABELS[k], "weight": round(v, 3), "delta": round(delta, 3)})
    return sorted(out, key=lambda x: -abs(x["delta"]))
