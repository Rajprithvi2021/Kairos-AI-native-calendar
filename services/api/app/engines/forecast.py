"""Predictive time analytics (F4): forecast next weeks' meeting load *before* it happens.

Model - "booking pickup" (borrowed from airline/hotel revenue management):
    final_hours(week) = hours booked so far + late bookings still to come
Late bookings are learned from the user's own history: for every past week we know what was on the
calendar N days before it started (events carry created_at) and what it finally looked like.
For an upcoming week starting in N days, the empirical distribution of (final - booked at N days)
gives a point forecast (median) and an 80% interval (10th-90th percentile, split-conformal style),
plus the probability of exceeding the user's weekly meeting cap.

Validation: rolling-origin backtest against three naive baselines (booked-so-far, last week,
trailing 4-week mean), reporting MAE and 80%-interval coverage. On synthetic data this proves the
pipeline is correct and beats naive baselines under the simulator's assumptions - not that it is
accurate on real calendars; that needs a shadow pilot (see docs/04).
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from typing import Any

from app.domain.calendar_data import Snapshot
from app.domain.timeutils import local_midnight_utc, to_local, week_start
from app.engines.analytics import deep_work_minutes


def conformal_radius(values: list[float], alpha: float = 0.2) -> float:
    """Split-conformal half-width around the median: the ceil((n+1)(1-alpha))-th smallest absolute
    residual. Honest with tiny samples (widens instead of pretending), unlike raw percentiles."""
    if not values:
        return 0.0
    med = statistics.median(values)
    res = sorted(abs(v - med) for v in values)
    k = math.ceil((len(res) + 1) * (1 - alpha))
    return res[-1] * 1.5 if k > len(res) else res[k - 1]


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _hours(snap: Snapshot, uid: str, s: datetime, e: datetime, as_of: datetime | None = None) -> float:
    total = 0.0
    for ev in snap.events_for(uid, s, e, ("meeting",)):
        if as_of is not None and ev.created_at is not None and ev.created_at > as_of:
            continue
        total += (min(ev.end, e) - max(ev.start, s)).total_seconds() / 3600
    return total


def forecast(snap: Snapshot, uid: str, now: datetime, horizon: int = 4, history: int = 12) -> dict[str, Any]:
    tzname = snap.person(uid).timezone
    prefs = snap.pref(uid)
    cap = prefs.max_meeting_hours_week
    this_monday = week_start(to_local(now, tzname).date())

    def bounds(k: int) -> tuple[datetime, datetime]:
        m = this_monday + timedelta(weeks=k)
        return local_midnight_utc(m, tzname), local_midnight_utc(m + timedelta(days=7), tzname)

    hist = []
    for k in range(1, history + 1):
        s, e = bounds(-k)
        hist.append({"k": k, "start": s, "end": e, "final": _hours(snap, uid, s, e)})

    def additions_at(lead_days: float, weeks: list[dict[str, Any]]) -> list[float]:
        return [w["final"] - _hours(snap, uid, w["start"], w["end"], w["start"] - timedelta(days=lead_days)) for w in weeks]

    weeks_out = []
    trailing = statistics.mean(w["final"] for w in hist[:4]) if hist else 0.0
    # Current week: condition on how far into the week we are.
    s0, e0 = bounds(0)
    elapsed = now - s0
    adds0 = [w["final"] - _hours(snap, uid, w["start"], w["end"], w["start"] + elapsed) for w in hist]
    booked0 = _hours(snap, uid, s0, e0, now)
    weeks_out.append(_point(0, s0, booked0, adds0, trailing, cap, snap, uid, now, prefs.focus_goal_hours))
    for k in range(1, horizon + 1):
        s, e = bounds(k)
        lead = (s - now).total_seconds() / 86400
        booked = _hours(snap, uid, s, e, now)
        weeks_out.append(_point(k, s, booked, additions_at(lead, hist), trailing, cap, snap, uid, now, prefs.focus_goal_hours))

    return {
        "method": "Ensemble of a booking-pickup model (booked so far + median late bookings at the same lead time) "
                  "and max(booked, 4-week trailing mean); 80% split-conformal interval.",
        "max_week_hours": cap,
        "weeks": weeks_out,
        "backtest": backtest(snap, uid, now, history),
    }


def ensemble(booked: float, median_additions: float, trailing: float) -> float:
    """Average of the pickup forecast and max(booked, trailing mean): reacts to what is already booked
    while damping pickup noise in ordinary weeks."""
    return 0.5 * (booked + median_additions) + 0.5 * max(booked, trailing)


def _point(k: int, s: datetime, booked: float, adds: list[float], trailing: float, cap: float, snap: Snapshot, uid: str,
           now: datetime, goal: float) -> dict[str, Any]:
    tzname = snap.person(uid).timezone
    med = statistics.median(adds) if adds else 0.0
    radius = conformal_radius(adds)
    point = ensemble(booked, med, trailing)
    samples = [ensemble(booked, a, trailing) for a in adds]
    p_over = sum(1 for x in samples if x > cap) / len(samples) if samples else 0.0
    e = s + timedelta(days=7)
    deep_now = deep_work_minutes(snap, uid, max(s, now), e) / 60
    deep_forecast = max(0.0, deep_now - 1.2 * max(0.0, med))
    protected = sum(
        (min(f.end, e) - max(f.start, max(s, now))).total_seconds() / 3600
        for f in snap.events_for(uid, max(s, now), e, ("focus", "prep"))
    )
    local_monday = to_local(s, tzname).date()
    return {
        "offset": k,
        "week_start": local_monday.isoformat(),
        "label": "This week" if k == 0 else ("Next week" if k == 1 else f"{local_monday:%b} {local_monday.day}"),
        "booked_hours": round(booked, 1),
        "forecast_hours": round(point, 1),
        "low": round(max(booked, point - radius), 1),
        "high": round(point + radius, 1),
        "p_over_cap": round(p_over, 2),
        "deep_work_forecast": round(deep_forecast, 1),
        "protected_focus_hours": round(protected, 1),
        # Unprotected free time gets booked: the goal is only safe once it is actually blocked.
        "focus_at_risk": protected < goal or deep_forecast < goal,
    }


def backtest(snap: Snapshot, uid: str, now: datetime, history: int = 12, leads: tuple[float, ...] = (3.0, 7.0, 14.0)) -> dict[str, Any]:
    """Rolling-origin backtest at several lead times; reported as-is (no cherry-picking)."""
    runs = [_backtest_at(snap, uid, now, history, lead) for lead in leads]
    primary = next((r for r in runs if r["lead_days"] == 7.0), runs[0])
    wins = sum(1 for r in runs if r["beats_baselines"])
    return {**primary, "by_lead": runs, "wins": f"beats every naive baseline at {wins}/{len(runs)} lead times"}


def _backtest_at(snap: Snapshot, uid: str, now: datetime, history: int, lead_days: float) -> dict[str, Any]:
    tzname = snap.person(uid).timezone
    this_monday = week_start(to_local(now, tzname).date())
    weeks = []
    for k in range(1, history + 1):
        m = this_monday - timedelta(weeks=k)
        s, e = local_midnight_utc(m, tzname), local_midnight_utc(m + timedelta(days=7), tzname)
        weeks.append({"start": s, "end": e, "final": _hours(snap, uid, s, e),
                      "booked": _hours(snap, uid, s, e, s - timedelta(days=lead_days))})
    weeks.sort(key=lambda w: w["start"])
    errs: dict[str, list[float]] = {"model": [], "booked_so_far": [], "last_week": [], "trailing_mean": []}
    covered = 0
    n = 0
    for i in range(3, len(weeks)):  # rolling origin: learn only from strictly earlier weeks
        train = weeks[:i]
        w = weeks[i]
        adds = [t["final"] - t["booked"] for t in train]
        trailing = statistics.mean(t["final"] for t in train[-4:])
        pred = ensemble(w["booked"], statistics.median(adds), trailing)
        radius = conformal_radius(adds)
        lo, hi = max(w["booked"], pred - radius), pred + radius
        errs["model"].append(abs(pred - w["final"]))
        errs["booked_so_far"].append(abs(w["booked"] - w["final"]))
        errs["last_week"].append(abs(train[-1]["final"] - w["final"]))
        errs["trailing_mean"].append(abs(statistics.mean(t["final"] for t in train[-4:]) - w["final"]))
        covered += int(lo - 1e-9 <= w["final"] <= hi + 1e-9)
        n += 1
    mae = {k: round(statistics.mean(v), 2) if v else None for k, v in errs.items()}
    best_baseline = min((v for k, v in mae.items() if k != "model" and v is not None), default=None)
    return {
        "lead_days": lead_days,
        "evaluated_weeks": n,
        "mae_hours": mae,
        "interval_coverage": round(covered / n, 2) if n else None,
        "beats_baselines": bool(n and mae["model"] is not None and best_baseline is not None and mae["model"] <= best_baseline),
        "caveat": "Synthetic demo data: validates the pipeline, not real-world accuracy (needs a shadow pilot).",
    }
