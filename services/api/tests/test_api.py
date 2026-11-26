"""End-to-end API tests: every feature's HTTP surface, exercised against the seeded demo world."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.timeutils import iso


def _week(now: datetime, weeks: int = 0) -> tuple[str, str]:
    s = now - timedelta(days=now.weekday()) + timedelta(weeks=weeks) - timedelta(days=1)
    return iso(s) or "", iso(s + timedelta(days=9)) or ""


def test_health_and_profile(client) -> None:
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["events"] > 500 and h["ai"]["engine"] == "offline" and h["simulated_clock"]
    me = client.get("/api/me").json()
    assert me["person"]["name"] == "Maya Chen" and me["preferences"]["focus_goal_hours"] == 10
    people = client.get("/api/people").json()
    assert {p["first_name"] for p in people} >= {"Priya", "Alex", "Dev", "Emma", "Arjun"}


def test_events_window_with_conflict_flags_and_holidays(client, now) -> None:
    s, e = _week(now, 0)
    r = client.get("/api/events", params={"start": s, "end": e})
    assert r.status_code == 200
    body = r.json()
    assert body["timezone"] == "America/Los_Angeles"
    assert any(h["name"].startswith("Thanksgiving") for h in body["holidays"])
    qbr = next(x for x in body["events"] if x["id"] == "plant_qbr")
    assert "overlap" in qbr["flags"] and qbr["priority"] >= 80
    assert client.get("/api/events", params={"start": e, "end": s}).status_code == 400


def test_f1_suggest_book_learn_and_undo(client, now) -> None:
    nm = now + timedelta(days=(7 - now.weekday()))
    r = client.post("/api/schedule/suggest", json={
        "attendee_ids": ["dev", "alex"], "duration_min": 45, "window_start": iso(nm), "window_end": iso(nm + timedelta(days=5))})
    assert r.status_code == 200
    res = r.json()
    assert len(res["slots"]) >= 3 and res["stats"]["elapsed_ms"] < 2000
    top, second = res["slots"][0], res["slots"][1]
    assert top["reasons"] and {a["person_id"] for a in top["attendees"]} >= {"maya", "dev", "alex"}
    book = client.post("/api/schedule/book", json={
        "title": "Tooling roadmap sync", "start": second["start"], "end": second["end"], "attendee_ids": ["dev", "alex"],
        "chosen_rank": 2, "chosen_components": second["components"], "shown_components": [s["components"] for s in res["slots"]]})
    assert book.status_code == 200, book.text
    out = book.json()
    assert out["learned"] is not None
    ev = client.get(f"/api/events/{out['event_id']}").json()
    assert ev["title"] == "Tooling roadmap sync" and ev["ai_generated"]
    # the same slot is no longer free -> optimistic re-check returns 409
    again = client.post("/api/schedule/book", json={"title": "x", "start": second["start"], "end": second["end"], "attendee_ids": ["dev"]})
    assert again.status_code == 409
    assert client.post(f"/api/audit/{out['audit_id']}/undo").status_code == 200
    assert client.get(f"/api/events/{out['event_id']}").status_code == 404
    assert client.post(f"/api/audit/{out['audit_id']}/undo").status_code == 400  # double undo rejected


def test_f1_no_shared_hours_offers_fair_relaxation(client, now) -> None:
    nm = now + timedelta(days=(7 - now.weekday()))
    res = client.post("/api/schedule/suggest", json={
        "attendee_ids": ["priya", "alex"], "duration_min": 45, "window_start": iso(nm), "window_end": iso(nm + timedelta(days=5))}).json()
    assert res["slots"] == []
    kinds = [r["kind"] for r in res["relaxations"]]
    assert "stretch" in kinds
    stretch = next(r for r in res["relaxations"] if r["kind"] == "stretch")
    res2 = client.post("/api/schedule/suggest", json={
        "attendee_ids": ["priya", "alex"], "duration_min": 45, "window_start": iso(nm), "window_end": iso(nm + timedelta(days=5)),
        **stretch["patch"]}).json()
    assert res2["slots"], "applying the suggested relaxation must yield slots"


def test_f2_conflicts_resolve_and_undo(client) -> None:
    cs = client.get("/api/conflicts").json()
    types = {c["type"] for c in cs}
    assert {"overlap", "travel", "focus", "overload", "outside_hours"} <= types
    overlap = next(c for c in cs if c["type"] == "overlap")
    move = next(o for o in overlap["options"] if o["kind"] == "move")
    r = client.post("/api/conflicts/resolve", json={"conflict_id": overlap["id"], "option_id": move["id"]})
    assert r.status_code == 200, r.text
    after = client.get("/api/conflicts").json()
    assert overlap["id"] not in {c["id"] for c in after}
    assert client.post(f"/api/audit/{r.json()['audit_id']}/undo").status_code == 200
    assert overlap["id"] in {c["id"] for c in client.get("/api/conflicts").json()}
    travel = next(c for c in after if c["type"] == "travel")
    remote = next(o for o in travel["options"] if o["kind"] == "remote_join")
    assert remote["draft"]["body"]
    assert client.post("/api/conflicts/resolve", json={"conflict_id": travel["id"], "option_id": remote["id"]}).status_code == 200
    assert travel["id"] not in {c["id"] for c in client.get("/api/conflicts").json()}


def test_undo_never_clobbers_later_edits_and_always_bumps_the_version(client) -> None:
    def rename(title: str, version: int):
        return client.post("/api/operations", json={"operations": [
            {"op": "update", "event_id": "plant_vendor", "expected_version": version, "changes": {"title": title}}]})

    original = client.get("/api/events/plant_vendor").json()
    v0 = original["version"]
    a1 = rename("Renamed once", v0)
    a2 = rename("Renamed twice", v0 + 1)
    assert a1.status_code == a2.status_code == 200
    # Undoing the older action would silently overwrite the newer one: refused.
    assert client.post(f"/api/audit/{a1.json()['audit_id']}/undo").status_code == 409
    assert client.post(f"/api/audit/{a2.json()['audit_id']}/undo").status_code == 200
    ev = client.get("/api/events/plant_vendor").json()
    assert ev["title"] == "Renamed once" and ev["version"] > v0 + 2
    assert rename("Stale client", v0 + 2).status_code == 409  # holder of the pre-undo version is rejected
    # With the later change undone, the earlier undo is allowed again.
    assert client.post(f"/api/audit/{a1.json()['audit_id']}/undo").status_code == 200
    ev = client.get("/api/events/plant_vendor").json()
    assert ev["title"] == original["title"]
    assert rename("Stale client", v0 + 1).status_code == 409  # post-apply version no longer valid after undo

    # Undoing a dismissal restores only that conflict, not ones dismissed later.
    cs = client.get("/api/conflicts").json()
    first, second = cs[0]["id"], cs[1]["id"]
    d1, d2 = (client.post("/api/operations", json={"operations": [{"op": "dismiss_conflict", "person_id": "maya", "conflict_id": c}]})
              for c in (first, second))
    assert client.post(f"/api/audit/{d1.json()['audit_id']}/undo").status_code == 200
    ids = {c["id"] for c in client.get("/api/conflicts").json()}
    assert first in ids and second not in ids
    assert client.post(f"/api/audit/{d2.json()['audit_id']}/undo").status_code == 200


def test_bad_input_is_a_400_not_a_crash(client) -> None:
    r = client.post("/api/schedule/book", json={"title": "x", "start": "2026-12-01T17:00:00Z", "end": "2026-12-01T17:30:00Z",
                                                 "attendee_ids": ["ghost"]})
    assert r.status_code == 400 and "ghost" in r.text
    assert client.get("/api/analytics/summary").status_code == 200
    assert client.get("/api/events", params={"start": "2026-11-30T00:00:00", "end": "2026-12-01T00:00:00"}).status_code == 400
    assert client.post("/api/operations", json={"operations": [{"op": "create"}]}).status_code == 400


def test_f3_reminders_toggle_digest_and_brief(client) -> None:
    plan = client.get("/api/events/plant_onsite/reminders").json()["reminders"]
    kinds = {r["kind"] for r in plan}
    assert {"prep", "leave", "followup"} <= kinds
    leave = next(r for r in plan if r["kind"] == "leave")
    assert "Palo Alto" in leave["rationale"]
    recap = next(r for r in plan if r["kind"] == "followup")["action"]["draft"]
    assert recap["subject"].startswith("Recap:") and recap["body"].rstrip().endswith("Maya")  # signed by the current user
    assert client.patch("/api/events/plant_onsite/reminders/followup", json={"enabled": False}).status_code == 200
    plan2 = client.get("/api/events/plant_onsite/reminders").json()["reminders"]
    assert next(r for r in plan2 if r["kind"] == "followup")["enabled"] is False
    assert client.patch("/api/events/plant_onsite/reminders/bogus", json={"enabled": False}).status_code == 400
    up = client.get("/api/reminders/upcoming", params={"hours": 168}).json()
    assert up and all("fire_at" in r for r in up)
    digest = client.get("/api/digest").json()
    assert "headline" in digest
    b = client.get("/api/events/plant_qbr/brief").json()
    assert b["engine"] == "template" and b["brief"]["agenda"] and b["brief"]["purpose"]
    assert sum(i["minutes"] for i in b["brief"]["agenda"]) == 60
    assert client.get("/api/events/plant_qbr/brief").json()["cached"] is True
    detail = client.get("/api/events/plant_qbr").json()
    assert detail["cost"] > 0 and detail["priority_factors"]


def test_f4_f7_analytics_forecast_recurring_insights(client) -> None:
    s = client.get("/api/analytics/summary").json()
    assert len(s["weeks"]) == 13 and s["kpis"] and s["heatmap"]["minutes_per_week"]
    assert any(f["name"] == "Arjun Rao" for f in s["fairness"])
    f = client.get("/api/analytics/forecast").json()
    nxt = next(w for w in f["weeks"] if w["offset"] == 1)
    assert nxt["low"] <= nxt["forecast_hours"] <= nxt["high"] and 0 <= nxt["p_over_cap"] <= 1
    assert f["backtest"]["evaluated_weeks"] >= 5 and f["backtest"]["by_lead"]
    rec = client.get("/api/analytics/recurring").json()
    kinds = {r["series_id"]: r["suggestion"]["kind"] for r in rec}
    assert kinds["s_cs_team"] == "shorten" and kinds["s_pipeline"] == "async"
    prop = client.post("/api/analytics/recurring/s_cs_team/proposal").json()
    assert prop["proposal"]["operations"] and prop["draft"]["body"]
    applied = client.post(f"/api/proposals/{prop['proposal']['id']}/apply")
    assert applied.status_code == 200
    assert client.post(f"/api/proposals/{prop['proposal']['id']}/apply").status_code == 400
    cards = client.get("/api/insights").json()
    assert {"conflict", "focus", "meeting_tip"} <= {c["kind"] for c in cards}


def test_f5_focus_protect_and_defrag(client) -> None:
    p = client.post("/api/focus/protect", json={}).json()
    assert p["proposal"] and p["plan"]["added_hours"] > 0 and not p["applied"]
    r = client.post(f"/api/proposals/{p['proposal']['id']}/apply")
    assert r.status_code == 200
    d = client.post("/api/focus/defrag", json={}).json()
    assert d["plan"]["after_hours"] >= d["plan"]["before_hours"]
    # autonomy = auto applies focus protection without asking
    client.put("/api/me/preferences", json={"autonomy": {"focus": "auto"}, "focus_goal_hours": 16})
    auto = client.post("/api/focus/protect", json={}).json()
    assert auto["applied"] is True or auto["proposal"] is None


def test_f6_command_bar_offline(client) -> None:
    r = client.post("/api/assistant/command", json={"text": "Find 45 min with Dev and Alex next week, mornings"}).json()
    assert r["engine"]["engine"] == "offline" and r["result"]["type"] == "slots" and r["result"]["slots"]
    assert any(c["label"] == "With" for c in r["chips"])
    r = client.post("/api/assistant/command", json={"text": "What conflicts do I have?"}).json()
    assert r["result"]["type"] == "conflicts" and r["result"]["conflicts"]
    r = client.post("/api/assistant/command", json={"text": "How much time did I spend in meetings last week?"}).json()
    assert r["result"]["type"] == "analytics" and "Last week" in r["result"]["headline"]
    r = client.post("/api/assistant/command", json={"text": "Brief me on the Brightwave QBR"}).json()
    assert r["result"]["type"] == "brief" and r["result"]["event"]["id"] == "plant_qbr"
    r = client.post("/api/assistant/command", json={"text": "Block 2 hours for the FY27 strategy before Friday"}).json()
    assert r["result"]["type"] in ("proposal", "clarify")
    r = client.post("/api/assistant/command", json={"text": "Move my 1:1 with Alex to Thursday afternoon"}).json()
    assert r["result"]["type"] == "slots" and r["result"]["mode"] == "reschedule"
    r = client.post("/api/assistant/command", json={"text": "Remind me 30 minutes before the Cobalt Health onsite"}).json()
    assert r["result"]["type"] == "reminder" and r["result"]["minutes_before"] == 30
    r = client.post("/api/assistant/command", json={"text": "What's the weather like?"}).json()
    assert r["result"]["type"] == "help"
    assert client.post("/api/assistant/command", json={"text": "  "}).status_code == 400
    log = client.get("/api/ai/status").json()
    assert log["calls"] and log["status"]["engine"] == "offline"


def test_events_crud_version_conflict(client, now) -> None:
    start = now + timedelta(days=8, hours=3)
    r = client.post("/api/events", json={"title": "Budget review", "start": iso(start), "end": iso(start + timedelta(minutes=30)),
                                         "attendee_ids": ["nina"]})
    assert r.status_code == 200
    eid = r.json()["event_id"]
    ev = client.get(f"/api/events/{eid}").json()
    ok = client.patch(f"/api/events/{eid}", json={"title": "Budget review v2", "expected_version": ev["version"]})
    assert ok.status_code == 200
    stale = client.patch(f"/api/events/{eid}", json={"title": "stale", "expected_version": ev["version"]})
    assert stale.status_code == 409
    bad = client.patch(f"/api/events/{eid}", json={"end": iso(start - timedelta(hours=1))})
    assert bad.status_code == 400
    assert client.delete(f"/api/events/{eid}").status_code == 200


def test_research_feedback_metrics_export(client) -> None:
    assert client.post("/api/feedback", json={"target_type": "card", "target_id": "card_x", "rating": 1, "reasons": ["useful"]}).status_code == 200
    assert client.post("/api/feedback", json={"target_type": "card", "target_id": "card_y", "rating": 5}).status_code == 422
    assert client.post("/api/research/results", json={"participant_id": "P01", "task_id": "T1", "duration_s": 74.5, "success": "yes", "seq": 6}).status_code == 200
    assert client.post("/api/research/results", json={"participant_id": "P01", "task_id": "T2", "success": "maybe"}).status_code == 400
    client.post("/api/assistant/command", json={"text": "Find 30 min with Nina tomorrow"})
    m = client.get("/api/research/metrics").json()
    assert m["feedback"]["up"] == 1 and m["tasks"][0]["task_id"] == "T1" and m["suggestions_shown"] >= 1
    csv_text = client.get("/api/research/export.csv").text
    assert "study" in csv_text and "feedback" in csv_text


def test_ics_import_and_google_status(client) -> None:
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
        "BEGIN:VEVENT\r\nUID:weekly-1\r\nSUMMARY:Board prep\r\nDTSTART:20261201T170000Z\r\nDTEND:20261201T180000Z\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=3\r\nATTENDEE:mailto:dev@lumora.example\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:allday\r\nSUMMARY:Offsite\r\nDTSTART;VALUE=DATE:20261203\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    r = client.post("/api/import/ics", files={"file": ("cal.ics", ics.encode(), "text/calendar")})
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 3, "skipped": 0}
    again = client.post("/api/import/ics", files={"file": ("cal.ics", ics.encode(), "text/calendar")}).json()
    assert again == {"imported": 0, "skipped": 3}
    assert client.post("/api/import/ics", files={"file": ("x.ics", b"not a calendar", "text/calendar")}).status_code == 400
    g = client.get("/api/integrations/google/status").json()
    assert g["configured"] is False and g["scopes"]
    assert client.post("/api/integrations/google/sync").status_code == 501


def test_demo_clock(client) -> None:
    r = client.post("/api/demo/clock", json={"now": "2026-11-30T16:00:00Z"}).json()
    assert r["now"] == "2026-11-30T16:00:00Z"
    due = client.get("/api/reminders/upcoming", params={"hours": 6}).json()
    assert any(x["event_id"] == "plant_onsite" for x in due)
