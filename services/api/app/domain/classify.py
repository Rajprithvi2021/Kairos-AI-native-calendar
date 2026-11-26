"""Rule-based event categorisation, explainable priority scoring and travel-time estimates.

These are the deterministic "twins" of what an ML model would learn in production; every score
comes with its contributing factors so the UI can explain it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from app.domain.calendar_data import CATEGORY_META, Ev, Snapshot

_HIGH_STAKES = re.compile(r"\b(qbr|board|renewal|escalation|offer|launch|onsite|exec|pricing)\b", re.I)


def _kw(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


_HIRING = _kw("interview", "candidate", "debrief", "hiring")
_VENDOR = _kw("vendor", "demo", "partner", "agency")
_CUSTOMER = _kw("qbr", "onsite", "kickoff", "escalation call")
_TEAM_FIRST = _kw("standup", "stand-up", "all-hands", "team meeting")
_LEADERSHIP = _kw("staff", "exec", "leadership", "board", "offsite")
_PLANNING = _kw("planning", "review", "strategy", "roadmap", "retro", "okr", "forecast")
_TEAM = _kw("sync", "team", "weekly")
_PERSONAL = _kw("lunch", "gym", "doctor", "pickup", "dentist")


def categorize(title: str, kind: str, participants: Iterable[Any]) -> str:
    """Keyword + attendee heuristics with word boundaries ("onboarding" is not "board")."""
    people = list(participants)
    if kind in ("focus", "prep"):
        return "focus"
    if kind == "personal":
        return "personal"
    if _HIRING.search(title):
        return "hiring"
    if any(getattr(p, "is_external", False) for p in people):
        return "external" if _VENDOR.search(title) else "customer"
    if _CUSTOMER.search(title):
        return "customer"
    if _VENDOR.search(title):
        return "external"
    if _TEAM_FIRST.search(title):
        return "team"
    if _LEADERSHIP.search(title):
        return "leadership"
    if _PLANNING.search(title):
        return "planning"
    if "1:1" in title or len(people) == 2:
        return "one_on_one"
    if _TEAM.search(title):
        return "team"
    if _PERSONAL.search(title):
        return "personal"
    return "admin"


def category_label(cat: str) -> str:
    return CATEGORY_META.get(cat, CATEGORY_META["admin"])["label"]


_BASE = {
    "customer": 70,
    "leadership": 65,
    "hiring": 60,
    "planning": 55,
    "one_on_one": 50,
    "external": 45,
    "focus": 45,
    "personal": 55,
    "team": 35,
    "admin": 30,
}


def priority(ev: Ev, snap: Snapshot, user_id: str) -> tuple[int, list[dict[str, Any]]]:
    """0-100 importance of an event *for this user*, with signed contributing factors."""
    factors: list[dict[str, Any]] = []
    base = _BASE.get(ev.category, 30)
    factors.append({"label": f"{category_label(ev.category)} meeting", "points": base})
    score = base
    others = [snap.people[p] for p in ev.participant_ids() if p in snap.people and p != user_id]

    def add(label: str, pts: int) -> None:
        nonlocal score
        score += pts
        factors.append({"label": label, "points": pts})

    if any(p.is_external for p in others):
        add("External attendees", 10)
    top = max((p.seniority for p in others), default=0)
    if top >= 5:
        add("CEO attending", 10)
    elif top >= 4:
        add("Senior leader attending", 5)
    if ev.organizer_id == user_id:
        add("You organise it", 5)
    if ev.series_id:
        add("Recurring (can catch the next one)", -5)
    elif ev.kind == "meeting":
        add("One-off", 8)
    if ev.is_optional_for(user_id):
        add("You're optional", -20)
    if _HIGH_STAKES.search(ev.title):
        add("High-stakes topic", 10)
    if len(others) >= 7 and ev.organizer_id != user_id:
        add("Large meeting (your absence matters less)", -5)
    return max(0, min(100, score)), factors


# --- travel -------------------------------------------------------------------------------
LOCATIONS: dict[str, tuple[float, float]] = {
    "Lumora HQ, San Francisco": (37.7897, -122.3942),
    "Cobalt Health, Palo Alto": (37.4419, -122.1430),
    "Brightwave Logistics, Oakland": (37.8044, -122.2712),
    "Fernway Retail, San Jose": (37.3382, -121.8863),
}


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def travel_minutes(origin: str | None, dest: str | None) -> int:
    """Door-to-door estimate (prototype: distance model; production: Maps API with live traffic)."""
    if not origin or not dest or origin == dest:
        return 0
    a, b = LOCATIONS.get(origin), LOCATIONS.get(dest)
    if a and b:
        return int(5 * round((8 + _km(a, b) * 1.05) / 5))
    return 30


def is_in_person(ev: Ev) -> bool:
    return bool(ev.location) and not ev.is_virtual
