"""End-to-end flows through the real UI (Next.js) and API (FastAPI), one test per key flow.

The browser runs in Asia/Kolkata on purpose: the calendar must render in the *user's* time zone
(San Francisco), not the browser's. Button locators use exact names (substring matching would
hit calendar events such as "Sync: onboarding playbook" for "Book"). Assertions hold whichever AI engine
the running API uses (offline twin, Claude or Gemini), so a key in services/api/.env doesn't break them.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import api, shot
from playwright.sync_api import Locator, Page, expect


def button(page: Page, name: str):
    return page.get_by_role("button", name=name, exact=True)


def show_event(page: Page, event_id: str) -> Locator:
    """Planted scenarios sit on the next business days, so they fall in this week or the next one
    depending on today's weekday: page forward until the event is on screen."""
    ev = page.locator(f'[data-event-id="{event_id}"]')
    heading = page.get_by_role("heading", level=1)
    for _ in range(2):
        expect(page.locator("[data-event-id]").first).to_be_visible()  # this week's events have loaded
        if ev.count():
            break
        label = heading.inner_text()
        button(page, "Next week").click()
        expect(heading).not_to_have_text(label)
    expect(ev).to_be_visible()
    return ev


def this_week_holidays() -> list[str]:
    """Holiday chips expected in the current week view (Monday-based, in the user's time zone)."""
    tz = ZoneInfo(api("GET", "/api/me")["person"]["timezone"])
    now = datetime.fromisoformat(api("GET", "/api/health")["now"]).astimezone(tz)
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    q = urllib.parse.urlencode({"start": start.isoformat(), "end": (start + timedelta(days=7)).isoformat()})
    return [f"{h['name']} ({h['country']})" for h in api("GET", f"/api/events?{q}")["holidays"]]


def conflicts_count(page: Page) -> int:
    badge = page.get_by_role("button", name=re.compile(r"^\d+ conflicts?$"))
    expect(badge).to_be_visible(timeout=30_000)  # "Checking…" until the conflict engine has answered
    return int(re.search(r"\d+", badge.inner_text()).group())


def test_calendar_workspace_renders_with_ai_overlays(page: Page) -> None:
    expect(page.get_by_text(re.compile(r"^P[SD]T · San Francisco$"))).to_be_visible()
    for holiday in this_week_holidays():  # e.g. "Thanksgiving Day (US)" in Thanksgiving week
        expect(page.get_by_text(holiday, exact=True)).to_be_visible()
    assert conflicts_count(page) >= 4
    expect(page.get_by_text("Needs attention", exact=False).first).to_be_visible()
    shot(page, "calendar")
    expect(show_event(page, "plant_qbr")).to_have_attribute("aria-label", re.compile("has a conflict"))


def test_f6_f1_command_bar_schedule_book_and_undo(page: Page) -> None:
    page.keyboard.press("Control+K")
    box = page.get_by_role("textbox", name="Ask Kairos")
    box.fill("Find 45 min with Dev and Alex next week, mornings")
    box.press("Enter")
    expect(page.get_by_text("Best times for")).to_be_visible(timeout=20_000)
    expect(page.get_by_text("With: Dev Patel, Alex Kim")).to_be_visible()
    expect(page.get_by_text(re.compile(r"^(Offline engine|Claude|Gemini)")).first).to_be_visible()
    shot(page, "command-bar")
    button(page, "Book").first.click()
    expect(page.get_by_text(re.compile(r"^Booked “"))).to_be_visible()  # the title wording depends on the engine
    audit = api("GET", "/api/audit?limit=1")[0]
    assert audit["action"] == "book_meeting" and not audit["undone"]
    button(page, "Undo").click()
    expect(page.get_by_text("Undone — your calendar is back as it was.")).to_be_visible()
    assert api("GET", "/api/audit?limit=1")[0]["undone"] is True


def test_f1_schedule_assistant_fair_relaxation_for_bangalore(page: Page) -> None:
    button(page, "New meeting").click()
    page.get_by_placeholder("e.g. Renewal strategy sync").fill("Support tooling roadmap")
    page.get_by_label("Add attendee", exact=True).select_option("priya")
    page.get_by_label("Add attendee", exact=True).select_option("alex")
    button(page, "Find the best times").click()
    relax = page.get_by_role("button", name=re.compile("Stretch working hours"))
    expect(relax).to_be_visible(timeout=20_000)
    expect(page.get_by_text("Here's what would have to give", exact=False)).to_be_visible()
    relax.click()
    expect(page.get_by_text(re.compile(r"Priya .* IST")).first).to_be_visible(timeout=20_000)
    shot(page, "schedule-assistant")
    button(page, "Book").first.click()
    expect(page.get_by_text(re.compile(r"^Booked “Support tooling roadmap”"))).to_be_visible()


def test_f2_conflict_center_preview_and_resolve(page: Page) -> None:
    before = conflicts_count(page)
    page.get_by_role("button", name=re.compile(r"^\d+ conflicts?$")).click()
    drawer = page.get_by_role("dialog", name="Conflict center")
    expect(drawer).to_be_visible()
    expect(drawer.get_by_text("Brightwave Logistics — QBR × Customer health review")).to_be_visible()
    drawer.get_by_role("button", name="Preview", exact=True).first.click()
    expect(page.get_by_text("Proposed", exact=True)).to_be_visible()
    shot(page, "conflict-center")
    drawer.get_by_role("button", name="Apply", exact=True).first.click()
    expect(page.get_by_text(re.compile(r"^Resolved: "))).to_be_visible()
    page.keyboard.press("Escape")
    remaining = before - 1
    expect(page.get_by_role("button", name=f"{remaining} conflict{'' if remaining == 1 else 's'}", exact=True)).to_be_visible()


def test_f3_event_drawer_smart_reminders_brief_and_prep(page: Page) -> None:
    show_event(page, "plant_onsite").click()
    drawer = page.get_by_role("dialog", name="Cobalt Health — onsite workshop")
    expect(drawer).to_be_visible()
    expect(drawer.get_by_text(re.compile(r"Leave by \d")).first).to_be_visible()
    expect(drawer.get_by_text("Palo Alto + 10 min buffer", exact=False)).to_be_visible()
    expect(drawer.get_by_text("Talking points", exact=True)).to_be_visible(timeout=30_000)  # brief rendered (any engine)
    shot(page, "event-drawer")
    drawer.get_by_label("followup reminder").uncheck()
    expect(drawer.get_by_label("followup reminder")).not_to_be_checked()
    drawer.get_by_role("button", name="Block prep time", exact=True).click()
    expect(page.get_by_text("Blocked prep time for Cobalt Health — onsite workshop")).to_be_visible()


def test_f5_copilot_protect_focus_proposal(page: Page) -> None:
    button(page, "Protect focus").click()
    expect(page.get_by_text("Nothing changes until you apply.")).to_be_visible()
    button(page, "Apply changes").click()
    expect(page.get_by_text(re.compile(r"Protect .*h of focus .* applied\."))).to_be_visible()


def test_f4_f7_insights_forecast_and_recurring_fix(page: Page) -> None:
    page.get_by_role("link", name="Insights").click()
    expect(page.get_by_role("heading", name="Insights")).to_be_visible(timeout=30_000)
    expect(page.get_by_text("Meeting-load forecast")).to_be_visible()
    expect(page.get_by_text("Model card · forecast")).to_be_visible()
    expect(page.locator(".recharts-bar-rectangle").first).to_be_visible(timeout=20_000)
    assert page.locator(".recharts-bar-rectangle").count() > 20
    expect(page.get_by_text("Arjun Rao").first).to_be_visible()
    shot(page, "insights")
    row = page.locator("tr", has_text="Weekly CS team meeting")
    row.get_by_role("button", name="Apply…").click()
    expect(page.get_by_text("Message draft")).to_be_visible()
    button(page, "Apply changes").click()
    expect(page.get_by_text(re.compile(r"Shorten to 45 min: Weekly CS team meeting — applied\."))).to_be_visible()


def test_settings_preferences_autonomy_and_ai_log(page: Page) -> None:
    page.get_by_role("link", name="Settings").click()
    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    page.get_by_label("Weekly focus goal (h)").fill("12")
    button(page, "Save").click()
    expect(page.get_by_text("Preferences saved.").first).to_be_visible()
    assert api("GET", "/api/me")["preferences"]["focus_goal_hours"] == 12
    page.get_by_role("radiogroup", name="Focus protection").get_by_role("radio", name="Auto").click()
    page.wait_for_timeout(800)
    assert api("GET", "/api/me")["preferences"]["autonomy"]["focus"] == "auto"
    expect(page.get_by_text("AI engine & activity log")).to_be_visible()
    shot(page, "settings")


def test_change_history_undo_after_the_toast_is_gone(page: Page) -> None:
    button(page, "Protect focus").click()
    button(page, "Apply changes").click()
    expect(page.get_by_text(re.compile(r"Protect .*h of focus .* applied\."))).to_be_visible()
    summary = api("GET", "/api/audit?limit=1")[0]["summary"]
    page.get_by_role("link", name="Settings").click()
    expect(page.get_by_text("Change history")).to_be_visible()
    page.get_by_role("button", name=f"Undo: {summary}", exact=True).click()
    expect(page.get_by_text(f"Undone: {summary}")).to_be_visible()
    assert api("GET", "/api/audit?limit=1")[0]["undone"] is True
    expect(page.get_by_role("button", name=f"Undo: {summary}", exact=True)).to_have_count(0)


def test_study_mode_records_task_and_metrics(page: Page) -> None:
    page.get_by_role("link", name="Study mode").click()
    page.get_by_placeholder("P01").fill("P99")
    button(page, "Start").first.click()
    page.wait_for_timeout(1200)
    button(page, "Stop").first.click()
    page.get_by_role("radiogroup", name="T1 ease rating").get_by_role("radio", name="6", exact=True).click()
    button(page, "Save").first.click()
    expect(page.get_by_text("T1 saved for P99.")).to_be_visible()
    metrics = api("GET", "/api/research/metrics")
    t1 = next(t for t in metrics["tasks"] if t["task_id"] == "T1")
    assert t1["n"] >= 1 and t1["mean_seq"] == 6
    shot(page, "study")
