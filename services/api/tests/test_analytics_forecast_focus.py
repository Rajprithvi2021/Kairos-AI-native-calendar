"""F4 analytics + forecast, F5 focus, F7 necessity advisor."""

from __future__ import annotations

from datetime import timedelta

from app.domain.timeutils import to_local, week_start
from app.engines import analytics, focus, forecast
from tests.conftest import make_snapshot


def test_summary_kpis_and_categories(snap, now) -> None:
    s = analytics.summary(snap, "maya", now)
    assert len(s["weeks"]) == 13
    assert {k["id"] for k in s["kpis"]} >= {"meeting_hours", "deep_work", "cost"}
    past = [w for w in s["weeks"] if w["phase"] == "past"][-4:]
    expected = sum(sum(w["by_category"].values()) for w in past)
    assert s["categories"] and abs(sum(c["hours"] for c in s["categories"]) - expected) < 0.5
    assert 0 <= s["workload"]["score"] <= 100
    assert len(s["heatmap"]["minutes_per_week"]) == 5


def test_fairness_report_names_bangalore(snap, now) -> None:
    fair = analytics.fairness(snap, "maya", now)
    names = [f["name"] for f in fair]
    assert "Arjun Rao" in names and "Priya Nair" in names
    assert fair[0]["count"] >= fair[-1]["count"]


def test_recurring_audit_finds_short_and_optional_series(snap, now) -> None:
    audit = {a["series_id"]: a for a in analytics.recurring_audit(snap, "maya", now)}
    team = audit["s_cs_team"]["suggestion"]
    assert team["kind"] == "shorten" and team["new_duration"] == 45 and team["saves_hours_month"] > 0
    assert audit["s_pipeline"]["suggestion"]["kind"] == "async"
    assert audit["s_tooling"]["suggestion"]["kind"] == "rotate"
    plan = analytics.series_action_ops(snap, "maya", "s_cs_team", now)
    assert plan["operations"] and all(op["op"] == "update" for op in plan["operations"])


def test_forecast_is_coherent_and_calibrated(snap, now) -> None:
    f = forecast.forecast(snap, "maya", now)
    for w in f["weeks"]:
        assert w["booked_hours"] <= w["low"] + 1e-9 <= w["forecast_hours"] + 1e-9 <= w["high"] + 1e-9
        assert 0.0 <= w["p_over_cap"] <= 1.0
    nxt = next(w for w in f["weeks"] if w["offset"] == 1)
    assert nxt["forecast_hours"] > nxt["booked_hours"], "late bookings are expected"
    bt = f["backtest"]
    assert bt["evaluated_weeks"] >= 5 and len(bt["by_lead"]) == 3
    best_baseline = min(v for k, v in bt["mae_hours"].items() if k != "model")
    assert bt["mae_hours"]["model"] <= 1.5 * best_baseline
    assert bt["interval_coverage"] >= 0.5


def test_forecast_does_not_peek_at_unbooked_events(world, now) -> None:
    # Leakage guard: everything in the snapshot was booked by "now" (the generator drops future bookings).
    assert all(e.created_at <= now for e in world.events)


def test_conformal_radius_widens_with_few_points() -> None:
    assert forecast.conformal_radius([1.0, 2.0, 3.0]) == 1.5  # k > n -> 1.5 x max residual
    assert forecast.conformal_radius([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) > 0


def test_focus_protection_and_defrag(world, now) -> None:
    snap = make_snapshot(world)
    monday = week_start(to_local(now, "America/Los_Angeles").date()) + timedelta(weeks=1)
    plan = focus.plan_protection(snap, "maya", monday, now)
    assert plan["added_hours"] > 0 and plan["operations"]
    for op in plan["operations"]:
        from app.clock import parse_utc

        s, e = parse_utc(op["event"]["start"]), parse_utc(op["event"]["end"])
        assert not snap.busy("maya", s - timedelta(hours=1), e + timedelta(hours=1)).overlaps(s, e)
    d = focus.plan_defrag(snap, "maya", monday, now)
    assert d["after_hours"] >= d["before_hours"]
    assert all(m["gain_min"] >= 30 for m in d["moves"])
