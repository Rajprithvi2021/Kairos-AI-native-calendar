"""Database engine and session management: SQLite locally, Postgres (e.g. Neon) when deployed."""

from __future__ import annotations

import ssl
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import URL, Engine, make_url
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def postgres_url(url: str) -> tuple[URL, dict[str, Any]]:
    """Accept any Postgres URL (postgres://, postgresql://, postgresql+driver://, e.g. Neon's) and use pg8000.

    pg8000 is pure Python, so it runs anywhere (including machines that block compiled drivers). It takes TLS
    as an SSLContext rather than libpq's `sslmode`/`channel_binding` parameters, which are translated here:
    TLS with certificate verification unless `sslmode=disable` (local or CI databases).
    """
    u = make_url(url)
    query = dict(u.query)
    sslmode = query.pop("sslmode", "require")
    query.pop("channel_binding", None)
    connect_args: dict[str, Any] = {} if sslmode == "disable" else {"ssl_context": ssl.create_default_context()}
    return u.set(drivername="postgresql+pg8000", query=query), connect_args


def _make_engine(url: str) -> Engine:
    if url.startswith("postgres"):
        pg_url, pg_args = postgres_url(url)
        # Serverless Postgres closes idle connections: check before use and recycle well inside its timeout.
        return create_engine(pg_url, connect_args=pg_args, pool_pre_ping=True, pool_recycle=240, pool_size=5, max_overflow=5)
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (used by tests after changing settings)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(get_engine())


def drop_all() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.drop_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
