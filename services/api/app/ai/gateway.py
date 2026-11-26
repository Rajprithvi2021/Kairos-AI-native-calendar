"""Claude gateway: the single choke point for LLM calls.

- Official Anthropic SDK, schema-constrained output via `client.beta.messages.parse(output_format=...)`.
- Default model `claude-opus-5-5`; effort "low" for parsing, "medium" for writing.
- Server-side refusal fallback enabled (beta `server-side-fallback-2026-07-01`, `fallbacks="default"`).
- Checks `stop_reason` (refusal / max_tokens) before trusting output.
- Typed error chain; any failure raises AIUnavailable/AIRefused so callers fall back to the
  deterministic twin. The caller logs every call (task, engine, latency, tokens, outcome - never content).
"""

from __future__ import annotations

import os
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailable(RuntimeError):
    pass


class AIRefused(RuntimeError):
    pass


class ClaudeGateway:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def available(self) -> bool:
        if self.settings.ai_mode == "offline":
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
