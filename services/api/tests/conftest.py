"""Test configuration: isolated temp database, frozen clock, offline AI. Runs identically on any date."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

FIXED_NOW = "2026-11-25T17:00:00Z"  # Wed 25 Nov 2026, 09:00 in San Francisco (day before US Thanksgiving)

_tmp = Path(tempfile.mkdtemp(prefix="kairos-test-"))
# KAIROS_TEST_DATABASE_URL runs the suite against Postgres (CI does); default is a throwaway SQLite file.
os.environ["KAIROS_DATABASE_URL"] = os.environ.get("KAIROS_TEST_DATABASE_URL") or f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["KAIROS_NOW"] = FIXED_NOW
os.environ["KAIROS_AI_MODE"] = "offline"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
os.environ["GEMINI_API_KEY"] = ""  # override any key in services/api/.env
os.environ["GOOGLE_API_KEY"] = ""

from app.clock import clock, parse_utc  # noqa: E402
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.domain.calendar_data import Ev, Snapshot  # noqa: E402
from app.seed.generator import World, build_world  # noqa: E402


@pytest.fixture(scope="session")
def now() -> datetime:
    return parse_utc(FIXED_NOW)


@pytest.fixture(scope="session")
def world(now: datetime) -> World:
    return build_world(now, 7)


def make_snapshot(world: World) -> Snapshot:
    return Snapshot(
        {p.id: p for p in world.people},
        {p.person_id: p for p in world.prefs},
        [Ev.from_row(e) for e in world.events],
        {s.id: s for s in world.series},
    )


@pytest.fixture()
def snap(world: World) -> Snapshot:
    return make_snapshot(world)


@pytest.fixture()
def client(now: datetime) -> Iterator:
    from fastapi.testclient import TestClient

    from app.api.deps import set_gateway
    from app.main import app

    set_gateway(None)
    clock.freeze(now)
    with TestClient(app) as c:
        assert c.post("/api/demo/reset").status_code == 200
        yield c
    clock.freeze(now)
