# ADR-0003: Schema-constrained workflows, not agents

- **Status:** Accepted
- **Date:** 2026-11-25
- **Related:** [04 §5 AI layer](../04-technical-architecture.md#5-ai-layer) · [02 F11](../02-ai-features.md#f11--external-scheduling-agent-design-only-v2) · [ADR-0001](0001-llm-interprets-solver-decides.md) · [ADR-0005](0005-offline-twin-graceful-degradation.md)

## Context

The v1 LLM jobs are bounded: one sentence becomes one intent, one set of facts becomes one brief, one draft becomes a polished draft. An agent, meaning a model that chooses its own tool calls over several turns, buys flexibility at the cost of predictability, auditability, latency and spend. Calendar changes affect other people, so those costs matter here.

On `claude-opus-5-5`, forced tool choice (`tool_choice` of type `any` or `tool`) is rejected. "Force a tool call to get JSON" is therefore not an option. Structured outputs, `output_format` through `messages.parse`, constrain the response to a schema instead.

## Decision

- **One call per task.** Every LLM use is a single `client.beta.messages.parse` call with a Pydantic output schema, made from code-controlled flow by `ClaudeGateway.structured` ([gateway.py](../../services/api/app/ai/gateway.py)):

| Task | Schema | Effort |
|---|---|---|
| `parse_intent` | `ParsedCommand` | low |
| `brief` | `MeetingBrief` | medium |
| `draft` | `Draft` | low |

- **No tools, no multi-turn state, no autonomous actions.** Code decides what happens next: resolving people and events, choosing the engine, creating a proposal, and waiting for the user to confirm.
- **Check before trusting.** `stop_reason` is checked before any output is used. A refusal, truncation or schema-invalid output is a failure, and the offline twin answers instead ([ADR-0005](0005-offline-twin-graceful-degradation.md)).
- **Agents are reserved for F11,** the external scheduling agent (v2), and only after Wizard-of-Oz validation, with draft-only sends and narrow tools.

## Consequences

**Positive**
- The control flow is predictable: one call per task, with bounded cost and latency.
- Evaluation is simple: field-level accuracy on a golden set (51 cases; the offline parser scores 100%; Claude has not been evaluated yet).
- The injection surface is small. Model output cannot act; it can only fill a schema whose effect is previewed before anything changes.

**Negative**
- Multi-step requests ("find a time, then move the clash") take two commands.
- Clarification is rule-based ("Who should attend?") rather than conversational.
- The schema grows with the product; each new action needs parser, engine and eval changes.

## Alternatives considered

| Option | Why not (now) |
|---|---|
| A tool-using agent with calendar tools | Less predictable, harder to audit and evaluate, slower; reserved for F11 |
| Free-text JSON prompting without a schema | Parse failures and silent field drift |
| A forced tool call to obtain JSON | Rejected by `claude-opus-5-5`; structured outputs are the supported route |
| A fine-tuned intent classifier | Needs labelled data we don't have yet; the golden set and Study-mode failures can seed it later |
