"""Time analytics (F4) and the meeting-necessity advisor (F7).

Everything is computed from the calendar alone (no surveillance of content): where time goes, what
meetings cost, how fragmented the week is, how much deep-work capacity is left, who carries the
time-zone burden, and which recurring meetings could be shorter, rarer or async.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from app.domain import drafts
from app.domain.calendar_data import CATEGORY_META, Ev, Snapshot
from app.domain.timeutils import (
    iso,
    local_midnight_utc,
    local_to_utc,
    minutes_of,
    overlap_minutes,
    parse_hhmm,
    subtract,
    to_local,
    week_start,
)


def _visible(ev: Ev, as_of: datetime | None) -> bool:
    return as_of is None or ev.created_at is None or ev.created_at <= as_of


def week_bounds(snap: Snapshot, uid: str, monday: date) -> tuple[datetime, datetime]:
    tzname = snap.person(uid).timezone
    return local_midnight_utc(monday, tzname), local_midnight_utc(monday + timedelta(days=7), tzname)


def deep_work_minutes(snap: Snapshot, uid: str, s: datetime, e: datetime, as_of: datetime | None = None) -> float:
    """Free time inside working hours in blocks >= the user's minimum focus block (focus blocks count as free)."""
    prefs = snap.pref(uid)
    busy_ev = [x for x in snap.events_for(uid, s, e, ("meeting", "personal")) if _visible(x, as_of)]
    from app.domain.timeutils import merge

    busy = merge((x.start, x.end) for x in busy_ev)
    total = 0.0
    for a, b in snap.working(uid, s, e).items:
        for fa, fb in subtract((a, b), busy):
            m = (fb - fa).total_seconds() / 60
            if m >= prefs.min_focus_block_min:
                total += m
    return total


def week_metrics(snap: Snapshot, uid: str, monday: date, as_of: datetime | None = None) -> dict[str, Any]:
    user = snap.person(uid)
    tzname = user.timezone
    s, e = week_bounds(snap, uid, monday)
    evs = [x for x in snap.events_for(uid, s, e) if _visible(x, as_of)]
    meetings = [x for x in evs if x.kind == "meeting"]
    focus = [x for x in evs if x.is_focus]
    by_cat: dict[str, float] = defaultdict(float)
    meeting_min = cost = 0.0
    after_hours = 0
    ws, we = minutes_of(parse_hhmm(user.work_start)), minutes_of(parse_hhmm(user.work_end))
    for m in meetings:
        mins = overlap_minutes(m.start, m.end, s, e)
        meeting_min += mins
        by_cat[m.category] += mins
        rate = sum(snap.people[p].hourly_rate for p in m.participant_ids() if p in snap.people and m.attending(p))
        cost += mins / 60 * rate
        ls = to_local(m.start, tzname)
        if ls.hour * 60 + ls.minute < ws or ls.hour * 60 + ls.minute + m.minutes > we or ls.weekday() >= 5:
            after_hours += 1
    for f in focus:
        by_cat["focus"] += overlap_minutes(f.start, f.end, s, e)
    ms = sorted(meetings, key=lambda x: x.start)
    b2b = sum(1 for a, b in zip(ms, ms[1:], strict=False) if 0 <= (b.start - a.end).total_seconds() < 300)
    frag_gaps = sum(1 for a, b in zip(ms, ms[1:], strict=False)
                    if to_local(a.end, tzname).date() == to_local(b.start, tzname).date() and 15 <= (b.start - a.end).total_seconds() / 60 < 60)
    workdays = max(1, sum(1 for d in range(7) if (monday + timedelta(days=d)).weekday() in user.work_days))
    deep = deep_work_minutes(snap, uid, s, e, as_of)
    return {
        "week_start": monday.isoformat(),
        "meeting_hours": round(meeting_min / 60, 2),
        "meeting_count": len(meetings),
        "focus_block_hours": round(by_cat.get("focus", 0) / 60, 2),
        "deep_work_hours": round(deep / 60, 2),
        "after_hours_meetings": after_hours,
        "back_to_back": b2b,
        "fragmentation": round(frag_gaps / workdays, 2),
        "cost": round(cost),
        "by_category": {k: round(v / 60, 2) for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])},
    }


def workload_signal(cur: dict[str, Any], baseline_hours: float) -> dict[str, Any]:
    score = (
        30
        + 4 * (cur["meeting_hours"] - baseline_hours)
        + 1.2 * cur["meeting_hours"]
        + 6 * cur["after_hours_meetings"]
        + 2 * cur["back_to_back"]
        - 0.5 * cur["deep_work_hours"]
    )
    score = max(0, min(100, round(score)))
    level = "healthy" if score < 40 else ("elevated" if score < 70 else "high")
    return {"score": score, "level": level, "note": "Calendar-based workload signal, not a wellbeing measure."}


def summary(snap: Snapshot, uid: str, now: datetime, weeks_back: int = 8, weeks_fwd: int = 4) -> dict[str, Any]:
    user = snap.person(uid)
    prefs = snap.pref(uid)
    tzname = user.timezone
    this_monday = week_start(to_local(now, tzname).date())
    weeks = []
    for k in range(-weeks_back, weeks_fwd + 1):
        monday = this_monday + timedelta(weeks=k)
        m = week_metrics(snap, uid, monday)
        m["phase"] = "past" if k < 0 else ("current" if k == 0 else "future")
        m["label"] = f"{monday:%b} {monday.day}"
        weeks.append(m)
    past = [w for w in weeks if w["phase"] == "past"]
    cur = next(w for w in weeks if w["phase"] == "current")
    last = past[-1] if past else cur
    base_h = statistics.mean(w["meeting_hours"] for w in past) if past else cur["meeting_hours"]
    base_deep = statistics.mean(w["deep_work_hours"] for w in past) if past else cur["deep_work_hours"]
    kpis = [
        {"id": "meeting_hours", "label": "Meeting hours this week", "value": cur["meeting_hours"], "baseline": round(base_h, 1), "unit": "h", "better": "lower"},
        {"id": "last_week_meetings", "label": "Meeting hours last week", "value": last["meeting_hours"], "baseline": round(base_h, 1), "unit": "h", "better": "lower"},
        {"id": "deep_work", "label": "Deep-work time available", "value": cur["deep_work_hours"], "baseline": round(base_deep, 1), "target": prefs.focus_goal_hours, "unit": "h", "better": "higher"},
        {"id": "fragmentation", "label": "Fragmenting gaps / day", "value": cur["fragmentation"], "baseline": round(statistics.mean(w["fragmentation"] for w in past), 2) if past else None, "unit": "", "better": "lower"},
        {"id": "after_hours", "label": "Outside-hours meetings", "value": cur["after_hours_meetings"], "baseline": round(statistics.mean(w["after_hours_meetings"] for w in past), 1) if past else None, "unit": "", "better": "lower"},
        {"id": "cost", "label": "Meeting cost this week", "value": cur["cost"], "baseline": round(statistics.mean(w["cost"] for w in past)) if past else None, "unit": "$", "better": "lower"},
    ]
    cats: dict[str, float] = defaultdict(float)
    for w in past[-4:]:
        for k, v in w["by_category"].items():
            cats[k] += v
    return {
        "user_timezone": tzname,
        "weeks": weeks,
        "kpis": kpis,
        "workload": workload_signal(cur, base_h),
        "categories": [
            {"category": k, "label": CATEGORY_META.get(k, CATEGORY_META["admin"])["label"], "color": CATEGORY_META.get(k, CATEGORY_META["admin"])["color"], "hours": round(v, 1)}
            for k, v in sorted(cats.items(), key=lambda kv: -kv[1])
        ],
        "heatmap": heatmap(snap, uid, now, weeks_back),
        "collaborators": collaborators(snap, uid, now),
        "fairness": fairness(snap, uid, now),
        "focus_goal_hours": prefs.focus_goal_hours,
        "last_week": last,
    }


def heatmap(snap: Snapshot, uid: str, now: datetime, weeks: int = 8) -> dict[str, Any]:
    tzname = snap.person(uid).timezone
    this_monday = week_start(to_local(now, tzname).date())
    s = local_midnight_utc(this_monday - timedelta(weeks=weeks), tzname)
    e = local_midnight_utc(this_monday, tzname)
    hours = list(range(7, 19))
    grid = [[0.0 for _ in hours] for _ in range(5)]
    for m in snap.events_for(uid, s, e, ("meeting",)):
        cur = m.start
        while cur < m.end:
            lt = to_local(cur, tzname)
            nxt = min(m.end, cur + timedelta(minutes=15))
            if lt.weekday() < 5 and lt.hour in hours:
                grid[lt.weekday()][hours.index(lt.hour)] += (nxt - cur).total_seconds() / 60
            cur = nxt
    return {"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "hours": hours,
            "minutes_per_week": [[round(v / weeks, 1) for v in row] for row in grid]}


def collaborators(snap: Snapshot, uid: str, now: datetime, days: int = 28) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    for m in snap.events_for(uid, now - timedelta(days=days), now, ("meeting",)):
        for p in m.participant_ids():
            if p != uid and p in snap.people and m.attending(p):
                totals[p] += m.minutes / 60
    out = []
    for pid, h in sorted(totals.items(), key=lambda kv: -kv[1])[:8]:
        p = snap.people[pid]
        out.append({"person_id": pid, "name": p.name, "title": p.title, "company": p.company, "hours": round(h, 1), "is_external": p.is_external})
    return out


def fairness(snap: Snapshot, uid: str, now: datetime, back_days: int = 28, fwd_days: int = 14) -> list[dict[str, Any]]:
    """Who carries the time-zone burden of meetings with the user?"""
    out: dict[str, dict[str, Any]] = {}
    for m in snap.events_for(uid, now - timedelta(days=back_days), now + timedelta(days=fwd_days), ("meeting",)):
        for pid in m.participant_ids():
            p = snap.people.get(pid)
            if p is None or pid == uid or p.is_external or not m.attending(pid):
                continue
            lt = to_local(m.start, p.timezone)
            sm = lt.hour * 60 + lt.minute
            ws, we = minutes_of(parse_hhmm(p.work_start)), minutes_of(parse_hhmm(p.work_end))
            if sm < ws or sm + m.minutes > we:
                rec = out.setdefault(pid, {"person_id": pid, "name": p.name, "city": p.city, "timezone": p.timezone, "count": 0, "examples": [], "series": set()})
                rec["count"] += 1
                if m.series_id:
                    rec["series"].add(m.title)
                hour = lt.hour % 12 or 12
                example = f"{m.title} at {hour}:{lt:%M} {'AM' if lt.hour < 12 else 'PM'} local"
                if len(rec["examples"]) < 3 and example not in rec["examples"]:
                    rec["examples"].append(example)
    res = []
    for rec in sorted(out.values(), key=lambda r: -r["count"]):
        rec["series"] = sorted(rec["series"])
        res.append(rec)
    return res


# --- F7: recurring-meeting audit -----------------------------------------------------------------
def _round_duration(minutes: float) -> int:
    for d in (15, 20, 25, 30, 45, 50, 60, 90):
        if d >= minutes:
            return d
    return int(minutes)


def recurring_audit(snap: Snapshot, uid: str, now: datetime) -> list[dict[str, Any]]:
    user = snap.person(uid)
    out = []
    for series in snap.series.values():
        if series.category == "focus":
            continue
        inst = [e for e in snap.events if e.series_id == series.id and uid in e.participant_ids()]
        if not inst:
            continue
        past = [e for e in inst if now - timedelta(days=28) <= e.start < now]
        upcoming = [e for e in inst if e.start > now]
        per_month = len(past) * 30 / 28 if past else len(upcoming[:4])
        sample = (past or upcoming)[0]
        internal = [p for p in sample.participant_ids() if p in snap.people and not snap.people[p].is_external]
        rate = sum(snap.people[p].hourly_rate for p in internal)
        hours_month = per_month * series.duration_min / 60
        cost_month = hours_month * rate
        suggestion = {"kind": "keep", "label": "Keep as is", "detail": "Well used and right-sized.", "saves_hours_month": 0.0, "saves_cost_month": 0}
        unfair = [snap.people[p].first_name for p in internal if p != uid and _outside(snap, p, sample)]
        if series.user_optional and (series.user_attendance_rate or 1) < 0.6:
            suggestion = {"kind": "async", "label": "Follow asynchronously",
                          "detail": f"You're optional and attend {round((series.user_attendance_rate or 0) * 100)}% of the time; read the notes instead.",
                          "saves_hours_month": round(hours_month, 1), "saves_cost_month": round(hours_month * user.hourly_rate)}
        elif series.avg_actual_min and series.avg_actual_min <= 0.8 * series.duration_min:
            new = _round_duration(series.avg_actual_min + 5)
            if new < series.duration_min:
                saved = per_month * (series.duration_min - new) / 60
                suggestion = {"kind": "shorten", "label": f"Shorten to {new} min", "new_duration": new,
                              "detail": f"It usually wraps after ~{int(series.avg_actual_min)} of {series.duration_min} min.",
                              "saves_hours_month": round(saved * len(internal), 1), "saves_cost_month": round(saved * rate)}
        elif unfair:
            suggestion = {"kind": "rotate", "label": "Rotate the time",
                          "detail": f"Always outside working hours for {', '.join(unfair)}; alternate early/late slots monthly.",
                          "saves_hours_month": 0.0, "saves_cost_month": 0}
        out.append({
            "series_id": series.id, "title": series.title, "cadence": series.cadence, "duration_min": series.duration_min,
            "attendees": len(sample.participant_ids()), "organizer_id": series.organizer_id, "you_organize": series.organizer_id == uid,
            "per_month": round(per_month, 1), "hours_month": round(hours_month, 1), "cost_month": round(cost_month),
            "avg_actual_min": series.avg_actual_min, "attendance_rate": series.user_attendance_rate, "optional": series.user_optional,
            "unfair_for": unfair, "suggestion": suggestion, "upcoming": len(upcoming),
        })
    return sorted(out, key=lambda r: (-r["suggestion"]["saves_cost_month"], -r["cost_month"]))


def _outside(snap: Snapshot, pid: str, ev: Ev) -> bool:
    p = snap.people[pid]
    lt = to_local(ev.start, p.timezone)
    sm = lt.hour * 60 + lt.minute
    return sm < minutes_of(parse_hhmm(p.work_start)) or sm + ev.minutes > minutes_of(parse_hhmm(p.work_end))


def series_action_ops(snap: Snapshot, uid: str, series_id: str, now: datetime) -> dict[str, Any]:
    """Concrete operations + message draft for the audit suggestion of one series."""
    audit = {a["series_id"]: a for a in recurring_audit(snap, uid, now)}
    if series_id not in audit:
        raise KeyError(series_id)
    a = audit[series_id]
    sug = a["suggestion"]
    upcoming = sorted([e for e in snap.events if e.series_id == series_id and e.start > now and uid in e.participant_ids()],
                      key=lambda e: e.start)
    me = snap.person(uid).first_name
    ops: list[dict[str, Any]] = []
    draft = None
    if sug["kind"] == "shorten" and a["you_organize"]:
        new = sug["new_duration"]
        ops = [{"op": "update", "event_id": e.id, "changes": {"end": iso(e.start + timedelta(minutes=new))}} for e in upcoming]
        draft = drafts.shorten_series_note(a["title"], a["duration_min"], new, me)
    elif sug["kind"] == "async":
        ops = [{"op": "respond", "event_id": e.id, "person_id": uid, "response": "declined"} for e in upcoming]
        draft = drafts.async_update_note(a["title"], snap.person(a["organizer_id"]).first_name, me)
    return {"series": a, "operations": ops, "draft": draft}


def work_bounds_utc(snap: Snapshot, uid: str, day: date) -> tuple[datetime, datetime]:
    p = snap.person(uid)
    return local_to_utc(day, parse_hhmm(p.work_start), p.timezone), local_to_utc(day, parse_hhmm(p.work_end), p.timezone)
