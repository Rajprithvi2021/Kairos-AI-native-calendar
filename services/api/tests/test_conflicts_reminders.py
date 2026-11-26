"""F2 conflicts + F3 reminders on the planted demo scenarios."""

from __future__ import annotations

from datetime import timedelta

from app.clock import parse_utc
from app.domain.calendar_data import Snapshot
from app.domain.timeutils import to_local
from app.engines import conflicts, reminders


def _apply(snap: Snapshot, operations: list[dict]) -> None:
    for op in operations:
        ev = snap.event(op.get("event_id", ""))
        if op["op"] == "update" and ev:
            ch = op["changes"]
            if "start" in ch:
                ev.start = parse_utc(ch["start"])
            if "end" in ch:
                ev.end = parse_utc(ch["end"])
            if "is_virtual" in ch:
                ev.is_virtual = ch["is_virtual"]
                ev.location = ch.get("location", ev.location)
        elif op["op"] == "respond" and ev:
            a = ev.attendee(op["person_id"])
            if a:
                a.response = op["response"]
        elif op["op"] == "delete" and ev:
            ev.status = "cancelled"


def test_all_planted_conflicts_are_detected(snap, now) -> None:
    cs = conflicts.detect_conflicts(snap, "maya", now, now + timedelta(days=14), now)
    by_type = {c.type: c for c in cs}
    assert set(by_type) == {"overlap", "travel", "focus", "overload", "outside_hours"}
    assert set(by_type["overlap"].event_ids) == {"plant_qbr", "plant_health"} and by_type["overlap"].severity == "high"
    assert set(by_type["travel"].event_ids) == {"plant_onsite", "plant_lunch"}
    assert set(by_type["focus"].event_ids) == {"plant_vendor", "plant_focus"}
    assert by_type["outside_hours"].event_ids == ["plant_emea"]
    for c in cs:
        assert c.options, f"{c.type} has no resolution options"
        assert [o.score for o in c.options] == sorted((o.score for o in c.options), reverse=True)


def test_overlap_keeps_the_customer_and_moves_the_internal_review(snap, now) -> None:
    c = next(c for c in conflicts.detect_conflicts(snap, "maya", now, now + timedelta(days=14), now) if c.type == "overlap")
    best = c.options[0]
    assert best.kind == "move" and best.operations[0]["event_id"] == "plant_health"
    assert any("Keeps" in r for r in best.reasons)
    _apply(snap, best.operations)
    after = conflicts.detect_conflicts(snap, "maya", now, now + timedelta(days=14), now, with_options=False)
    assert c.id not in {x.id for x in after}
    new_overlaps = [x for x in after if x.type == "overlap"]
    assert not new_overlaps, "a resolution must never create a new double-booking"


def test_every_move_option_lands_in_free_time(snap, now) -> None:
    for c in conflicts.detect_conflicts(snap, "maya", now, now + timedelta(days=14), now):
        for o in c.options:
            for op in o.operations:
                if op["op"] == "update" and "start" in op["changes"]:
                    ev = snap.event(op["event_id"])
                    s, e = parse_utc(op["changes"]["start"]), parse_utc(op["changes"]["end"])
                    for pid in ev.participant_ids():
                        if ev.attending(pid) and pid in snap.people:
                            busy = snap.busy(pid, s - timedelta(hours=2), e + timedelta(hours=2), exclude_ids={ev.id})
                            assert not busy.overlaps(s, e), f"{o.label} double-books {pid}"


def test_dismiss_conflict_hides_it(snap, now) -> None:
    c = next(c for c in conflicts.detect_conflicts(snap, "maya", now, now + timedelta(days=14), now) if c.type == "outside_hours")
    snap.pref("maya").dismissed_conflicts = [c.id]
    try:
        ids = {x.id for x in conflicts.detect_conflicts(snap, "maya", now, now + timedelta(days=14), now, with_options=False)}
        assert c.id not in ids
    finally:
        snap.pref("maya").dismissed_conflicts = []


def test_onsite_reminders_use_travel_time_and_real_gaps(snap, now) -> None:
    ev = snap.event("plant_onsite")
    plan = {r.kind: r for r in reminders.plan_event(snap, ev, "maya", now)}
    assert plan["leave"].fire_at == ev.start - timedelta(minutes=55 + 10)
    prep = plan["prep"]
    assert prep.fire_at < ev.start and prep.action and prep.action["operations"]
    s = prep.fire_at
    e = s + timedelta(minutes=int(prep.title.split(" ")[1]))
    assert not snap.busy("maya", s - timedelta(hours=1), e + timedelta(hours=1)).overlaps(s, e), "prep must sit in a free gap"
    assert e <= plan["leave"].fire_at, "prep must be finished before the user has to leave for an in-person meeting"
    assert "followup" in plan


def test_routine_meetings_are_silent(snap, now) -> None:
    standup = next(e for e in snap.events if e.series_id == "s_standup" and e.start > now)
    plan = reminders.plan_event(snap, standup, "maya", now)
    assert plan and all(r.suppressed and not r.enabled for r in plan)


def test_quiet_hours_with_and_without_midnight_wrap(snap) -> None:
    prefs = snap.pref("maya")
    at = lambda hhmm: parse_utc(f"2026-12-01T{hhmm}:00Z")  # noqa: E731  (UTC; Maya is UTC-8)
    assert reminders._in_quiet_hours(at("05:00"), snap, "maya")  # 21:00 PST, default 20:00-07:30
    assert not reminders._in_quiet_hours(at("20:00"), snap, "maya")  # 12:00 PST
    prefs.quiet_start, prefs.quiet_end = "12:00", "13:00"  # a lunch window that does not wrap midnight
    try:
        assert reminders._in_quiet_hours(at("20:30"), snap, "maya")  # 12:30 PST
        assert not reminders._in_quiet_hours(at("17:00"), snap, "maya")  # 09:00 PST
    finally:
        prefs.quiet_start, prefs.quiet_end = "20:00", "07:30"


def test_upcoming_and_digest(snap, now) -> None:
    up = reminders.upcoming(snap, "maya", now, 24 * 7)
    assert up and all(r.enabled and not r.suppressed for r in up)
    assert [r.fire_at for r in up] == sorted(r.fire_at for r in up)
    day = to_local(snap.event("plant_onsite").start, "America/Los_Angeles").date()
    dg = reminders.digest(snap, "maya", day, now)
    assert dg["meeting_count"] >= 3 and dg["in_person"] and dg["headline"]
