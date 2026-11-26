from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.domain.calendar_data import holidays_for
from app.domain.timeutils import IntervalSet, merge, subtract, working_intervals


def dt(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def test_merge_and_subtract() -> None:
    m = merge([(dt(2026, 1, 1, 9), dt(2026, 1, 1, 10)), (dt(2026, 1, 1, 9, 30), dt(2026, 1, 1, 11)), (dt(2026, 1, 1, 12), dt(2026, 1, 1, 13))])
    assert m == [(dt(2026, 1, 1, 9), dt(2026, 1, 1, 11)), (dt(2026, 1, 1, 12), dt(2026, 1, 1, 13))]
    free = subtract((dt(2026, 1, 1, 8), dt(2026, 1, 1, 14)), m)
    assert free == [(dt(2026, 1, 1, 8), dt(2026, 1, 1, 9)), (dt(2026, 1, 1, 11), dt(2026, 1, 1, 12)), (dt(2026, 1, 1, 13), dt(2026, 1, 1, 14))]


def test_interval_set_queries() -> None:
    s = IntervalSet([(dt(2026, 1, 1, 9), dt(2026, 1, 1, 10)), (dt(2026, 1, 1, 12), dt(2026, 1, 1, 13))])
    assert s.overlaps(dt(2026, 1, 1, 9, 30), dt(2026, 1, 1, 9, 45))
    assert s.overlaps(dt(2026, 1, 1, 11), dt(2026, 1, 1, 12, 1))
    assert not s.overlaps(dt(2026, 1, 1, 10), dt(2026, 1, 1, 12))  # touching edges are free
    assert s.contains(dt(2026, 1, 1, 12, 15), dt(2026, 1, 1, 12, 45))
    assert not s.contains(dt(2026, 1, 1, 9, 30), dt(2026, 1, 1, 10, 30))


def test_working_hours_respect_dst_transitions() -> None:
    # US DST starts Sun 8 Mar 2026: 09:00 Los Angeles is 17:00 UTC on Fri 6 Mar but 16:00 UTC on Mon 9 Mar.
    iv = working_intervals("America/Los_Angeles", "09:00", "17:00", [0, 1, 2, 3, 4], dt(2026, 3, 6), dt(2026, 3, 10))
    starts = {s.date(): s.hour for s, _ in iv}
    assert starts[date(2026, 3, 6)] == 17 and starts[date(2026, 3, 9)] == 16
    # US and EU change on different weekends: 2 weeks in March where SF-London is 7h, not 8h.
    lon = working_intervals("Europe/London", "09:00", "17:00", [0, 1, 2, 3, 4], dt(2026, 3, 16), dt(2026, 3, 17))
    assert lon[0][0] == dt(2026, 3, 16, 9)
    # India has no DST and a half-hour offset.
    ind = working_intervals("Asia/Kolkata", "10:00", "18:30", [0, 1, 2, 3, 4], dt(2026, 7, 6), dt(2026, 7, 7))
    assert ind[0] == (dt(2026, 7, 6, 4, 30), dt(2026, 7, 6, 13, 0))


def test_holidays_excluded_per_country() -> None:
    us = holidays_for("US", date(2026, 11, 20), date(2026, 11, 30))
    assert date(2026, 11, 26) in us  # Thanksgiving
    iv = working_intervals("America/Los_Angeles", "09:00", "17:00", [0, 1, 2, 3, 4], dt(2026, 11, 25), dt(2026, 11, 28), set(us))
    assert date(2026, 11, 26) not in {s.astimezone().date() for s, _ in iv if (s - timedelta(hours=8)).date() == date(2026, 11, 26)}
    assert all((s - timedelta(hours=8)).date() != date(2026, 11, 26) for s, _ in iv)
    gb = holidays_for("GB", date(2026, 12, 20), date(2026, 12, 31))
    assert date(2026, 12, 25) in gb and date(2026, 12, 28) in gb  # Boxing Day (substitute)
