# 06 · Final presentation

**Deck (17 slides, 16:9):** https://claude.ai/artifact/7PG4m1ztCyrgmNFV3v8wrY
- It's a private claude.ai artifact. Share it from the page's Share menu.
- It exports to PowerPoint or PDF from Share › Export.
- The source and speaker notes below are the same content, kept in the repo.

Narrative arc: why → what → how → proof → next. Each claim ends with its evidence, either sourced (docs/01) or measured on the prototype.

| # | Slide | Message | Speaker notes (short) |
|---|---|---|---|
| 1 | **Kairos**: an AI-native calendar for business users | *The LLM interprets. Deterministic engines decide. You stay in control.* | Kairos = "the opportune moment". Everything shown runs in a working prototype. |
| 2 | Calendars record time. Business users need help spending it. | Interruptions every 2 min in core hours (heaviest 20% of users); 50% of meetings in peak-focus windows; 78% say the meeting load makes work hard; >70% of senior managers call meetings unproductive. | Sources: Microsoft WTI 2025, Atlassian (5,000 workers), HBR 2017 via MIT SMR. We do *not* quote "emails per meeting": no rigorous source exists, so we will measure it. |
| 3 | Five proto-personas, eight recurring pains | Maya (VP CS), Sam (EA), Dev (eng manager), Priya (Bangalore IC), Leo (AE). Pains P1–P8. | Proto-personas are validated in the diary study. Every feature traces back to P1–P8 (docs/02). |
| 4 | Eight table stakes before AI matters | Sync, group scheduling, time zones, conferencing and rooms, delegation, reminders, recurrence, admin and security. | Kano hygiene factors: required to compete, never a reason to switch. |
| 5 | AI that earns trust | The LLM interprets and the solver decides · proposals, never surprises · explain every choice · private by design, works offline. | Trust is earned in small, reversible steps. |
| 6 | F1 Intelligent scheduling | Hard constraints, property-tested · max-min fairness across zones · a relaxation ladder (fair stretch: 6:00 AM PT / 7:30 PM IST / 9:00 AM ET) · learns from picks. | 135–331 candidate times in 2–42 ms. |
| 7 | F2 Conflict resolution | Five conflict types · fixes ranked by value kept − disruption · never creates new conflicts · preview, apply, undo. | QBR (priority 100) kept; internal review (68) moved an hour earlier; 2 people affected. |
| 8 | F3 Smart reminders and briefs | Prep sized to importance in a real gap · leave by 8:55 · routine meetings silent · a brief before you walk in. | Live testing caught "prep after departure"; fixed, and now guarded by a test. |
| 9 | F4 Predictive time analytics | Booking-pickup ensemble with a conformal band · model card · cost and fragmentation · fairness report and fixes (F7). | Synthetic backtest: MAE about 1.1 h, competitive with the best naive baseline; coverage 67% vs 80% target over 9 weeks. Shown as-is. |
| 10 | One command bar, four more features | F6 Ctrl+K · F5 focus guardian and defrag · F7 necessity advisor · F8 learning. Designed: F9 time-boxing, F10 team view, F11 external agent. | F11 is the only autonomous agent in the plan, and the right place for one. |
| 11 | Architecture | UI → FastAPI → parser (Claude ⇄ offline twin) + decision engines + proposals → audit → undo → data. Production: push-sync, event bus, Postgres + pgvector, Kubernetes, SOC 2. | The UI never talks to the model; one audited write path makes undo universal. |
| 12 | Tech stack | Prototype vs production per layer. | Same seams, swapped implementations. |
| 13 | Quality and safety | 70 backend tests · 0 hard-constraint violations (property test) · 10/10 end-to-end flows · 51 golden commands. | Not yet verified: live Claude, Google OAuth, Docker, CI. Held-out user commands are the real eval. |
| 14 | User testing | Concept → Wizard-of-Oz → moderated + RITE → unmoderated → diary study → beta A/B. Study mode built in. | Over-reliance probe: plant a worse suggestion, then debrief. We aim for calibrated trust. |
| 15 | Roadmap | Sprint 0 Dec 2026 → internal alpha Feb 2027 → private beta Mar 2027 → public beta May 2027 → GA Nov 2027. North star: AI decisions kept per weekly active user. | Feature flags and eval gates on every AI change (docs/07). |
| 16 | From a record of time to a partner in spending it | Before/after: ping-pong → one sentence; surprise double-bookings → flagged early; pop-ups → reminders that matter; hindsight → a forecast; unfair calls → fairness; black box → proposals with undo. | The fundamental shift for business users. |
| 17 | Prototype to pilot | Turn Claude on and measure it · 3–5 design partners · platform approvals · trust and compliance track. | Kairos: the right moment, every time. |

## Live demo (optional, 5 minutes)
Follow the "5-minute demo" in the [README](../README.md). Start the app first with `scripts\dev.ps1`.
