"""Focus guardian (F5): protect deep-work time and defragment the week.

- protect: place focus blocks in the largest free stretches until the weekly goal is met
  (one block per day first, mornings preferred - spread beats one giant block).
- defrag:  local search over meetings the user organises; greedily move the one whose relocation
  frees the most deep-work time (blocks >= the user's minimum), never creating conflicts (moves
  come from the scheduler), and stop when the gain is < 30 minutes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.domain.calendar_data import Snapshot
from app.domain.timeutils import fmt_local, fmt_time, iso, local_midnight_utc, subtract, to_local
from app.engines.analytics import deep_work_minutes
from app.engines.scheduler import SlotRequest, find_slots


def _week(snap: Snapshot, uid: str, monday: date) -> tuple[datetime, datetime]:
    tz = snap.person(uid).timezone
    return local_midnight_utc(monday, tz), local_midnight_utc(monday + timedelta(days=7), tz)


def plan_protection(snap: Snapshot, uid: str, monday: date, now: datetime, goal_hours: float | None = None) -> dict[str, Any]:
    prefs = snap.pref(uid)
    tzname = snap.person(uid).timezone
    goal = goal_hours if goal_hours is not None else prefs.focus_goal_hours
    s, e = _week(snap, uid, monday)
    start = max(s, now + timedelta(hours=1))
    existing = sum((min(f.end, e) - max(f.start, s)).total_seconds() / 3600 for f in snap.events_for(uid, s, e, ("focus", "prep")))
    need = max(0.0, goal - existing) * 60
    candidates = []
    busy = snap.busy(uid, s, e, include_focus=True)
    for a, b in snap.working(uid, start, e).items:
        for fa, fb in subtract((a, b), busy.items):
            mins = (fb - fa).total_seconds() / 60
            if mins >= prefs.min_focus_block_min:
                candidates.append((fa, fb, mins))
    # Prefer one block per day, longest first, mornings break ties.
    candidates.sort(key=lambda c: (-min(c[2], 180), to_local(c[0], tzname).hour))
    chosen, used_days = [], set()
    for pass_no in (0, 1):
        for fa, _fb, mins in candidates:
            if need <= 0:
                break
            day = to_local(fa, tzname).date()
            if pass_no == 0 and day in used_days:
                continue
            if any(c[0] == fa for c in chosen):
                continue
            length = min(mins, 180, max(prefs.min_focus_block_min, need))
            length = int(length // 15 * 15)
            chosen.append((fa, fa + timedelta(minutes=length)))
            used_days.add(day)
            need -= length
    ops = [{
        "op": "create",
        "event": {
            "title": "Focus: deep work (protected by Kairos)", "start": iso(a), "end": iso(b), "organizer_id": uid,
            "attendees": [{"person_id": uid, "response": "accepted", "optional": False}], "kind": "focus",
            "category": "focus", "source": "ai", "ai_generated": True, "is_movable": True,
        },
    } for a, b in chosen]
    added = sum((b - a).total_seconds() / 3600 for a, b in chosen)
    return {
        "week_start": monday.isoformat(),
        "goal_hours": goal,
        "existing_hours": round(existing, 1),
        "added_hours": round(added, 1),
        "blocks": [{"start": iso(a), "end": iso(b), "label": f"{fmt_local(a, tzname)} - {fmt_time(b, tzname)}"} for a, b in chosen],
        "operations": ops,
        "goal_met": existing + added >= goal - 1e-6,
    }


def plan_defrag(snap: Snapshot, uid: str, monday: date, now: datetime, max_moves: int = 4) -> dict[str, Any]:
    tzname = snap.person(uid).timezone
    s, e = _week(snap, uid, monday)
    earliest = max(s, now + timedelta(hours=24))
    work = Snapshot(snap.people, snap.prefs, [x for x in snap.clone().events if x.end > s - timedelta(days=1) and x.start < e + timedelta(days=1)], snap.series)

    def deep() -> float:
        return deep_work_minutes(work, uid, s, e)

    before = deep()
    moves: list[dict[str, Any]] = []
    moved: set[str] = set()
    for _ in range(max_moves):
        current = deep()
        best: tuple[float, Any, Any] | None = None
        movable = [m for m in work.events_for(uid, earliest, e, ("meeting",))
                   if m.organizer_id == uid and m.is_movable and m.id not in moved and not m.series_id
                   and not any(work.people[p].is_external for p in m.participant_ids() if p in work.people)]
        for m in movable:
            others = [p for p in m.participant_ids() if p != uid]
            req = SlotRequest(uid, others, int(m.minutes), earliest, e, exclude_event_id=m.id, max_results=8, min_notice_min=24 * 60)
            res = find_slots(work, req, now, None, explore=False)
            orig = (m.start, m.end)
            for slot in res.slots:
                work.move(m.id, slot.start, slot.end)
                gain = deep() - current
                work.move(m.id, *orig)
                if gain >= 30 and (best is None or gain > best[0]):
                    best = (gain, m, slot)
        if best is None:
            break
        gain, m, slot = best
        moves.append({
            "event_id": m.id, "title": m.title,
            "from": fmt_local(m.start, tzname), "to": slot.label,
            "gain_min": int(gain), "attendees": len(m.participant_ids()) - 1,
            "start": iso(slot.start), "end": iso(slot.end),
        })
        work.move(m.id, slot.start, slot.end)
        moved.add(m.id)
    after = deep()
    return {
        "week_start": monday.isoformat(),
        "before_hours": round(before / 60, 1),
        "after_hours": round(after / 60, 1),
        "moves": moves,
        "operations": [{"op": "update", "event_id": mv["event_id"], "changes": {"start": mv["start"], "end": mv["end"]}} for mv in moves],
    }
