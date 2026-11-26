# Architecture decision records

Short records in the MADR style: **Context · Decision · Consequences · Alternatives considered**. There is one decision per file, numbered in order, and a record is never rewritten. When a decision changes, a new ADR supersedes the old one and both stay in the index. The architecture these decisions shape is described in [04 · Technical architecture](../04-technical-architecture.md).

| ADR | Title | Status | Date | The decision in one line |
|---|---|---|---|---|
| [0001](0001-llm-interprets-solver-decides.md) | The LLM interprets, the solver decides | Accepted | 2026-11-25 | Claude parses language and writes briefs and drafts; deterministic engines choose every time and compute every number |
| [0002](0002-python-ai-services-typescript-ui.md) | Python for the AI services, TypeScript for the UI | Accepted | 2026-11-25 | FastAPI and Pydantic behind a Next.js, React and TypeScript front end, on one origin through an `/api` rewrite |
| [0003](0003-schema-constrained-workflows-not-agents.md) | Schema-constrained workflows, not agents | Accepted | 2026-11-25 | One structured-output call per task inside code-controlled flow; agent loops only for F11 |
| [0004](0004-proposals-audit-undo-autonomy.md) | Proposals, audit and undo, with graded autonomy | Accepted | 2026-11-25 | One audited write path with one-click undo; proposals before multi-step AI changes; Auto only where it is wired |
| [0005](0005-offline-twin-graceful-degradation.md) | An offline twin for every LLM task, and graceful degradation | Accepted | 2026-11-25 | Each LLM task has a deterministic twin with the same schema; typed failures fall back to it |
| [0006](0006-windows-onedrive-and-app-control.md) | Building on Windows with OneDrive and Application Control | Accepted | 2026-11-25 | A pure-Python SQLAlchemy shim, `python -m` launchers, dependency folders outside OneDrive, and webpack |

## Planned

The Sprint 0 spikes in 07 §7 each close with an ADR:
- Google push notifications and incremental sync.
- Microsoft Graph delta queries and webhooks.
- OR-Tools CP-SAT against the current engine at team scale.
- The eval harness in CI, for both engines.
- A threat model for prompt injection and data minimisation.

## Template

````markdown
# ADR-NNNN: Title

- **Status:** Proposed | Accepted | Superseded by ADR-XXXX
- **Date:** YYYY-MM-DD
- **Related:** links to docs, code and other ADRs

## Context
The forces at play, with evidence and constraints.

## Decision
What we will do, stated so it can be checked in the code.

## Consequences
**Positive** … **Negative** …

## Alternatives considered
| Option | Why not (now) |
|---|---|
````
