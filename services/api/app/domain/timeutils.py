"""Time-zone and interval arithmetic. Everything is UTC-aware; local times are derived per person."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

Interval = tuple[datetime, datetime]


@lru_cache(maxsize=64)
def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def minutes_of(t: time) -> int:
    return t.hour * 60 + t.minute


def to_local(dt: datetime, tzname: str) -> datetime:
    return dt.astimezone(tz(tzname))


def local_date(dt: datetime, tzname: str) -> date:
    return to_local(dt, tzname).date()


def local_to_utc(d: date, t: time, tzname: str) -> datetime:
    return datetime.combine(d, t, tzinfo=tz(tzname)).astimezone(UTC)


def local_midnight_utc(d: date, tzname: str) -> datetime:
    return local_to_utc(d, time(0, 0), tzname)


def week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def daterange(start: date, end: date) -> Iterable[date]:
    """Inclusive date range."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600.0


def minutes(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    s, e = max(a_start, b_start), min(a_end, b_end)
    return max(0.0, minutes(s, e))


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(i for i in intervals if i[1] > i[0]):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def subtract(base: Interval, busy: Sequence[Interval]) -> list[Interval]:
    """Free parts of `base` not covered by (merged, sorted) `busy`."""
    free: list[Interval] = []
    cur = base[0]
    for s, e in busy:
        if e <= cur or s >= base[1]:
            continue
        if s > cur:
            free.append((cur, min(s, base[1])))
        cur = max(cur, e)
        if cur >= base[1]:
            break
    if cur < base[1]:
        free.append((cur, base[1]))
    return free


class IntervalSet:
    """Merged, sorted intervals with O(log n) overlap / containment queries."""

    __slots__ = ("items", "_starts")

    def __init__(self, intervals: Iterable[Interval] = ()) -> None:
        self.items = merge(intervals)
        self._starts = [s for s, _ in self.items]

    def overlaps(self, s: datetime, e: datetime) -> bool:
        i = bisect_right(self._starts, s) - 1
        if i >= 0 and self.items[i][1] > s:
            return True
        j = i + 1
        return j < len(self.items) and self.items[j][0] < e

    def contains(self, s: datetime, e: datetime) -> bool:
        i = bisect_right(self._starts, s) - 1
        return i >= 0 and self.items[i][0] <= s and self.items[i][1] >= e

    def block_containing(self, s: datetime, e: datetime) -> Interval | None:
        i = bisect_right(self._starts, s) - 1
        if i >= 0 and self.items[i][0] <= s and self.items[i][1] >= e:
            return self.items[i]
        return None

    def __len__(self) -> int:
        return len(self.items)


def working_intervals(
    tzname: str,
    work_start: str,
    work_end: str,
    work_days: Sequence[int],
    start: datetime,
    end: datetime,
    holidays: set[date] | None = None,
    stretch_min: int = 0,
) -> list[Interval]:
    """UTC intervals of a person's working hours (local wall-clock, DST-correct) inside [start, end)."""
    ws, we = parse_hhmm(work_start), parse_hhmm(work_end)
    holidays = holidays or set()
    out: list[Interval] = []
    first = local_date(start, tzname) - timedelta(days=1)
    last = local_date(end, tzname) + timedelta(days=1)
    stretch = timedelta(minutes=stretch_min)
    for d in daterange(first, last):
        if d.weekday() not in work_days or d in holidays:
            continue
        s = local_to_utc(d, ws, tzname) - stretch
        e = local_to_utc(d, we, tzname) + stretch
        s, e = max(s, start), min(e, end)
        if e > s:
            out.append((s, e))
    return merge(out)


def fmt_local(dt: datetime, tzname: str) -> str:
    """e.g. 'Tue 9:30 PM' (portable, no %-I)."""
    loc = to_local(dt, tzname)
    hour = loc.hour % 12 or 12
    return f"{loc:%a} {hour}:{loc:%M} {'AM' if loc.hour < 12 else 'PM'}"


def fmt_time(dt: datetime, tzname: str) -> str:
    loc = to_local(dt, tzname)
    hour = loc.hour % 12 or 12
    return f"{hour}:{loc:%M} {'AM' if loc.hour < 12 else 'PM'}"


def tz_abbrev(dt: datetime, tzname: str) -> str:
    name = to_local(dt, tzname).tzname() or tzname
    return {"+0530": "IST", "+0545": "NPT"}.get(name, name)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
