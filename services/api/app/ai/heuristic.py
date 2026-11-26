"""Offline command parser: the deterministic twin of the Claude parser.

Covers the everyday scheduling grammar - who, how long, when, time of day, explicit limits - with
regexes and a small relative-date resolver. It is scored on the same golden set as Claude
(evals/run_evals.py), so the two engines are directly comparable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from app.ai.schemas import DateWindow, ParsedCommand

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
for _i, _n in enumerate(WEEKDAYS):
    _WD[_n] = _i
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_WD_RE = r"(mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:r|rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
_MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

ACTIONS: list[tuple[str, re.Pattern[str]]] = [
    ("set_reminder", re.compile(r"\b(remind me|reminder)\b", re.I)),
    ("find_conflicts", re.compile(r"\b(conflicts?|double[- ]?book\w*|overlaps?|clash\w*)\b", re.I)),
    ("defrag_week", re.compile(r"\b(defrag\w*|consolidate|re-?organi[sz]e my|optimi[sz]e my (?:week|calendar|schedule)|free up)\b", re.I)),
    ("show_analytics", re.compile(r"\b(how much time|how many hours|analytics|insights?|where did my time|time spent|meeting load|stats|forecast)\b", re.I)),
    ("brief_event", re.compile(r"\b(brief me|brief|prep me|prepare me|what do i need to know|background on)\b", re.I)),
    ("cancel_event", re.compile(r"\b(cancel|delete|remove|drop)\b", re.I)),
    ("reschedule_event", re.compile(r"\b(move|reschedule|push|shift|postpone|bring forward)\b", re.I)),
    ("block_focus", re.compile(r"\b(block|protect|focus|deep work|heads[- ]down|no meetings)\b", re.I)),
    ("schedule_meeting", re.compile(r"\b(schedule|set up|book|find|meet|meeting|call|sync|1:1|catch up|lunch|coffee|chat)\b", re.I)),
]

_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(minutes?|mins?|m|hours?|hrs?|h)\b", re.I)
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"


def _hhmm(h: str, m: str | None, ampm: str | None) -> str | None:
    hour, minute = int(h), int(m or 0)
    if hour > 23 or minute > 59:
        return None
    ap = (ampm or "").replace(".", "").lower()
    if ap == "pm" and hour < 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    elif not ap and 1 <= hour <= 7:
        hour += 12  # "at 3" in a business context means 3 PM
    return f"{hour:02d}:{minute:02d}"


def _next_weekday(today: date, wd: int, *, next_week: bool = False, allow_today: bool = False) -> date:
    if next_week:
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return monday + timedelta(days=wd)
    delta = (wd - today.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return today + timedelta(days=delta)


def resolve_window(text: str, today: date) -> DateWindow | None:
    t = text.lower()
    monday = today - timedelta(days=today.weekday())

    def win(a: date, b: date) -> DateWindow:
        return DateWindow(start_date=a.isoformat(), end_date=b.isoformat())

    if re.search(r"\bday after tomorrow\b", t):
        d = today + timedelta(days=2)
        return win(d, d)
    if re.search(r"\b(today|this (?:morning|afternoon|evening)|tonight)\b", t):
        return win(today, today)
    if re.search(r"\btomorrow\b", t):
        d = today + timedelta(days=1)
        return win(d, d)
    if re.search(r"\b(the )?week after next\b", t):
        return win(monday + timedelta(days=14), monday + timedelta(days=18))
    if re.search(r"\bnext week\b", t):
        return win(monday + timedelta(days=7), monday + timedelta(days=11))
    if re.search(r"\b(this week|end of (?:the )?week|later this week)\b", t):
        end = monday + timedelta(days=4)
        if today > end:
            return win(monday + timedelta(days=7), monday + timedelta(days=11))
        if re.search(r"\b(by|before) (?:the )?end of (?:the )?week\b", t):
            return win(today, end)
        return win(today, end)
    m = re.search(r"\bin (\d+) days?\b", t)
    if m:
        d = today + timedelta(days=int(m.group(1)))
        return win(d, d)
    m = re.search(r"\b(?:within(?: the next)?|in the next|over the next) (\d+) days?\b", t)
    if m:
        return win(today, today + timedelta(days=int(m.group(1))))
    m = re.search(r"\b(by|before|until) " + _WD_RE + r"\b", t)
    if m:
        target = _next_weekday(today, _WD[m.group(2)[:3] if m.group(2)[:3] in _WD else m.group(2)])
        end = target - timedelta(days=1) if m.group(1) == "before" else target
        return win(today, max(today, end))
    m = re.search(r"\b(next|this|on)?\s*" + _WD_RE + r"\b", t)
    if m:
        key = m.group(2)
        wd = _WD.get(key, _WD.get(key[:3], 0))
        d = _next_weekday(today, wd, next_week=m.group(1) == "next", allow_today=m.group(1) == "this")
        return win(d, d)
    m = re.search(r"\b" + _MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b", t) or re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_RE + r"\b", t)
    if m:
        a, b = m.group(1), m.group(2)
        mon_s, day_s = (a, b) if not a.isdigit() else (b, a)
        try:
            d = date(today.year, MONTHS[mon_s[:3]], int(day_s))
            if d < today:
                d = date(today.year + 1, d.month, d.day)
            return win(d, d)
        except (ValueError, KeyError):
            return None
    return None


def _duration(text: str) -> int | None:
    t = text.lower()
    m = _DURATION.search(t)
    if m:
        value = float(m.group(1))
        return int(round(value * 60)) if m.group(2).startswith("h") else int(round(value))
    if re.search(r"\b(half an hour|half-hour|30-minute)\b", t):
        return 30
    if re.search(r"\b(an hour|one hour|hour-long|1-hour)\b", t):
        return 60
    if re.search(r"\b(quick|brief chat|short)\b", t):
        return 15
    return None


def _time_limits(text: str) -> tuple[str | None, str | None, str | None]:
    t = text.lower()
    tod = None
    for word in ("morning", "afternoon", "evening"):
        if re.search(rf"\b{word}s?\b", t):
            tod = word
    earliest = latest = None
    m = re.search(r"\bbetween\s+" + _TIME + r"\s+(?:and|-)\s+" + _TIME, t)
    if m:
        ap2 = m.group(6)
        earliest = _hhmm(m.group(1), m.group(2), m.group(3) or ap2)
        latest = _hhmm(m.group(4), m.group(5), ap2)
        return tod, earliest, latest
    m = re.search(r"\b(?:after|from|not before)\s+" + _TIME + r"(?!\s*(?:min|hour|h\b))", t)
    if m and (m.group(3) or m.group(2) or int(m.group(1)) <= 12):
        earliest = _hhmm(m.group(1), m.group(2), m.group(3))
    m = re.search(r"\b(?:before|by|until|no later than)\s+" + _TIME + r"\b(?!\s*(?:min|hour|day))", t)
    if m and (m.group(3) or m.group(2)):
        latest = _hhmm(m.group(1), m.group(2), m.group(3))
    m = re.search(r"\bat\s+" + _TIME + r"\b", t)
    if m and (m.group(3) or m.group(2) or int(m.group(1)) <= 12):
        earliest = _hhmm(m.group(1), m.group(2), m.group(3))
        latest = None
    return tod, earliest, latest


def _people_mentions(text: str, people: Iterable[Any], user_id: str) -> tuple[list[str], list[str]]:
    found: list[tuple[int, str, bool]] = []
    for p in people:
        if p.id == user_id:
            continue
        names = [p.name, p.name.split(" ")[0]]
        for n in names:
            m = re.search(rf"\b{re.escape(n)}\b", text, re.I)
            if m:
                before = text[max(0, m.start() - 25): m.start()].lower()
                after = text[m.end(): m.end() + 12].lower()
                optional = bool(re.search(r"\b(optional(?:ly)?|cc|if (?:she|he|they)'?s? free)\b", before[-20:] + " " + after))
                found.append((m.start(), p.name, optional))
                break
    found.sort()
    req = [n for _, n, o in found if not o]
    opt = [n for _, n, o in found if o]
    return req, opt


def _title(text: str, action: str, attendees: list[str]) -> str | None:
    q = re.search(r"[\"“‘']([^\"”’']{3,80})[\"”’']", text)
    if q:
        return q.group(1).strip()
    m = re.search(r"\b(?:about|to discuss|re:?|regarding|for)\s+(?:the\s+|our\s+|my\s+)?(.+?)(?=\s+(?:with|next|this|on|tomorrow|today|by|before|after|at|in|between|for)\b|[,.?!]|$)", text, re.I)
    if m and action in ("schedule_meeting", "block_focus"):
        phrase = m.group(1).strip()
        if phrase and not re.match(r"^\d", phrase) and len(phrase) <= 60:
            return ("Focus: " + phrase) if action == "block_focus" else phrase[0].upper() + phrase[1:]
    if action == "schedule_meeting" and attendees:
        return "Sync: " + " / ".join(n.split(" ")[0] for n in attendees)
    if action == "block_focus":
        return "Focus: deep work"
    return None


def _target(text: str, action: str) -> str | None:
    verbs = {
        "reschedule_event": r"(?:move|reschedule|push|shift|postpone|bring forward)",
        "cancel_event": r"(?:cancel|delete|remove|drop)",
        "brief_event": r"(?:brief me on|brief me for|brief me about|prep me for|prepare me for|what do i need to know (?:about|for)|background on|brief)",
        "set_reminder": r"(?:before|for|about|ahead of)",
    }
    pat = verbs.get(action)
    if not pat:
        return None
    m = re.search(pat + r"\s+(?:my\s+|the\s+|our\s+)?(.+?)(?=\s+(?:to|until|till|by)\s+|\s+(?:next|this)\s+week\b|[?.!]|$)", text, re.I)
    if not m:
        return None
    phrase = m.group(1).strip(" ,")
    phrase = re.sub(r"^\d+\s*(?:minutes?|mins?|hours?)\s+(?:before\s+)?(?:the\s+|my\s+)?", "", phrase, flags=re.I)
    return phrase or None


def parse(text: str, today: date, people: Iterable[Any], user_id: str) -> ParsedCommand:
    people = list(people)
    clean = text.strip()
    action = "unknown"
    for name, pat in ACTIONS:
        if pat.search(clean):
            action = name
            break
    attendees, optional = _people_mentions(clean, people, user_id)
    if re.search(r"\b(my team|the team|my directs|direct reports)\b", clean, re.I):
        for p in people:
            if p.manager_id == user_id and p.name not in attendees:
                attendees.append(p.name)
    if action == "block_focus" and attendees and re.search(r"\b(with|meet|sync|call)\b", clean, re.I):
        action = "schedule_meeting"  # "block time with Dev" is a meeting
    if action == "show_analytics" and attendees and re.search(r"\b(schedule|book|set up|find time)\b", clean, re.I):
        action = "schedule_meeting"
    duration = _duration(clean)
    if action == "unknown" and attendees and (duration or re.search(r"\b(need|want|get|grab|time)\b", clean, re.I)):
        action = "schedule_meeting"  # "I need 2 hours with Nina and Dev" - people + time means a meeting
    target_text = clean
    if action == "reschedule_event":
        parts = re.split(r"\s+(?:to|until|till)\s+", clean, maxsplit=1, flags=re.I)
        target_text = parts[1] if len(parts) > 1 else ""
    window = resolve_window(target_text, today) if action != "reschedule_event" or target_text else None
    tod, earliest, latest = _time_limits(target_text if action == "reschedule_event" else clean)
    focus_hours = None
    if action == "block_focus":
        focus_hours = round(duration / 60, 2) if duration else 2.0
    reminder = None
    if action == "set_reminder":
        m = re.search(r"(\d+)\s*(minutes?|mins?|hours?|h)\b", clean, re.I)
        if m:
            reminder = int(m.group(1)) * (60 if m.group(2).lower().startswith("h") else 1)
        duration = None
    title = _title(clean, action, attendees)
    target = _target(clean, action)
    if action in ("reschedule_event", "cancel_event", "brief_event", "set_reminder"):
        attendees_out, optional_out = [], []
    else:
        attendees_out, optional_out = attendees, optional
    filled = sum(x is not None and x != [] for x in (attendees_out or None, duration, window, tod, target, focus_hours))
    confidence = 0.35 if action == "unknown" else min(0.95, 0.55 + 0.1 * filled)
    return ParsedCommand(
        action=action,  # type: ignore[arg-type]
        title=title,
        attendees=attendees_out,
        optional_attendees=optional_out,
        duration_minutes=duration if action not in ("set_reminder",) else None,
        window=window,
        time_of_day=tod,  # type: ignore[arg-type]
        earliest_time=earliest,
        latest_time=latest,
        target_event=target,
        focus_hours=focus_hours,
        reminder_minutes_before=reminder,
        confidence=round(confidence, 2),
    )
