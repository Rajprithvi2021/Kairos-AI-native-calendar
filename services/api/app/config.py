"""Runtime configuration (environment variables or services/api/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = API_DIR / ".data" / "kairos.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=API_DIR / ".env", env_prefix="KAIROS_", extra="ignore")

    database_url: str = f"sqlite:///{DEFAULT_DB.as_posix()}"
    # auto = Claude, then Gemini, for whichever has credentials; offline heuristics as the last resort.
    # offline = never call an LLM; claude = always try Claude (Gemini as fallback); gemini = Gemini only.
    ai_mode: Literal["auto", "offline", "claude", "gemini"] = "auto"
    model: str = "claude-opus-5-5"
    ai_timeout_s: float = 25.0  # briefs and drafts (one retry)
    ai_parse_timeout_s: float = 8.0  # command parsing: no retry, fall back to the offline parse quickly
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    # Google Gemini (Gemini Developer API): used when there is no Claude key, and as Claude's fallback.
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    # Measured 26 Nov 2026: a brief took ~9 s on 3.5-flash-lite, while 3.5-flash hung past 45 s under load.
    gemini_model: str = "gemini-3.5-flash-lite"  # briefs and drafts
    gemini_fast_model: str = "gemini-3.1-flash-lite"  # command parsing, and the fallback when the main model is busy
    user_id: str = "maya"
    seed: int = 7
    # Optional frozen clock for demos/tests, e.g. "2026-11-30T16:00:00Z".
    now: str | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    google_client_secrets: str | None = None  # path to an OAuth client JSON (optional connector)


@lru_cache
def get_settings() -> Settings:
    return Settings()
