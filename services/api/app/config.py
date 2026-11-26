"""Runtime configuration (environment variables or services/api/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = API_DIR / ".data" / "kairos.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=API_DIR / ".env", env_prefix="KAIROS_", extra="ignore")

    database_url: str = f"sqlite:///{DEFAULT_DB.as_posix()}"
    # auto = Claude when credentials exist, else offline heuristics; offline = never call an LLM.
    ai_mode: Literal["auto", "offline", "claude"] = "auto"
    model: str = "claude-opus-5-5"
    ai_timeout_s: float = 25.0  # briefs and drafts (one retry)
    ai_parse_timeout_s: float = 8.0  # command parsing: no retry, fall back to the offline parse quickly
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    user_id: str = "maya"
    seed: int = 7
    # Optional frozen clock for demos/tests, e.g. "2026-11-30T16:00:00Z".
    now: str | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    google_client_secrets: str | None = None  # path to an OAuth client JSON (optional connector)


@lru_cache
def get_settings() -> Settings:
    return Settings()
