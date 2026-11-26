"""Shared FastAPI dependencies and error mapping."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from datetime import datetime
from functools import wraps
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from app.ai.gateway import LLM, build_gateway
from app.clock import clock
from app.config import get_settings
from app.db import get_engine
from app.services.ops import VersionConflict

_gateway: LLM | None = None


def session_dep() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def now_dep() -> datetime:
    return clock.now()


def gateway_dep() -> LLM:
    global _gateway
    if _gateway is None:
        _gateway = build_gateway(get_settings())
    return _gateway


def set_gateway(gw: LLM | None) -> None:
    """Test hook: inject a gateway (e.g. one wrapping a fake Anthropic client)."""
    global _gateway
    _gateway = gw


def _translate(e: Exception) -> HTTPException:
    if isinstance(e, VersionConflict):
        return HTTPException(409, str(e))
    if isinstance(e, ValueError):  # OpError, unparseable or offset-less timestamps
        return HTTPException(400, str(e))
    return HTTPException(404, f"not found: {e}")


def http_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Map domain errors to HTTP status codes (works for sync and async route handlers)."""
    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except (ValueError, KeyError) as e:
                raise _translate(e) from e

        return awrapper

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError) as e:
            raise _translate(e) from e

    return wrapper
