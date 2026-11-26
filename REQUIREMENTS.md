# What is required

## 1. To run the prototype

| Item | Version | Required? | Notes |
|---|---|---|---|
| Windows 11 / macOS / Linux | — | yes | Built and tested on Windows 11 |
| Python | 3.11+ (3.12 tested) | yes | `uv` installs packages into a project-local `.venv` |
| [uv](https://docs.astral.sh/uv/) | 0.5+ (0.13.5 tested) | yes | Python package and env manager |
| Node.js + npm | 22+ (26.13.1 LTS tested) | yes | For the Next.js web app |
| Git | any recent | yes | |
| A modern browser | Edge/Chrome/Firefox | yes | E2E tests drive the installed Edge |
| Disk | ~1 GB | yes | Dependencies (kept outside OneDrive automatically) |
| Anthropic API key | — | optional | Enables Claude; without it the offline twin runs everything |
| Gemini API key (Google AI Studio) | — | optional | Enables Gemini: Claude's fallback, or the main engine when there is no Claude key |
| Google Cloud project + OAuth client (Calendar API) | — | optional | Live Google Calendar sync (mapping is built and tested; OAuth flow needs your client) |
| Docker Desktop | — | optional | One-command run via `infra/docker-compose.yml` |

Packages installed by `scripts/setup.ps1` are listed in:
- `services/api/pyproject.toml` (+ `uv.lock`): FastAPI, SQLModel, Pydantic, anthropic, holidays, icalendar, tzdata; dev: pytest, hypothesis, ruff, playwright.
- `apps/web/package.json` (+ lock): Next.js 16, React 19, TanStack Query, Recharts, Tailwind CSS 4, lucide-react; dev: TypeScript, ESLint, Vitest.

## 2. Product requirements

### Functional
MoSCoW priority applies to the MVP; status is for this prototype.

| ID | Requirement | Feature | MoSCoW | Status |
|---|---|---|---|---|
| FR-01 | Show the user's week in **their** time zone with working hours, holidays, focus blocks and conflicts | Calendar | Must | ✅ |
| FR-02 | Find meeting times for N attendees across time zones that never violate working hours, existing commitments or protected focus | F1 | Must | ✅ (property-tested) |
| FR-03 | Rank options with an explanation (reasons, warnings, each attendee's local time) | F1 | Must | ✅ |
| FR-04 | When nothing fits, say what would have to give (shorter, wider window, stretch hours fairly, over focus) | F1 | Must | ✅ |
| FR-05 | Natural-language commands for schedule, reschedule, cancel, focus, conflicts, analytics, brief, remind, defrag | F6 | Must | ✅ (offline + Claude path) |
| FR-06 | Detect overlaps, impossible travel, focus intrusions, overloaded days, outside-hours meetings | F2 | Must | ✅ |
| FR-07 | Offer ranked, previewable resolutions that never create new conflicts | F2 | Must | ✅ (tested) |
| FR-08 | Every AI change is a proposal: preview → apply → one-click undo, audit-logged | All | Must | ✅ |
| FR-09 | Context-aware reminders: prep sized and placed in free time (before leaving for in-person), leave-now, follow-up, noise control, quiet hours | F3 | Must | ✅ |
| FR-10 | Meeting brief (purpose, context, agenda that fits, talking points, prep, watch-outs) | F3 | Should | ✅ (template; Claude when configured) |
| FR-11 | Analytics: allocation, cost, fragmentation, deep-work capacity, heatmap, collaborators, fairness | F4 | Should | ✅ |
| FR-12 | Forecast next weeks' meeting load with uncertainty and overload risk; publish backtest | F4 | Should | ✅ |
| FR-13 | Protect weekly focus goal; defragment flexible meetings | F5 | Should | ✅ |
| FR-14 | Recurring-meeting advisor with drafted messages | F7 | Should | ✅ |
| FR-15 | Learn ranking preferences from choices; user can inspect and reset | F8 | Could | ✅ (simple) |
| FR-16 | Autonomy dial per action type | All | Should | ✅ UI; Auto wired for focus protection |
| FR-17 | Privacy controls for what the AI sees | AI | Must | ✅ |
| FR-18 | Import ICS; sync Google Calendar / Microsoft 365 | Integrations | Must (prod) | ICS ✅ · Google mapping ✅, OAuth design · Graph design |
| FR-19 | In-product research instrumentation (feedback, telemetry, study tasks, CSV export) | Research | Should | ✅ |
| FR-20 | Task time-boxing, team load view, external scheduling agent | F9–F11 | Could | Designed |

### Non-functional
| ID | Requirement | Target (production) | Prototype |
|---|---|---|---|
| NFR-01 | Slot search latency | p95 < 300 ms (10 attendees × 2 weeks) | 2–42 ms measured (135–331 candidates); test bound < 500 ms for 9 attendees × 14 days |
| NFR-02 | NL command latency | < 2 s to interpretation | Offline < 5 ms; Claude not measured (no key), time-boxed at 8 s before the offline fallback |
| NFR-03 | Correctness of hard constraints | 0 violations | Hypothesis property test (40 random scenarios per run) |
| NFR-04 | Reversibility | 100% of AI changes undoable | All writes go through audited operations with undo |
| NFR-05 | Privacy | Minimum data to LLM; no content in logs | Pseudonymisation, title redaction, untrusted-text fencing, call log stores metadata only |
| NFR-06 | Availability / sync freshness | 99.9% · < 30 s via webhooks | Design (docs/04) |
| NFR-07 | Accessibility | WCAG 2.2 AA | Keyboard-first command bar, labelled controls, non-colour conflict cues; full audit pending |
| NFR-08 | Graceful degradation | Works when the LLM is down | Offline twin, automatic fallback (tested) |
| NFR-09 | Time correctness | DST, half-hour zones, regional holidays | Tested (US/GB/IN, DST transitions, IST) |

## 3. To take it to production

- **People:**
  - 1 PM and 1 product designer / UX researcher;
  - 3 full-stack engineers;
  - 2 ML/AI engineers;
  - 1 SRE/platform engineer;
  - part-time security and compliance.
- **Accounts and services:**
  - Google Cloud: Calendar API, plus OAuth app verification for the sensitive calendar scopes.
  - A Microsoft Entra app registration (Graph) and publisher verification.
  - An LLM provider: Anthropic API, or Claude on AWS Bedrock / Google Vertex AI for data residency.
  - A cloud host: GKE/EKS.
  - Postgres and Redis.
  - SSO/SCIM, e.g. WorkOS.
  - Observability: OpenTelemetry plus a backend.
  - Email and push providers.
  - Feature flags.
- **Compliance:**
  - SOC 2 Type II and GDPR/CCPA, with a DPA and sub-processor list.
  - Data retention and deletion.
  - A penetration test.
  - Google Workspace Marketplace review.
- **Plan:** dual-track agile, from internal alpha to private beta with design partners to GA.
