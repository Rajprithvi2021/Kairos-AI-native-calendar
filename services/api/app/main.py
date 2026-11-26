"""Kairos API entry point:  uv run uvicorn app.main:app --reload"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, func, select

from app import __version__
from app.api import routes_actions, routes_ai, routes_core
from app.clock import clock, parse_utc
from app.config import get_settings
from app.db import get_engine, init_db
from app.models import Person
from app.seed.generator import seed_database


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.now:
        clock.freeze(parse_utc(settings.now))
    init_db()
    with Session(get_engine()) as session:
        if session.exec(select(func.count()).select_from(Person)).one() == 0:
            seed_database(session, clock.now(), settings.seed)
    yield


app = FastAPI(
    title="Kairos API",
    version=__version__,
    description="AI-native calendar for business users. The LLM interprets; deterministic engines decide; every change is audited and undoable.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes_core.router)
app.include_router(routes_ai.router)
app.include_router(routes_actions.router)
