"""E2E fixtures: drives the locally installed Microsoft Edge (no browser download) with Playwright.

Prerequisites: API on :8000 and web app on :3000 (scripts/dev.ps1 or scripts/test.ps1 -E2E).
Run:  cd services/api; uv run python -m pytest ../../tests/e2e
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

# A freshly started dev server compiles each route on first visit; allow for it.
expect.set_options(timeout=15_000)

BASE = os.environ.get("KAIROS_WEB_URL", "http://localhost:3000")
API = os.environ.get("KAIROS_API_URL", "http://127.0.0.1:8000")
SHOTS = Path(__file__).resolve().parents[2] / "docs" / "screenshots"


def api(method: str, path: str, body: dict | None = None) -> object:
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body or {}).encode() if method != "GET" else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    channel = os.environ.get("KAIROS_E2E_CHANNEL", "msedge")
    with sync_playwright() as p:
        b = p.chromium.launch(channel=channel, headless=os.environ.get("KAIROS_E2E_HEADED") != "1")
        yield b
        b.close()


@pytest.fixture(scope="session", autouse=True)
def warm_up(browser: Browser) -> None:
    """Compile every route once, so a fresh dev server doesn't hot-reload pages mid-test."""
    ctx = browser.new_context()
    pg = ctx.new_page()
    for path in ("/", "/insights", "/settings", "/study"):
        pg.goto(BASE + path, wait_until="networkidle", timeout=120_000)
    ctx.close()


@pytest.fixture()
def page(browser: Browser) -> Iterator[Page]:
    api("POST", "/api/demo/reset")  # every test starts from the same demo world
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, timezone_id="Asia/Kolkata", reduced_motion="reduce")
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE)
    pg.get_by_text("Copilot", exact=True).wait_for(timeout=60_000)
    yield pg
    ctx.close()
    assert not errors, f"uncaught page errors: {errors}"


def shot(page: Page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / f"{name}.png"))
