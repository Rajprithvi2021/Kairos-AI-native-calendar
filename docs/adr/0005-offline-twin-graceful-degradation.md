# ADR-0005: An offline twin for every LLM task, and graceful degradation

- **Status:** Accepted
- **Date:** 2026-11-25
- **Related:** [04 §5 AI layer](../04-technical-architecture.md#5-ai-layer) · [ADR-0001](0001-llm-interprets-solver-decides.md) · [ADR-0003](0003-schema-constrained-workflows-not-agents.md)

## Context

- There is no Anthropic API key on the build machine, and the demo has to run anywhere, for free.
- LLM calls fail in many ways: timeouts, rate limits, authentication errors, refusals, truncated output and schema-invalid output.
- Evaluating the LLM needs a baseline, and assumption A9 in [01 §11](../01-user-research.md) requires the heuristic fallback to reach at least 90% intent accuracy.

## Decision

- **Same schema, two engines.** Every LLM task has a deterministic twin that returns the same output schema:

| Task | Claude | Twin |
|---|---|---|
| Parse a command into `ParsedCommand` | `parse_command` in [assistant.py](../../services/api/app/services/assistant.py) | `heuristic.parse` ([heuristic.py](../../services/api/app/ai/heuristic.py)) |
| Write a `MeetingBrief` | `claude_brief` in [briefs.py](../../services/api/app/ai/briefs.py) | `template_brief` |
| Polish a `Draft` | `polish_draft` | The template text ([drafts.py](../../services/api/app/domain/drafts.py)) |

- **One choke point.** `ClaudeGateway` ([gateway.py](../../services/api/app/ai/gateway.py)) is the only module that calls an LLM. `KAIROS_AI_MODE` is `auto`, `offline` or `claude`. Failures raise `AIUnavailable` or `AIRefused`, and callers return the twin's answer together with a `fallback_reason`.
- **Refusals get a second chance first.** Requests carry the server-side fallback beta (`server-side-fallback-2026-07-01`, `fallbacks="default"`); only a final refusal reaches the twin.
- **The twin runs first.** The offline parse is computed before the Claude call, so falling back costs nothing extra, and `agrees_with_offline` gives a free shadow comparison.
- **Visible and logged.** Every call is logged without content. The UI always names the engine: the sidebar pill, the command-bar badge, the brief and draft badges, and the AI activity log in Settings.

## Consequences

**Positive**
- Every feature works with no key. All 64 backend tests and all 9 end-to-end tests run offline.
- The same golden set scores both engines on equal terms (`python -m evals.run_evals --claude`).
- Users always see which engine answered and, after a fallback, why.

**Negative**
- Two implementations per task to maintain. The regex grammar is narrow and was written alongside its golden set, so its 100% score overstates real accuracy.
- There is a quality cliff offline: template briefs and drafts are generic.
- The fallback is only partly latency-aware. The parse waits for Claude up to 8 s (no retry) before falling back, which is still above the 2 s NFR. Production should show the offline interpretation at once and upgrade it if Claude disagrees.
- In `auto` mode, availability is decided from keys in the environment or the config. Credentials that come from an SDK profile need `KAIROS_AI_MODE=claude`.

## Alternatives considered

| Option | Why not (now) |
|---|---|
| Fail closed (show an error when the LLM is down) | Breaks the product and the demo |
| Cache the last LLM answer | Helps only repeated questions; briefs are already cached per event |
| A small local model as the fallback | Heavier install and uneven quality; possible later |
| The SDK's client-side refusal middleware (`BetaRefusalFallbackMiddleware`) | Needed only where server-side fallbacks don't exist (Bedrock, Vertex AI, Foundry). If production moves there for data residency, this replaces the beta flag |
