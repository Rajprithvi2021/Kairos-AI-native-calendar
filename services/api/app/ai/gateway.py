"""LLM gateway: the single choke point for LLM calls. `build_gateway` chains Claude, then Gemini; every
caller keeps the deterministic offline twin as the last resort.

Claude:

- Official Anthropic SDK, schema-constrained output via `client.beta.messages.parse(output_format=...)`.
- Default model `claude-opus-5-5`; effort "low" for parsing, "medium" for writing.
- Server-side refusal fallback enabled (beta `server-side-fallback-2026-07-01`, `fallbacks="default"`).
- Checks `stop_reason` (refusal / max_tokens) before trusting output.
- Typed error chain; any failure raises AIUnavailable/AIRefused so callers fall back to the
  deterministic twin. The caller logs every call (task, engine, latency, tokens, outcome - never content).

Gemini (fallback, or primary when there is no Claude key):
- Gemini Developer API over REST (stdlib only); the key travels in the `x-goog-api-key` header, never the URL.
- JSON output constrained by the same Pydantic schemas (`responseJsonSchema`), validated again on receipt.
- A fast model for parsing; a stronger one for briefs and drafts, falling back to the fast one when busy.
- Safety blocks map to AIRefused; overload, truncation, bad output and network errors to AIUnavailable.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailable(RuntimeError):
    pass


class AIRefused(RuntimeError):
    pass


class LLM(Protocol):
    """What callers rely on; ClaudeGateway, GeminiGateway and the AIGateway chain all provide it."""

    name: str
    settings: Settings

    @property
    def available(self) -> bool: ...

    @property
    def model(self) -> str | None: ...

    def status(self) -> dict[str, Any]: ...

    def structured(self, *, system: str, prompt: str, schema: type[T], effort: str = "low", max_tokens: int = 4000,
                   timeout_s: float | None = None, max_retries: int | None = None) -> tuple[T, dict[str, Any]]: ...


LABELS = {"claude": "Claude", "gemini": "Gemini", "offline": "Offline"}


class ClaudeGateway:
    name = "claude"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def model(self) -> str:
        return self.settings.model

    @property
    def available(self) -> bool:
        if self.settings.ai_mode in ("offline", "gemini"):
            return False
        if self._client is not None or self.settings.ai_mode == "claude":
            return True
        return bool(
            self.settings.anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    def status(self) -> dict[str, Any]:
        if self.settings.ai_mode == "offline":
            reason = "AI mode set to offline"
        elif self.available:
            reason = "Claude credentials found"
        else:
            reason = "No Anthropic credentials - using the offline heuristic engine"
        return {
            "engine": "claude" if self.available else "offline",
            "model": self.settings.model if self.available else None,
            "mode": self.settings.ai_mode,
            "reason": reason,
        }

    def client(self) -> Any:
        if self._client is None:
            import anthropic

            key = self.settings.anthropic_api_key.get_secret_value() if self.settings.anthropic_api_key else None
            kwargs: dict[str, Any] = {"timeout": self.settings.ai_timeout_s, "max_retries": 1}
            self._client = anthropic.Anthropic(api_key=key, **kwargs) if key else anthropic.Anthropic(**kwargs)
        return self._client

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[T],
        effort: str = "low",
        max_tokens: int = 4000,
        timeout_s: float | None = None,
        max_retries: int | None = None,
    ) -> tuple[T, dict[str, Any]]:
        if not self.available:
            raise AIUnavailable("Claude is not configured")
        import anthropic

        client = self.client()
        if timeout_s is not None or max_retries is not None:  # per-call budget, e.g. a tight one for parsing
            opts: dict[str, Any] = {}
            if timeout_s is not None:
                opts["timeout"] = timeout_s
            if max_retries is not None:
                opts["max_retries"] = max_retries
            client = client.with_options(**opts)
        t0 = time.perf_counter()
        try:
            resp = client.beta.messages.parse(
                model=self.settings.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise AIUnavailable("authentication failed - check ANTHROPIC_API_KEY") from e
        except anthropic.RateLimitError as e:
            raise AIUnavailable("rate limited") from e
        except anthropic.BadRequestError as e:
            raise AIUnavailable(f"bad request: {getattr(e, 'message', e)}") from e
        except anthropic.APIStatusError as e:
            raise AIUnavailable(f"API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:  # includes timeouts
            raise AIUnavailable("network error or timeout") from e
        except ValidationError as e:
            raise AIUnavailable("model output failed schema validation") from e
        latency = round((time.perf_counter() - t0) * 1000, 1)
        usage = getattr(resp, "usage", None)
        meta = {
            "engine": "claude",
            "model": getattr(resp, "model", self.settings.model),
            "latency_ms": latency,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "request_id": getattr(resp, "_request_id", None),
        }
        if resp.stop_reason == "refusal":
            raise AIRefused("Claude declined this request")
        if resp.stop_reason == "max_tokens":
            raise AIUnavailable("response truncated (max_tokens)")
        parsed = getattr(resp, "parsed_output", None)
        if parsed is None:
            raise AIUnavailable("no structured output returned")
        return parsed, meta


# --- Gemini ---------------------------------------------------------------------------------------------
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_REFUSAL_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

Transport = Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, Any]]


class _Busy(AIUnavailable):
    """Overloaded or rate-limited: worth one try on the lighter model."""


def _urllib_transport(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> tuple[int, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": {"message": raw.decode(errors="replace")[:300]}}


class GeminiGateway:
    name = "gemini"

    def __init__(self, settings: Settings, transport: Transport | None = None) -> None:
        self.settings = settings
        self._transport = transport or _urllib_transport

    def _key(self) -> str:
        return self.settings.gemini_api_key.get_secret_value().strip() if self.settings.gemini_api_key else ""

    @property
    def model(self) -> str:
        return self.settings.gemini_model

    @property
    def available(self) -> bool:
        return self.settings.ai_mode != "offline" and bool(self._key())

    def status(self) -> dict[str, Any]:
        return {"engine": "gemini" if self.available else "offline", "model": self.model if self.available else None,
                "mode": self.settings.ai_mode, "reason": "Gemini API key found" if self.available else "No Gemini API key"}

    def structured(self, *, system: str, prompt: str, schema: type[T], effort: str = "low", max_tokens: int = 4000,
                   timeout_s: float | None = None, max_retries: int | None = None) -> tuple[T, dict[str, Any]]:
        if not self.available:
            raise AIUnavailable("Gemini is not configured")
        deadline = time.monotonic() + (timeout_s if timeout_s is not None else self.settings.ai_timeout_s)
        first = self.settings.gemini_fast_model if effort == "low" else self.settings.gemini_model
        models = [first] if max_retries == 0 or first == self.settings.gemini_fast_model else [first, self.settings.gemini_fast_model]
        last: AIUnavailable | None = None
        for i, model in enumerate(models):
            remaining = deadline - time.monotonic()
            if remaining < 1:
                break
            # Leave time for the lighter model if this one is slow: the first of two attempts gets 60% of the budget.
            attempt = remaining * 0.6 if i < len(models) - 1 else remaining
            try:
                return self._call(model, system, prompt, schema, max_tokens, attempt, thinking=effort != "low" and "lite" not in model)
            except _Busy as e:
                last = e
        raise AIUnavailable(str(last) if last else "timed out")

    def _call(self, model: str, system: str, prompt: str, schema: type[T], max_tokens: int, timeout: float,
              thinking: bool) -> tuple[T, dict[str, Any]]:
        config: dict[str, Any] = {"responseMimeType": "application/json", "responseJsonSchema": schema.model_json_schema(),
                                  "maxOutputTokens": max_tokens}
        if thinking:
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
        headers = {"x-goog-api-key": self._key(), "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            status, data = self._transport(GEMINI_URL.format(model=model), headers, body, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:  # includes socket timeouts
            raise _Busy(f"{model}: network error or timeout") from e
        latency = round((time.perf_counter() - t0) * 1000, 1)
        if status != 200:
            message = ((data or {}).get("error") or {}).get("message", "") if isinstance(data, dict) else ""
            if status in (401, 403):
                raise AIUnavailable("authentication failed - check GEMINI_API_KEY")
            if status in _RETRYABLE_STATUS:
                raise _Busy(f"{model} busy (HTTP {status})")
            if status == 404:
                raise AIUnavailable(f"model {model} not available to this key")
            raise AIUnavailable(f"bad request: {message[:160]}" if status == 400 else f"API error {status}")
        blocked = ((data or {}).get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise AIRefused(f"Gemini blocked the request ({blocked})")
        candidates = (data or {}).get("candidates") or []
        if not candidates:
            raise AIUnavailable("no structured output returned")
        finish = candidates[0].get("finishReason", "STOP")
        if finish in _REFUSAL_FINISH:
            raise AIRefused(f"Gemini declined this request ({finish})")
        if finish == "MAX_TOKENS":
            raise AIUnavailable("response truncated (max_tokens)")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise AIUnavailable("no structured output returned")
        try:
            parsed = schema.model_validate_json(text)
        except ValidationError as e:
            raise AIUnavailable("model output failed schema validation") from e
        usage = data.get("usageMetadata") or {}
        out_tokens = (usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0)
        return parsed, {"engine": "gemini", "model": data.get("modelVersion") or model, "latency_ms": latency,
                        "input_tokens": usage.get("promptTokenCount"), "output_tokens": out_tokens or None,
                        "request_id": data.get("responseId")}


# --- chain ------------------------------------------------------------------------------------------------
class AIGateway:
    """Tries each configured LLM in order; a refusal stops the chain (it is a decision, not an outage)."""

    def __init__(self, settings: Settings, engines: list[Any]) -> None:
        self.settings = settings
        self.engines = engines
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _within_budget(self) -> bool:
        """Rolling-hour cap on LLM calls (KAIROS_AI_MAX_CALLS_PER_HOUR); 0 means unlimited."""
        limit = self.settings.ai_max_calls_per_hour
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] >= 3600:
                self._calls.popleft()
            if len(self._calls) >= limit:
                return False
            self._calls.append(now)
            return True

    def _live(self) -> list[Any]:
        return [e for e in self.engines if e.available]

    @property
    def available(self) -> bool:
        return bool(self._live())

    @property
    def name(self) -> str:
        live = self._live()
        return live[0].name if live else "offline"

    @property
    def model(self) -> str | None:
        live = self._live()
        return live[0].model if live else None

    def status(self) -> dict[str, Any]:
        live = self._live()
        if self.settings.ai_mode == "offline":
            reason = "AI mode set to offline"
        elif not live:
            reason = "No Claude or Gemini credentials - using the offline heuristic engine"
        else:
            then = [LABELS[e.name] for e in live[1:]] + ["the offline engine"]
            reason = f"{LABELS[live[0].name]} credentials found; falls back to {', then '.join(then)}"
        return {"engine": self.name, "model": self.model, "mode": self.settings.ai_mode, "reason": reason,
                "fallbacks": [e.name for e in live[1:]]}

    def structured(self, *, timeout_s: float | None = None, **kwargs: Any) -> tuple[Any, dict[str, Any]]:
        if self._live() and not self._within_budget():
            raise AIUnavailable(f"hourly AI call limit ({self.settings.ai_max_calls_per_hour}) reached")
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        errors: list[str] = []
        for engine in self._live():
            budget = None if deadline is None else deadline - time.monotonic()
            if budget is not None and budget < 1:
                errors.append(f"{LABELS[engine.name]}: no time left")
                break
            try:
                parsed, meta = engine.structured(timeout_s=budget, **kwargs)
            except AIUnavailable as e:
                errors.append(f"{LABELS[engine.name]}: {e}")
                continue
            if errors:
                meta["fallback_from"] = "; ".join(errors)
            return parsed, meta
        raise AIUnavailable("; ".join(errors) or "no AI engine configured")


def build_gateway(settings: Settings) -> AIGateway:
    engines: list[Any] = [] if settings.ai_mode == "gemini" else [ClaudeGateway(settings)]
    return AIGateway(settings, [*engines, GeminiGateway(settings)])
