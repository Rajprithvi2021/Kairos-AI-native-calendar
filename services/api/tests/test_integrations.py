"""Integrations: ICS parsing (recurrence, floating times, all-day) and the Google Calendar mapping."""

from __future__ import annotations

from app.integrations import google_calendar, ics


def _people(world):
    return {p.id: p for p in world.people}


def test_ics_recurrence_floating_time_and_attendee_matching(world, now) -> None:
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        b"BEGIN:VEVENT\r\nUID:r1\r\nSUMMARY:Weekly ops review\r\nDTSTART:20261130T100000\r\nDTEND:20261130T110000\r\n"
        b"RRULE:FREQ=WEEKLY;COUNT=4\r\nORGANIZER:mailto:alex@lumora.example\r\nATTENDEE:mailto:nina@lumora.example\r\n"
        b"ATTENDEE:mailto:stranger@elsewhere.example\r\nEND:VEVENT\r\n"
        b"BEGIN:VEVENT\r\nUID:a1\r\nSUMMARY:Company holiday\r\nDTSTART;VALUE=DATE:20261224\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    events = ics.parse_ics(raw, "maya", _people(world), now)
    assert len(events) == 4  # all-day skipped, recurrence expanded
    first = events[0]
    assert first["organizer_id"] == "alex" and {a["person_id"] for a in first["attendees"]} == {"alex", "maya", "nina"}
    assert first["start"].hour == 18  # 10:00 floating time interpreted in Maya's zone (PST = UTC-8)
    assert first["category"] == "planning" and first["is_movable"] is False


def test_ics_exdate_moved_and_cancelled_occurrences(world, now) -> None:
    tz = b";TZID=America/Los_Angeles:"
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        b"BEGIN:VEVENT\r\nUID:s1\r\nSUMMARY:Weekly ops review\r\nDTSTART" + tz + b"20261130T100000\r\nDTEND" + tz + b"20261130T110000\r\n"
        b"RRULE:FREQ=WEEKLY;COUNT=5\r\nEXDATE" + tz + b"20261207T100000\r\nEND:VEVENT\r\n"
        # the 14 Dec occurrence moved to Tuesday 15 Dec, 14:00
        b"BEGIN:VEVENT\r\nUID:s1\r\nRECURRENCE-ID" + tz + b"20261214T100000\r\nSUMMARY:Weekly ops review (moved)\r\n"
        b"DTSTART" + tz + b"20261215T140000\r\nDTEND" + tz + b"20261215T150000\r\nEND:VEVENT\r\n"
        # the 21 Dec occurrence cancelled
        b"BEGIN:VEVENT\r\nUID:s1\r\nRECURRENCE-ID" + tz + b"20261221T100000\r\nSTATUS:CANCELLED\r\nSUMMARY:Weekly ops review\r\n"
        b"DTSTART" + tz + b"20261221T100000\r\nDTEND" + tz + b"20261221T110000\r\nEND:VEVENT\r\n"
        b"END:VCALENDAR\r\n"
    )
    events = sorted(ics.parse_ics(raw, "maya", _people(world), now), key=lambda e: e["start"])
    # 30 Nov kept, 7 Dec deleted (EXDATE), 14 Dec moved to 15 Dec 14:00, 21 Dec cancelled, 28 Dec kept.
    assert [e["start"].isoformat()[:16] for e in events] == ["2026-11-30T18:00", "2026-12-15T22:00", "2026-12-28T18:00"]
    assert events[1]["title"] == "Weekly ops review (moved)"
    assert events[1]["external_ref"] == "ics:s1:2026-12-14T18:00:00+00:00"  # keeps the replaced occurrence's identity


def test_ics_floating_until_and_bad_recurrence_do_not_abort_the_import(world, now) -> None:
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        # floating DTSTART with a floating UNTIL: valid RFC 5545, rejected by a naive dateutil call
        b"BEGIN:VEVENT\r\nUID:f1\r\nSUMMARY:Floating weekly\r\nDTSTART:20261130T100000\r\nDTEND:20261130T110000\r\n"
        b"RRULE:FREQ=WEEKLY;UNTIL=20261221T100000\r\nEND:VEVENT\r\n"
        b"BEGIN:VEVENT\r\nUID:b1\r\nSUMMARY:Broken rule\r\nDTSTART:20261201T100000\r\nDTEND:20261201T110000\r\n"
        b"RRULE:FREQ=SOMETIMES\r\nEND:VEVENT\r\n"
        b"BEGIN:VEVENT\r\nUID:o1\r\nSUMMARY:One-off\r\nDTSTART:20261202T150000Z\r\nDTEND:20261202T160000Z\r\nEND:VEVENT\r\n"
        b"END:VCALENDAR\r\n"
    )
    events = ics.parse_ics(raw, "maya", _people(world), now)
    titles = sorted(e["title"] for e in events)
    assert titles == ["Floating weekly"] * 4 + ["One-off"]  # 30 Nov .. 21 Dec; the broken series is skipped
    assert sorted(e["start"].hour for e in events if e["title"] == "Floating weekly") == [18] * 4  # 10:00 PST


def test_google_event_mapping(world) -> None:
    by_email = {p.email.lower(): p.id for p in world.people}
    item = {
        "id": "g123", "status": "confirmed", "summary": "Roadmap review", "eventType": "default",
        "start": {"dateTime": "2026-12-02T10:00:00-08:00"}, "end": {"dateTime": "2026-12-02T11:00:00-08:00"},
        "organizer": {"email": "nina@lumora.example"},
        "attendees": [{"email": "maya@lumora.example", "responseStatus": "accepted"},
                      {"email": "dev@lumora.example", "responseStatus": "tentative", "optional": True}],
        "hangoutLink": "https://meet.example/abc",
    }
    ev = google_calendar.to_kairos_event(item, "maya", by_email)
    assert ev and ev["organizer_id"] == "nina" and ev["is_virtual"] and ev["external_ref"] == "google:g123"
    assert {a["person_id"]: a["response"] for a in ev["attendees"]} == {"maya": "accepted", "dev": "tentative"}
    assert google_calendar.to_kairos_event({**item, "status": "cancelled"}, "maya", by_email) is None
    assert google_calendar.to_kairos_event({**item, "start": {"date": "2026-12-02"}}, "maya", by_email) is None
    focus = google_calendar.to_kairos_event({**item, "eventType": "focusTime"}, "maya", by_email)
    assert focus and focus["kind"] == "focus"


def test_postgres_urls_from_neon_or_ci_use_pg8000_with_the_right_tls() -> None:
    from app.db import postgres_url

    neon = "postgresql://kairos:pw@ep-cool-name-123456.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    url, args = postgres_url(neon)
    assert url.drivername == "postgresql+pg8000" and url.host.endswith("neon.tech") and url.database == "neondb"
    assert dict(url.query) == {} and args["ssl_context"].verify_mode.name == "CERT_REQUIRED"
    heroku_style, args2 = postgres_url("postgres://u:p@db.example.com:5433/app")
    assert heroku_style.drivername == "postgresql+pg8000" and heroku_style.port == 5433 and "ssl_context" in args2
    local, args3 = postgres_url("postgresql://postgres:postgres@localhost:5432/kairos?sslmode=disable")
    assert local.drivername == "postgresql+pg8000" and args3 == {}
