"""Copilot feed: turns engine outputs into a short, ranked list of actionable, explainable cards.

Every card says what Kairos noticed, why it matters (impact), what it proposes (actions) and why
(explanation). Cards carry stable ids so 👍/👎 feedback can be attributed and learned from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.engines.conflicts import TYPE_LABEL, Conflict
from app.engines.reminders import PlannedReminder


def build_feed(
    conflicts: list[Conflict],
    forecast: dict[str, Any],
    audit: list[dict[str, Any]],
    fairness: list[dict[str, Any]],
    reminders: list[PlannedReminder],
    focus_goal: float,
    now: datetime,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    rank = {"high": 0, "medium": 1, "low": 2}
    for c in sorted(conflicts, key=lambda c: (rank[c.severity], c.starts_at))[:6]:
        top = c.options[0] if c.options else None
        cards.append({
            "id": f"card_{c.id}", "kind": "conflict", "section": "attention", "severity": c.severity,
            "title": TYPE_LABEL.get(c.type, "Conflict"), "body": c.title, "detail": c.description,
            "impact": None, "explanation": f"Suggested fix: {top.label}" if top else "",
            "actions": [{"type": "open_conflict", "label": "Resolve", "conflict_id": c.id}],
            "day": c.day,
        })

    weeks = forecast.get("weeks", [])
    nxt = next((w for w in weeks if w["offset"] == 1), None)
    if nxt and nxt["focus_at_risk"]:
        cards.append({
            "id": f"card_focus_{nxt['week_start']}", "kind": "focus", "section": "insights", "severity": "medium",
            "title": "Focus time at risk next week",
            "body": f"Only {nxt['protected_focus_hours']:g}h of your {focus_goal:g}h focus goal is protected; "
                    f"~{max(0.0, round(nxt['forecast_hours'] - nxt['booked_hours'], 1)):g}h more meetings are likely to land.",
            "detail": f"{nxt['booked_hours']}h of meetings booked so far; history says ~{nxt['forecast_hours']}h by the end "
                      f"(80% range {nxt['low']}–{nxt['high']}h).",
            "impact": f"Protect up to {focus_goal:g}h before it gets booked",
            "explanation": "Late bookings usually fill next week's open time; protecting focus now is cheaper than defending it later.",
            "actions": [{"type": "focus_plan", "label": "Protect focus", "week_start": nxt["week_start"]},
                        {"type": "defrag", "label": "Defrag the week", "week_start": nxt["week_start"]}],
        })
    risky = [w for w in weeks if w["offset"] >= 1 and w["p_over_cap"] >= 0.5]
    if risky:
        w = risky[0]
        cards.append({
            "id": f"card_overload_{w['week_start']}", "kind": "forecast", "section": "insights", "severity": "medium",
            "title": f"{w['label']} likely over your meeting cap",
            "body": f"{round(w['p_over_cap'] * 100)}% chance of more than {forecast['max_week_hours']:g}h of meetings.",
            "detail": f"Forecast {w['forecast_hours']}h (80% range {w['low']}–{w['high']}h); {w['booked_hours']}h booked today.",
            "impact": None, "explanation": forecast.get("method", ""),
            "actions": [{"type": "navigate", "label": "See forecast", "to": "/insights"}],
        })

    for a in [x for x in audit if x["suggestion"]["kind"] in ("shorten", "async")][:2]:
        s = a["suggestion"]
        cards.append({
            "id": f"card_series_{a['series_id']}", "kind": "meeting_tip", "section": "insights", "severity": "low",
            "title": f"{s['label']}: “{a['title']}”", "body": s["detail"],
            "detail": f"{a['cadence']} · {a['attendees']} people · ${a['cost_month']:,}/month",
            "impact": f"Saves ~{s['saves_hours_month']}h/month" + (f" (${s['saves_cost_month']:,})" if s["saves_cost_month"] else ""),
            "explanation": "Based on how long this series actually runs and your attendance.",
            "actions": [{"type": "series_action", "label": "Apply", "series_id": a["series_id"]}],
        })

    for f in fairness[:1]:
        if f["count"] >= 3:
            cards.append({
                "id": f"card_fair_{f['person_id']}", "kind": "fairness", "section": "insights", "severity": "low",
                "title": f"{f['city']} keeps taking the late calls",
                "body": f"{f['name']}: {f['count']} meetings outside working hours (last 4 weeks + next 2).",
                "detail": "; ".join(f["examples"]),
                "impact": "Fairer rotation improves retention and meeting quality",
                "explanation": "Kairos' scheduler optimises the worst-off attendee's local time, not just yours.",
                "actions": [{"type": "navigate", "label": "See fairness report", "to": "/insights#fairness"}],
            })

    for r in [r for r in reminders if r.kind == "prep" and r.action][:2]:
        cards.append({
            "id": f"card_prep_{r.event_id}", "kind": "prep", "section": "upnext", "severity": "low",
            "title": r.title, "body": r.rationale, "detail": None, "impact": None,
            "explanation": "Prep time is sized by meeting type, priority and first contact with externals.",
            "actions": [{"type": "operations", "label": r.action["label"], "operations": r.action["operations"],
                         "summary": f"Block prep time for {r.event_title}"},
                        {"type": "open_event", "label": "Open meeting", "event_id": r.event_id}],
            "at": r.fire_at.isoformat(),
        })
    return cards
