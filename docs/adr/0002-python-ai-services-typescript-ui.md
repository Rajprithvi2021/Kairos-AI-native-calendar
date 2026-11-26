# ADR-0002: Python for the AI services, TypeScript for the UI

- **Status:** Accepted
- **Date:** 2026-11-25
- **Related:** [04 §2 Prototype architecture](../04-technical-architecture.md#2-prototype-architecture) · [04 §8 Tech stack](../04-technical-architecture.md#8-tech-stack) · [ADR-0006](0006-windows-onedrive-and-app-control.md)

## Context

The backend needs, today or soon:
- the official Anthropic SDK with Pydantic structured outputs;
- an optimisation library (OR-Tools CP-SAT is planned for team-scale problems);
- time-zone and holiday data (`zoneinfo` with `tzdata`, `holidays`) and iCalendar parsing (`icalendar`, `dateutil`);
- property-based testing (Hypothesis) and statistics.

The UI is a highly interactive calendar: a week grid in the user's zone, drawers, ghost previews, a keyboard-first command bar and charts. It needs a mainstream, typed web stack with good accessibility tooling. The team in [07 §8](../07-agile-roadmap.md) is full-stack engineers plus ML/AI engineers.

## Decision

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLModel (SQLAlchemy) on SQLite for the prototype, with uv for environments ([services/api](../../services/api/)).
- **Frontend:** Next.js 16 (App Router) with React 19 client components, TypeScript, TanStack Query, Tailwind CSS 4 and Recharts ([apps/web](../../apps/web/)).
- **One origin.** The browser calls only the Next.js origin, and [next.config.ts](../../apps/web/next.config.ts) rewrites `/api/*` to FastAPI, so normal use needs no CORS.
- **The contract** is FastAPI's OpenAPI document (`/docs`), mirrored by the hand-written types in [types.ts](../../apps/web/src/lib/types.ts).
- **One schema per AI task.** Pydantic models double as the LLM output schema and the API model (`ParsedCommand`, `MeetingBrief`, `Draft` in [schemas.py](../../services/api/app/ai/schemas.py)), so Claude, the offline twin and the API share one type.

## Consequences

**Positive**
- Each side gets its best ecosystem, and the AI and optimisation code sits next to its tests.
- One schema serves Claude, the deterministic twin and the HTTP API.
- The same ORM can point at Postgres through `KAIROS_DATABASE_URL`. The schema still needs normalising for production ([04 §7.4](../04-technical-architecture.md#74-data-stores)).

**Negative**
- Two toolchains (uv and npm), two test runners and two linters; CI runs two jobs.
- The API contract can drift. The plan called for TypeScript types generated from OpenAPI, but the prototype writes them by hand. Next step: generate them in CI.
- The Windows build machine needed workarounds for both toolchains ([ADR-0006](0006-windows-onedrive-and-app-control.md)).

## Alternatives considered

| Option | Why not (now) |
|---|---|
| All TypeScript (Node API with the TypeScript Anthropic SDK) | Viable for the LLM calls, but the optimisation, time-zone, holiday and statistics ecosystems are weaker |
| A Python UI framework (Streamlit, Dash) | Can't deliver calendar-grade interaction, keyboard flows or accessibility |
| A separate single-page app calling FastAPI directly | Works, but needs CORS and gives up Next.js routing and build tooling; the rewrite keeps one origin |
| gRPC between UI and API | Unnecessary for a browser client; kept as an option between production services |
