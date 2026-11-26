// API contract types (mirror the FastAPI responses; OpenAPI docs at http://127.0.0.1:8000/docs).

export type Person = {
  id: string; name: string; first_name: string; email: string; title: string; team: string; company: string;
  timezone: string; country: string; city: string; work_start: string; work_end: string; work_days: number[];
  is_external: boolean; color: string; seniority: number; hourly_rate: number; manager_id: string | null;
};

export type Attendee = {
  person_id: string; name: string; title: string; company: string; timezone: string; is_external: boolean;
  response: string; optional: boolean; organizer: boolean;
};

export type PriorityFactor = { label: string; points: number };

export type CalEvent = {
  id: string; title: string; description: string; start: string; end: string; organizer_id: string;
  attendees: Attendee[]; kind: "meeting" | "focus" | "prep" | "personal"; category: string; category_label: string;
  color: string; location: string | null; is_virtual: boolean; is_movable: boolean; series_id: string | null;
  status: string; source: string; ai_generated: boolean; version: number; my_response: string | null;
  optional_for_me: boolean; priority: number; priority_factors: PriorityFactor[]; flags: string[];
};

export type EventDetail = CalEvent & {
  cost: number; necessity_tip: string | null;
  series: { title: string; cadence: string; duration_min: number; avg_actual_min: number | null } | null;
};

export type Holiday = { date: string; name: string; country: string };
export type EventsResponse = { events: CalEvent[]; holidays: Holiday[]; timezone: string };

export type AttendeeLocal = {
  person_id: string; name: string; timezone: string; tz_abbr: string; local_label: string;
  comfort: number; status: "core" | "edge" | "outside"; optional: boolean; available: boolean;
};

export type Slot = {
  start: string; end: string; score: number; components: Record<string, number>; reasons: string[];
  warnings: string[]; attendees: AttendeeLocal[]; label: string; rank: number;
};

export type Relaxation = { kind: string; label: string; description: string; patch: Record<string, unknown>; slot_count: number; preview: string };

export type SlotRequest = {
  organizer_id: string; attendee_ids: string[]; duration_min: number; window_start: string | null; window_end: string | null;
  optional_ids: string[]; preferred_period: string; earliest_local: string | null; latest_local: string | null;
  respect_focus: boolean; exclude_event_id: string | null; stretch_hours_min: number;
};

export type SlotResult = { slots: Slot[]; relaxations: Relaxation[]; stats: { candidates: number; feasible: number; elapsed_ms: number }; request: SlotRequest };

export type Operation = Record<string, unknown> & { op: string };

export type ConflictOption = {
  id: string; kind: string; label: string; description: string; operations: Operation[]; people_affected: number;
  score: number; reasons: string[]; draft: { subject: string; body: string } | null;
  preview: { event_id: string; start: string; end: string } | null;
};

export type Conflict = {
  id: string; type: "overlap" | "travel" | "focus" | "overload" | "outside_hours"; severity: "high" | "medium" | "low";
  title: string; description: string; event_ids: string[]; day: string; starts_at: string; options: ConflictOption[];
};

export type Reminder = {
  id: string; event_id: string; event_title: string; kind: string; fire_at: string; title: string; rationale: string;
  enabled: boolean; suppressed: boolean; channel: string; due?: boolean;
  action: { type: string; label: string; operations?: Operation[]; kind?: string; draft?: { subject: string; body: string } } | null;
};

export type Brief = {
  purpose: string; context: string[]; agenda: { item: string; minutes: number }[]; talking_points: string[];
  prep_checklist: string[]; watch_outs: string[];
};

export type CardAction = {
  type: "open_conflict" | "focus_plan" | "defrag" | "series_action" | "navigate" | "operations" | "open_event";
  label: string; conflict_id?: string; week_start?: string; series_id?: string; to?: string; operations?: Operation[];
  summary?: string; event_id?: string;
};

export type InsightCard = {
  id: string; kind: string; section: "attention" | "insights" | "upnext"; severity: string; title: string; body: string;
  detail: string | null; impact: string | null; explanation: string; actions: CardAction[]; day?: string; at?: string;
};

export type Proposal = {
  id: string; kind: string; title: string; summary: string; operations: Operation[];
  explanation: Record<string, unknown>; status: string; source: string; created_at: string; audit_id: string | null;
};

export type Kpi = { id: string; label: string; value: number; baseline: number | null; target?: number; unit: string; better: "lower" | "higher" };

export type WeekMetrics = {
  week_start: string; label: string; phase: "past" | "current" | "future"; meeting_hours: number; meeting_count: number;
  focus_block_hours: number; deep_work_hours: number; after_hours_meetings: number; back_to_back: number;
  fragmentation: number; cost: number; by_category: Record<string, number>;
};

export type AnalyticsSummary = {
  user_timezone: string; weeks: WeekMetrics[]; kpis: Kpi[]; workload: { score: number; level: string; note: string };
  categories: { category: string; label: string; color: string; hours: number }[];
  heatmap: { days: string[]; hours: number[]; minutes_per_week: number[][] };
  collaborators: { person_id: string; name: string; title: string; company: string; hours: number; is_external: boolean }[];
  fairness: { person_id: string; name: string; city: string; timezone: string; count: number; examples: string[]; series: string[] }[];
  focus_goal_hours: number; last_week: WeekMetrics;
};

export type ForecastWeek = {
  offset: number; week_start: string; label: string; booked_hours: number; forecast_hours: number; low: number; high: number;
  p_over_cap: number; deep_work_forecast: number; protected_focus_hours: number; focus_at_risk: boolean;
};

export type Backtest = {
  lead_days: number; evaluated_weeks: number; mae_hours: Record<string, number | null>; interval_coverage: number | null;
  beats_baselines: boolean; caveat: string; wins?: string; by_lead?: Backtest[];
};

export type Forecast = { method: string; max_week_hours: number; weeks: ForecastWeek[]; backtest: Backtest };

export type RecurringRow = {
  series_id: string; title: string; cadence: string; duration_min: number; attendees: number; organizer_id: string;
  you_organize: boolean; per_month: number; hours_month: number; cost_month: number; avg_actual_min: number | null;
  attendance_rate: number | null; optional: boolean; unfair_for: string[]; upcoming: number;
  suggestion: { kind: string; label: string; detail: string; saves_hours_month: number; saves_cost_month: number; new_duration?: number };
};

export type Preferences = {
  person_id: string; focus_goal_hours: number; min_focus_block_min: number; preferred_period: string; buffer_min: number;
  max_meeting_hours_day: number; max_meeting_hours_week: number; lunch_start: string; lunch_end: string;
  quiet_start: string; quiet_end: string; no_meeting_days: number[]; autonomy: Record<string, string>;
  privacy: Record<string, boolean>; learned_weights: Record<string, number>; dismissed_conflicts: string[];
};

export type AiStatus = { engine: "claude" | "offline"; model: string | null; mode: string; reason: string };

export type Me = {
  person: Person; preferences: Preferences; ai: AiStatus;
  learned: { component: string; label: string; weight: number; delta: number }[];
};

export type Health = { status: string; version: string; now: string; simulated_clock: boolean; events: number; ai: AiStatus };

export type CommandResult = {
  text: string; parsed: Record<string, unknown>; chips: { label: string; value: string }[]; unknown_people: string[];
  engine: { engine: string; model?: string; latency_ms?: number; fallback_reason?: string; agrees_with_offline?: boolean };
  result:
    | ({ type: "slots"; mode: "new" | "reschedule"; title: string; event?: CalEvent; attendees?: Person[] } & SlotResult)
    | { type: "conflicts"; conflicts: Conflict[] }
    | { type: "analytics"; headline: string; kpis: Kpi[] }
    | { type: "brief"; event: CalEvent; brief: Brief; engine: string }
    | { type: "proposal"; proposal: Proposal; event?: CalEvent }
    | { type: "reminder"; event: CalEvent; minutes_before: number; message: string }
    | { type: "clarify"; message: string }
    | { type: "help"; message: string; examples: string[] };
};
