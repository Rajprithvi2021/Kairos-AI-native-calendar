"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Brain, Clock, History, Shield, Sparkles, Upload } from "lucide-react";
import { useState } from "react";

import { useUi } from "@/components/providers";
import { AiBadge, Badge, Button, Card, ErrorNote, Field, inputCls, Segmented, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDay, fmtTime, zonedToUtc } from "@/lib/time";
import type { Health, Me, Preferences } from "@/lib/types";

type Audit = { id: string; action: string; actor: string; summary: string; change_count: number; created_at: string; undone: boolean };
type Calls = { status: { engine: string; model: string | null; reason: string }; calls: { task: string; engine: string; model: string | null; latency_ms: number; input_tokens: number | null; output_tokens: number | null; outcome: string; detail: string; at: string }[] };

const AUTONOMY = [
  { key: "scheduling", label: "Scheduling", help: "Find times and book meetings" },
  { key: "focus", label: "Focus protection", help: "Place focus blocks toward your goal" },
  { key: "reminders", label: "Reminders", help: "Smart prep / leave / follow-up nudges" },
  { key: "conflicts", label: "Conflict resolution", help: "Move or decline to resolve clashes" },
];

export function SettingsPage() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  if (me.isError) return <div className="p-8"><ErrorNote error={me.error} /></div>;
  if (!me.data) return <div className="p-8"><Spinner /></div>;
  // Keyed by user, not fetch time: a background refetch must never wipe edits being typed.
  return <SettingsForm key={me.data.person.id} me={me.data} />;
}

function SettingsForm({ me: meData }: { me: Me }) {
  const qc = useQueryClient();
  const { toast, refreshAll } = useUi();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/api/health") });
  const calls = useQuery({ queryKey: ["ai-status"], queryFn: () => api.get<Calls>("/api/ai/status") });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<Audit[]>("/api/audit?limit=15") });
  const google = useQuery({ queryKey: ["google"], queryFn: () => api.get<{ configured: boolean; message: string; scopes: string[] }>("/api/integrations/google/status") });
  const [p, setP] = useState<Preferences>(meData.preferences);
  const [hours, setHours] = useState({ work_start: meData.person.work_start, work_end: meData.person.work_end });
  const [simAt, setSimAt] = useState("");
  const tz = meData.person.timezone;

  async function undo(a: Audit) {
    try {
      await api.post(`/api/audit/${a.id}/undo`);
      refreshAll();
      toast(`Undone: ${a.summary}`);
    } catch (e) { toast(e instanceof Error ? e.message : "Could not undo", { tone: "error" }); }
  }

  async function save(patch: Partial<Preferences> & { work_start?: string; work_end?: string; reset_learning?: boolean }) {
    await api.put("/api/me/preferences", patch);
    await qc.invalidateQueries({ queryKey: ["me"] });
    refreshAll();
    toast("Preferences saved.");
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-6 p-6">
        <header>
          <h1 className="text-2xl font-semibold">Settings</h1>
          <p className="text-sm text-muted">{meData.person.name} · {meData.person.title} · {tz}</p>
        </header>

        <Card className="space-y-4 p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Clock className="h-4 w-4" />Working hours & focus</h2>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Day starts"><input type="time" className={inputCls} value={hours.work_start} onChange={(e) => setHours({ ...hours, work_start: e.target.value })} /></Field>
            <Field label="Day ends"><input type="time" className={inputCls} value={hours.work_end} onChange={(e) => setHours({ ...hours, work_end: e.target.value })} /></Field>
            <Field label="Weekly focus goal (h)"><input type="number" min={0} max={40} className={inputCls} value={p.focus_goal_hours} onChange={(e) => setP({ ...p, focus_goal_hours: Number(e.target.value) })} /></Field>
            <Field label="Min focus block (min)"><input type="number" min={30} max={240} step={15} className={inputCls} value={p.min_focus_block_min} onChange={(e) => setP({ ...p, min_focus_block_min: Number(e.target.value) })} /></Field>
            <Field label="Buffer between meetings (min)"><input type="number" min={0} max={30} className={inputCls} value={p.buffer_min} onChange={(e) => setP({ ...p, buffer_min: Number(e.target.value) })} /></Field>
            <Field label="Max meeting hours / day"><input type="number" min={1} max={12} step={0.5} className={inputCls} value={p.max_meeting_hours_day} onChange={(e) => setP({ ...p, max_meeting_hours_day: Number(e.target.value) })} /></Field>
            <Field label="Max meeting hours / week"><input type="number" min={5} max={50} className={inputCls} value={p.max_meeting_hours_week} onChange={(e) => setP({ ...p, max_meeting_hours_week: Number(e.target.value) })} /></Field>
            <Field label="Preferred meeting time">
              <select className={inputCls} value={p.preferred_period} onChange={(e) => setP({ ...p, preferred_period: e.target.value })}>
                <option value="any">No preference</option><option value="morning">Mornings</option><option value="afternoon">Afternoons</option>
              </select>
            </Field>
          </div>
          <Button variant="primary" onClick={() => save({ ...hours, focus_goal_hours: p.focus_goal_hours, min_focus_block_min: p.min_focus_block_min, buffer_min: p.buffer_min, max_meeting_hours_day: p.max_meeting_hours_day, max_meeting_hours_week: p.max_meeting_hours_week, preferred_period: p.preferred_period })}>Save</Button>
        </Card>

        <Card className="space-y-3 p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-ai" />Autonomy dial</h2>
          <p className="text-xs text-muted">How much Kairos may do on its own. Everything is audited and undoable either way. In this prototype “Auto” is wired for focus protection; the others always ask.</p>
          <ul className="divide-y divide-border">
            {AUTONOMY.map((a) => (
              <li key={a.key} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div><div className="text-sm font-medium">{a.label}</div><div className="text-[11px] text-muted">{a.help}</div></div>
                <Segmented label={a.label} value={(p.autonomy[a.key] ?? "suggest") as "suggest" | "ask" | "auto"}
                  options={[{ value: "suggest", label: "Suggest" }, { value: "ask", label: "Ask first" }, { value: "auto", label: "Auto" }]}
                  onChange={(v) => { setP({ ...p, autonomy: { ...p.autonomy, [a.key]: v } }); save({ autonomy: { [a.key]: v } }); }} />
              </li>
            ))}
          </ul>
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          <Card className="space-y-3 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Shield className="h-4 w-4" />Privacy (what the AI sees)</h2>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={p.privacy.send_titles_to_ai ?? true} onChange={(e) => save({ privacy: { send_titles_to_ai: e.target.checked } })} />
              <span>Send event titles to the AI<span className="block text-[11px] text-muted">Off: Claude sees only “[Customer meeting]”-style categories.</span></span></label>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={p.privacy.redact_external_names ?? true} onChange={(e) => save({ privacy: { redact_external_names: e.target.checked } })} />
              <span>Pseudonymise external people<span className="block text-[11px] text-muted">Claude sees “External: COO at Brightwave Logistics”, never names or emails.</span></span></label>
            <p className="text-[11px] text-muted">Invite text written by others is always fenced as untrusted data (prompt-injection guard).</p>
          </Card>

          <Card className="space-y-3 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Brain className="h-4 w-4" />What Kairos has learned</h2>
            <p className="text-[11px] text-muted">Slot-ranking weights adapt to the options you pick (bounded pairwise learning).</p>
            <ul className="space-y-1 text-xs">
              {meData.learned.map((l) => (
                <li key={l.component} className="flex justify-between"><span>{l.label}</span><span>{(l.weight * 100).toFixed(0)}% {l.delta !== 0 && <span className={l.delta > 0 ? "text-emerald-700" : "text-red-600"}>({l.delta > 0 ? "+" : ""}{(l.delta * 100).toFixed(1)})</span>}</span></li>
              ))}
            </ul>
            <Button size="sm" onClick={() => save({ reset_learning: true })}>Reset learning</Button>
          </Card>
        </div>

        <Card className="space-y-3 p-5">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-ai" />AI engine & activity log</h2>
            <AiBadge engine={calls.data?.status.engine} model={calls.data?.status.model} />
          </div>
          <p className="text-xs text-muted">{calls.data?.status.reason}. To enable Claude, put <code>ANTHROPIC_API_KEY=…</code> in <code>services/api/.env</code> and restart the API. Content is never logged — only task, engine, latency, tokens and outcome.</p>
          <div className="max-h-56 overflow-y-auto">
            <table className="w-full text-[11px]">
              <thead><tr className="text-left text-muted"><th>When</th><th>Task</th><th>Engine</th><th>Latency</th><th>Tokens in/out</th><th>Outcome</th></tr></thead>
              <tbody>
                {(calls.data?.calls ?? []).map((c, i) => (
                  <tr key={i} className="border-t border-border"><td className="py-1">{fmtTime(c.at, tz)}</td><td>{c.task}</td><td>{c.engine}</td><td>{Math.round(c.latency_ms)} ms</td>
                    <td>{c.input_tokens ?? "–"}/{c.output_tokens ?? "–"}</td><td><Badge tone={c.outcome === "ok" ? "green" : "amber"}>{c.outcome}</Badge> <span className="text-muted">{c.detail}</span></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="space-y-3 p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><History className="h-4 w-4" />Change history</h2>
          <p className="text-xs text-muted">Every calendar change, by you or by Kairos, newest first. Undo works while the event is still as that change left it.</p>
          {audit.data?.length === 0 && <p className="text-xs text-muted">No changes yet.</p>}
          <ul className="max-h-72 divide-y divide-border overflow-y-auto">
            {(audit.data ?? []).map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className={clsx("truncate font-medium", a.undone && "text-muted line-through")}>{a.summary}</div>
                  <div className="text-[11px] text-muted">{fmtDay(a.created_at, tz)} {fmtTime(a.created_at, tz)} · {a.actor === "ai" ? "Kairos (auto)" : "You"} · {a.change_count} change{a.change_count === 1 ? "" : "s"}</div>
                </div>
                {a.undone ? <Badge tone="slate">Undone</Badge> : <Button size="sm" onClick={() => undo(a)} aria-label={`Undo: ${a.summary}`}>Undo</Button>}
              </li>
            ))}
          </ul>
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          <Card className="space-y-3 p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold"><Upload className="h-4 w-4" />Integrations</h2>
            <Field label="Import an .ics file" hint="Export from Google Calendar, Outlook or Apple Calendar. Recurring events are expanded.">
              <input type="file" accept=".ics,text/calendar" className="text-xs" onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                const form = new FormData();
                form.append("file", f);
                try {
                  const r = await api.upload<{ imported: number; skipped: number }>("/api/import/ics", form);
                  refreshAll();
                  toast(`Imported ${r.imported} events (${r.skipped} already present).`);
                } catch (err) { toast(err instanceof Error ? err.message : "Import failed", { tone: "error" }); }
              }} />
            </Field>
            <div className="rounded-lg bg-slate-50 p-3 text-xs">
              <b>Google Calendar (live sync)</b> <Badge tone={google.data?.configured ? "green" : "slate"}>{google.data?.configured ? "ready" : "not configured"}</Badge>
              <p className="mt-1 text-muted">{google.data?.message} Scope: calendar.readonly.</p>
            </div>
          </Card>

          <Card className="space-y-3 p-5">
            <h2 className="text-sm font-semibold">Demo controls</h2>
            <p className="text-xs text-muted">Clock: {health.data ? `${fmtDay(health.data.now, tz)} ${fmtTime(health.data.now, tz)}` : "…"} {health.data?.simulated_clock && <Badge tone="amber">simulated</Badge>}</p>
            <Field label="Simulate “now” (your time zone)" hint="Useful to watch reminders fire, e.g. the morning of the onsite.">
              <div className="flex gap-2">
                <input type="datetime-local" className={inputCls} value={simAt} onChange={(e) => setSimAt(e.target.value)} />
                <Button size="sm" disabled={!simAt} onClick={async () => {
                  const [d, t] = simAt.split("T");
                  const [y, m, day] = d.split("-").map(Number);
                  const [hh, mm] = t.split(":").map(Number);
                  await api.post("/api/demo/clock", { now: zonedToUtc(y, m, day, hh, mm, tz).toISOString() });
                  await qc.invalidateQueries({ queryKey: ["health"] });
                  refreshAll();
                  toast("Clock set.");
                }}>Set</Button>
              </div>
            </Field>
            <div className="flex gap-2">
              <Button size="sm" onClick={async () => { await api.post("/api/demo/clock", { now: null }); await qc.invalidateQueries({ queryKey: ["health"] }); refreshAll(); toast("Back to real time."); }}>Use real time</Button>
              <Button size="sm" variant="danger" onClick={async () => { await api.post("/api/demo/reset"); await qc.invalidateQueries(); toast("Demo data reset."); }}>Reset demo data</Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
