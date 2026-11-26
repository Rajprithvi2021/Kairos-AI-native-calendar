# ADR-0004: Proposals, audit and undo, with graded autonomy

- **Status:** Accepted
- **Date:** 2026-11-25
- **Related:** [04 §2.4 Write path](../04-technical-architecture.md#24-write-path-proposals-audit-and-undo) · [02 §4 Cross-cutting design](../02-ai-features.md#4-cross-cutting-design) · [03 §3](../03-prototype-and-flows.md#3-interaction-principles)

## Context

Trust is the bottleneck, and people delegate what they can correct ([01 §10](../01-user-research.md), insight I5). Calendar changes affect other people. The research plan needs acceptance and undo rates ([05 §7](../05-user-testing-plan.md)), and the north star counts AI decisions that are *kept* (07 §2).

Writes come from many places: booking, conflict fixes, focus protection, defrag, recurring-series changes, ICS import and manual edits. Without one discipline, some of them would be impossible to explain or reverse.

## Decision

1. **One write path.** `apply_operations` in [ops.py](../../services/api/app/services/ops.py) supports five operations: `create`; `update` (whitelisted fields only); `delete` (a soft cancel); `respond` (RSVP); `dismiss_conflict`. It validates that events end after they start, enforces optimistic concurrency through `expected_version` (HTTP 409), and writes one `AuditEntry` per call with before/after JSON snapshots and the actor (`user` or `ai`).
2. **Proposals first.** Multi-step or AI-initiated changes are persisted as a `Proposal` (`pending → applied | discarded | undone`) and shown as a list of changes before **Apply**. This covers focus protection, defrag, series changes, and focus blocks and cancellations from the command bar.
3. **Undo** replays the before-snapshots in reverse order. The UI offers it in a 12-second toast; the API (`POST /api/audit/{id}/undo`) keeps it available afterwards.
4. **Graded autonomy.** Each action type has a level in `Preferences.autonomy` (Suggest, Ask, Auto). Today only focus protection honours Auto: it is applied with actor `ai`, and the toast offers Undo. Anything that would notify or move other people stays manual.
5. **No automatic external sends.** Kairos produces drafts; a person sends them.

## Consequences

**Positive**
- Every calendar change is explainable and reversible. Tests cover booking then undo (the event is gone), resolving then undo (the conflict is back) and a rejected double undo.
- Research metrics come for free: acceptance, undo rate and average rank picked (`GET /api/research/metrics`).
- Autonomy can widen per action type without new plumbing.

**Negative**
- Undo does not check for edits made after the change. It also restores the old `version` and then increments it, which lands on the post-apply value: a later edit can be overwritten, and a stale client is not rejected. Fix: check the version on undo and keep versions strictly increasing.
- After the toast closes, undo stays one click away in Settings → *Change history*. Undo refuses (409) to overwrite a later change to the same event, and every undo issues a new event version, so stale clients are rejected.
- Not everything is audited. Reminder settings, preferences and feedback are written directly, and `POST /api/operations` accepts client-built operations, which are audited but not re-validated by the engines.
- Undo is local. In production it must write the reversal back to Google or Microsoft and correct what attendees were told.
- Snapshot JSON grows with event size; production needs an append-only audit store with retention rules.

## Alternatives considered

| Option | Why not (now) |
|---|---|
| Direct writes plus a change log | No preview step, so a weaker trust story |
| Full event sourcing for calendar state | Strong audit and as-of queries, but heavy for a prototype. The production `event_history` table ([04 §7.4](../04-technical-architecture.md#74-data-stores)) takes the useful half |
| Provider-native undo | Neither Google nor Microsoft offers an undo across several events |
| One global "AI on/off" switch | Too coarse: people may trust focus blocks long before auto-declines (assumption A4) |
