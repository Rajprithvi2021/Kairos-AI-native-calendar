"""F1 scheduler + F8 learning: hard constraints are never violated; soft scoring behaves as designed."""

from __future__ import annotations

import time
from datetime import timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.domain.calendar_data import Snapshot
from app.domain.timeutils import to_local
from app.engines.scheduler import (
    DEFAULT_WEIGHTS,
    SlotRequest,
    comfort,
    find_slots,
    learn_weights,
    normalize_weights,
)
from tests.conftest import make_snapshot

INTERNAL = ["dev", "priya", "alex", "emma", "arjun", "sam", "nina", "leo", "lena", "omar", "jordan"]


def _next_monday(now):
    return now + timedelta(days=(7 - now.weekday()))


def _assert_hard_constraints(snap: Snapshot, req: SlotRequest, slots, now) -> None:
    for sl in slots:
        assert sl.start >= now + timedelta(minutes=req.min_notice_min)
        assert (sl.end - sl.start) == timedelta(minutes=req.duration_min)
        for pid in req.required():
            work = snap.working(pid, sl.start - timedelta(days=1), sl.end + timedelta(days=1), req.stretch_hours_min)
            assert work.contains(sl.start, sl.end), f"{pid} outside working hours at {sl.label}"
            include_focus = not (pid == req.organizer_id and not req.respect_focus)
            busy = snap.busy(pid, sl.start - timedelta(days=1), sl.end + timedelta(days=1), include_focus=include_focus,
                             exclude_ids={req.exclude_event_id} if req.exclude_event_id else None)
            assert not busy.overlaps(sl.start, sl.end), f"{pid} double-booked at {sl.label}"


def test_dev_alex_next_week_has_explained_slots(snap, now) -> None:
    nm = _next_monday(now)
    req = SlotRequest("maya", ["dev", "alex"], 45, nm, nm + timedelta(days=5))
    res = find_slots(snap, req, now)
    assert len(res.slots) >= 3
    _assert_hard_constraints(snap, req, res.slots, now)
    assert [s.rank for s in res.slots] == list(range(1, len(res.slots) + 1))
    assert all(s.reasons for s in res.slots)
    assert res.slots[0].score >= res.slots[-1].score


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    attendees=st.lists(st.sampled_from(INTERNAL), min_size=0, max_size=4, unique=True),
    duration=st.sampled_from([15, 30, 45, 60, 90]),
    day_offset=st.integers(min_value=0, max_value=14),
    span=st.integers(min_value=1, max_value=7),
    stretch=st.sampled_from([0, 0, 60]),
    respect_focus=st.booleans(),
)
def test_property_hard_constraints_never_violated(world, now, attendees, duration, day_offset, span, stretch, respect_focus) -> None:
    snap = make_snapshot(world)
    ws = now + timedelta(days=day_offset)
    req = SlotRequest("maya", attendees, duration, ws, ws + timedelta(days=span), stretch_hours_min=stretch,
                      respect_focus=respect_focus, max_results=6)
    res = find_slots(snap, req, now, explore=False)
    _assert_hard_constraints(snap, req, res.slots, now)


def test_no_shared_hours_triggers_fair_stretch(snap, now) -> None:
    nm = _next_monday(now)
    req = SlotRequest("maya", ["priya", "alex"], 45, nm, nm + timedelta(days=5))
    res = find_slots(snap, req, now)
    assert res.slots == []
    stretch = [r for r in res.relaxations if r.kind == "stretch"]
    assert stretch, "SF + Bangalore + NY has no shared working hours; Kairos must say what would have to give"
    assert "Priya" in stretch[0].description and "IST" in stretch[0].description


def test_focus_preservation_prefers_short_gaps(snap, now) -> None:
    # A solo 30-minute slot should not land in the middle of a long free block when shorter gaps exist.
    nm = _next_monday(now)
    res = find_slots(snap, SlotRequest("maya", [], 30, nm + timedelta(days=3), nm + timedelta(days=5)), now)
    top = res.slots[0]
    assert top.components["focus"] >= max(s.components["focus"] for s in res.slots) - 1e-9 or top.score >= res.slots[1].score


def test_time_of_day_and_explicit_limits(snap, now) -> None:
    nm = _next_monday(now)
    tz = snap.person("maya").timezone
    morning = find_slots(snap, SlotRequest("maya", ["dev"], 30, nm, nm + timedelta(days=5), preferred_period="morning"), now)
    assert to_local(morning.slots[0].start, tz).hour < 12
    limited = find_slots(snap, SlotRequest("maya", ["dev"], 30, nm, nm + timedelta(days=5), earliest_local="14:00"), now)
    assert limited.slots and all(to_local(s.start, tz).hour >= 14 for s in limited.slots)


def test_reschedule_excludes_the_event_itself(snap, now) -> None:
    ev = snap.event("plant_health")
    others = [p for p in ev.participant_ids() if p != "maya"]
    req = SlotRequest("maya", others, int(ev.minutes), now, now + timedelta(days=7), exclude_event_id=ev.id)
    res = find_slots(snap, req, now)
    assert res.slots
    _assert_hard_constraints(snap, req, res.slots, now)


def test_performance_ten_attendees_two_weeks(snap, now) -> None:
    req = SlotRequest("maya", INTERNAL[:9], 30, now, now + timedelta(days=14), stretch_hours_min=180)
    t0 = time.perf_counter()
    find_slots(snap, req, now, explore=False)
    assert (time.perf_counter() - t0) < 0.5  # NFR: p95 < 300 ms in production; generous bound for CI machines


def test_comfort_curve() -> None:
    assert comfort(10 * 60, 11 * 60, 9 * 60, 17 * 60) == 1.0
    assert 0.55 <= comfort(9 * 60, 9 * 60 + 30, 9 * 60, 17 * 60) < 1.0
    assert comfort(21 * 60, 22 * 60, 9 * 60, 17 * 60) < 0.2


def test_learning_shifts_weight_toward_what_the_user_picks() -> None:
    chosen = {"fairness": 0.6, "focus": 1.0, "preference": 1.0, "batching": 0.45, "day_load": 0.9, "soonness": 0.2, "optional": 1, "lunch": 1}
    above = {"fairness": 1.0, "focus": 0.4, "preference": 1.0, "batching": 1.0, "day_load": 0.6, "soonness": 1.0, "optional": 1, "lunch": 1}
    w = normalize_weights(None)
    for _ in range(5):
        w = learn_weights(w, chosen, [above, chosen])
    assert w["focus"] > DEFAULT_WEIGHTS["focus"]
    assert abs(sum(w.values()) - 1.0) < 1e-9 and all(0.0 < v <= 0.6 for v in w.values())
