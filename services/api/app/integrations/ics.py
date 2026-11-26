"""ICS (iCalendar) import - works with exports from Google Calendar, Outlook and Apple Calendar.

Recurring events are expanded within a window around "now", honouring EXDATE (deleted occurrences) and
RECURRENCE-ID overrides (moved or cancelled occurrences, which Google Calendar exports as separate VEVENTs
with the series' UID). Floating times are interpreted in the user's time zone; attendees are matched to
known people by email; all-day and cancelled events are skipped.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from dateutil.rrule import rrulestr
from icalendar import Calendar

from app.domain.classify import categorize
from app.domain.timeutils import tz

MAX_OCCURRENCES = 300


def _aware(value: datetime, tzname: str) -> datetime:
    return value.replace(tzinfo=tz(tzname)) if value.tzinfo is None else value


def _emails(prop: Any) -> list[str]:
    if prop is None:
        return []
    items = prop if isinstance(prop, list) else [prop]
    return [str(i).lower().removeprefix("mailto:") for i in items]


def _instants(prop: Any, tzname: str) -> set[datetime]:
    """Date-time values of an EXDATE-like property (one or several lines) as aware UTC; all-day values are ignored."""
    out: set[datetime] = set()
    for line in prop if isinstance(prop, list) else ([prop] if prop is not None else []):
        for d in getattr(line, "dts", []):
            if isinstance(d.dt, datetime):
                out.add(_aware(d.dt, tzname).astimezone(UTC))
    return out


def _recurrence_id(comp: Any, tzname: str) -> datetime | None:
    rid = comp.get("RECURRENCE-ID")
    return _aware(rid.dt, tzname).astimezone(UTC) if rid is not None and isinstance(rid.dt, datetime) else None


def _expand(rule_text: str, start: datetime) -> Any:
    """Occurrences of an RRULE as aware datetimes. dateutil insists that UNTIL and DTSTART agree on being
    zoned or floating; exporters disagree (RFC 5545 allows a floating UNTIL with a floating DTSTART), so try the
    zoned form first and fall back to wall-clock expansion in the event's own zone."""
    try:
        return iter(rrulestr(rule_text, dtstart=start))
    except ValueError:
        naive = rrulestr(rule_text, dtstart=start.replace(tzinfo=None))  # may raise: caller skips the event
        return (occ.replace(tzinfo=start.tzinfo) for occ in naive)


def parse_ics(raw: bytes, uid: str, people: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    try:
        cal = Calendar.from_ical(raw)
    except Exception as e:  # icalendar raises a variety of errors on malformed input
        raise ValueError(str(e)) from e
    user_tz = people[uid].timezone
    by_email = {p.email.lower(): pid for pid, p in people.items()}
    window_start, window_end = now - timedelta(days=60), now + timedelta(days=90)
    components = list(cal.walk("VEVENT"))
    # Occurrences replaced by an override VEVENT: the series expansion skips them.
    overridden = {(str(c.get("UID", "")), rid) for c in components if (rid := _recurrence_id(c, user_tz)) is not None}
    out: list[dict[str, Any]] = []
    for comp in components:
        dtstart_prop = comp.get("DTSTART")
        if dtstart_prop is None or str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start = dtstart_prop.dt
        if isinstance(start, date) and not isinstance(start, datetime):
            continue  # all-day events are not meetings
        start = _aware(start, user_tz)
        if comp.get("DTEND") is not None:
            end = _aware(comp.get("DTEND").dt, user_tz)
        elif comp.get("DURATION") is not None:
            end = start + comp.get("DURATION").dt
        else:
            end = start + timedelta(minutes=30)
        if end <= start:
            continue
        duration = end - start
        title = str(comp.get("SUMMARY", "(no title)"))
        organizer = by_email.get(_emails(comp.get("ORGANIZER"))[0], uid) if comp.get("ORGANIZER") else uid
        attendee_ids = [by_email[e] for e in _emails(comp.get("ATTENDEE")) if e in by_email]
        ids = list(dict.fromkeys([organizer, uid, *attendee_ids]))
        atts = [{"person_id": p, "response": "accepted", "optional": False} for p in ids]
        category = categorize(title, "meeting", [people[p] for p in ids if p in people])
        ics_uid = str(comp.get("UID", title))
        rid = _recurrence_id(comp, user_tz)
        starts = [start]
        if comp.get("RRULE") is not None and rid is None:
            try:
                rule = _expand("RRULE:" + comp.get("RRULE").to_ical().decode(), start)
            except ValueError:
                continue  # an unreadable recurrence skips this event, not the whole file
            excluded = _instants(comp.get("EXDATE"), user_tz)
            starts = []
            for occ in rule:
                if occ > window_end or len(starts) >= MAX_OCCURRENCES:
                    break
                occ_utc = occ.astimezone(UTC)
                if occ + duration >= window_start and occ_utc not in excluded and (ics_uid, occ_utc) not in overridden:
                    starts.append(occ)
        for s in starts:
            s_utc = s.astimezone(UTC)
            out.append({
                "title": title,
                "description": str(comp.get("DESCRIPTION", ""))[:2000],
                "start": s_utc,
                "end": s_utc + duration,
                "organizer_id": organizer,
                "attendees": atts,
                "kind": "meeting",
                "category": category,
                "location": str(comp.get("LOCATION")) if comp.get("LOCATION") else None,
                "is_virtual": not bool(comp.get("LOCATION")),
                "is_movable": organizer == uid,
                "source": "ics",
                # An override keeps the identity of the occurrence it replaces, so re-importing stays idempotent.
                "external_ref": f"ics:{ics_uid}:{(rid or s_utc).isoformat()}",
            })
    return out
