"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, FlaskConical, Play, RefreshCw, Square } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";

import { useUi } from "@/components/providers";
import { Badge, Button, Card, Field, inputCls } from "@/components/ui";
import { api } from "@/lib/api";

const TASKS = [
  { id: "T1", text: "Schedule a 45-minute meeting with Priya and Alex next week at a time that's fair for Bangalore." },
  { id: "T2", text: "Resolve the double-booking Kairos flagged on your calendar." },
  { id: "T3", text: "Make sure you'll be on time and prepared for the Cobalt Health onsite visit." },
  { id: "T4", text: "Find how many hours you spent in meetings last week, then act on one recommendation." },
  { id: "T5", text: "Protect at least 6 hours of focus time next week." },
];

type Metrics = {
  suggestions_shown: number; actions_applied: number; acceptance_rate: number | null; undo_rate: number | null;
  avg_rank_picked: number | null; feedback: { up: number; down: number }; commands: number;
  tasks: { task_id: string; n: number; success_rate: number; median_time_s: number | null; mean_seq: number | null }[];
};

type Row = { running: boolean; started: number | null; elapsed: number; success: "yes" | "partial" | "no"; seq: number | null; notes: string; saved: boolean };

// Participant ID lives in localStorage (per browser); read it as an external store, not via an effect.
const PID_KEY = "kairos.participant";
const PID_EVENT = "kairos-participant";
function subscribePid(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(PID_EVENT, cb);
  return () => { window.removeEventListener("storage", cb); window.removeEventListener(PID_EVENT, cb); };
}
function readPid() {
  try { return window.localStorage.getItem(PID_KEY) ?? ""; } catch { return ""; }
}
function writePid(v: string) {
  try { window.localStorage.setItem(PID_KEY, v); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event(PID_EVENT));
}

export function StudyPage() {
  const { toast } = useUi();
  const pid = useSyncExternalStore(subscribePid, readPid, () => "");
  const [rows, setRows] = useState<Record<string, Row>>(() => Object.fromEntries(TASKS.map((t) => [t.id, { running: false, started: null, elapsed: 0, success: "yes", seq: null, notes: "", saved: false }])));
  const [nowTick, setNowTick] = useState(0);
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api.get<Metrics>("/api/research/metrics") });

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(performance.now()), 500);
    return () => window.clearInterval(id);
  }, []);

  const update = (id: string, patch: Partial<Row>) => setRows((r) => ({ ...r, [id]: { ...r[id], ...patch } }));
  const elapsed = (r: Row) => r.elapsed + (r.running && r.started ? Math.max(0, nowTick - r.started) / 1000 : 0);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <header>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><FlaskConical className="h-6 w-6 text-ai" />Study mode</h1>
          <p className="text-sm text-muted">Moderated usability sessions (see docs/05-user-testing-plan.md). Telemetry and feedback stay in the local database.</p>
        </header>

        <Card className="flex flex-wrap items-end gap-3 p-4">
          <Field label="Participant ID" hint="Use codes (P01…), never names.">
            <input className={inputCls} value={pid} placeholder="P01" onChange={(e) => writePid(e.target.value)} />
          </Field>
          <a href="/api/research/export.csv" className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-white px-3.5 py-2 text-sm font-medium hover:bg-slate-50"><Download className="h-4 w-4" />Export CSV</a>
          <Button onClick={() => metrics.refetch()}><RefreshCw className="h-4 w-4" />Refresh metrics</Button>
        </Card>

        <section className="space-y-3">
          {TASKS.map((t) => {
            const r = rows[t.id];
            const secs = elapsed(r);
            return (
              <Card key={t.id} className="p-4">
                <div className="flex flex-wrap items-start gap-3">
                  <Badge tone="violet">{t.id}</Badge>
                  <p className="min-w-[240px] flex-1 text-sm">{t.text}</p>
                  <span className="w-16 text-right font-mono text-sm">{Math.floor(secs / 60)}:{String(Math.floor(secs % 60)).padStart(2, "0")}</span>
                  {r.running
                    ? <Button size="sm" variant="danger" onClick={() => update(t.id, { running: false, elapsed: r.elapsed + (performance.now() - (r.started ?? performance.now())) / 1000, started: null })}><Square className="h-3.5 w-3.5" />Stop</Button>
                    : <Button size="sm" variant="primary" onClick={() => update(t.id, { running: true, started: performance.now(), saved: false })}><Play className="h-3.5 w-3.5" />{r.elapsed ? "Resume" : "Start"}</Button>}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-4 text-xs">
                  <label className="flex items-center gap-1.5">Success
                    <select className="rounded border border-border px-1.5 py-1" value={r.success} onChange={(e) => update(t.id, { success: e.target.value as Row["success"] })}>
                      <option value="yes">yes</option><option value="partial">partial</option><option value="no">no</option>
                    </select></label>
                  <span className="flex items-center gap-1" role="radiogroup" aria-label={`${t.id} ease rating`}>SEQ (1 very hard – 7 very easy)
                    {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                      <button key={n} role="radio" aria-checked={r.seq === n} onClick={() => update(t.id, { seq: n })}
                        className={`h-6 w-6 rounded ${r.seq === n ? "bg-primary text-white" : "border border-border"}`}>{n}</button>
                    ))}
                  </span>
                  <input className="min-w-[200px] flex-1 rounded border border-border px-2 py-1" placeholder="Observer notes" value={r.notes} onChange={(e) => update(t.id, { notes: e.target.value })} />
                  <Button size="sm" disabled={!pid || r.running || r.saved} onClick={async () => {
                    await api.post("/api/research/results", { participant_id: pid, task_id: t.id, duration_s: Math.round(secs * 10) / 10, success: r.success, seq: r.seq, notes: r.notes });
                    update(t.id, { saved: true });
                    metrics.refetch();
                    toast(`${t.id} saved for ${pid}.`);
                  }}>{r.saved ? "Saved" : "Save"}</Button>
                </div>
              </Card>
            );
          })}
        </section>

        <Card className="p-4">
          <h2 className="mb-3 text-sm font-semibold">Live metrics</h2>
          {metrics.data && (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                {[
                  ["Suggestion acceptance", metrics.data.acceptance_rate != null ? `${Math.round(metrics.data.acceptance_rate * 100)}%` : "–"],
                  ["Undo rate", metrics.data.undo_rate != null ? `${Math.round(metrics.data.undo_rate * 100)}%` : "–"],
                  ["Avg rank picked", metrics.data.avg_rank_picked ?? "–"],
                  ["Feedback 👍 / 👎", `${metrics.data.feedback.up} / ${metrics.data.feedback.down}`],
                  ["Commands", metrics.data.commands],
                ].map(([k, v]) => <div key={String(k)} className="rounded-lg bg-slate-50 p-3"><div className="text-[11px] text-muted">{k}</div><div className="text-lg font-semibold">{v}</div></div>)}
              </div>
              <table className="mt-4 w-full text-xs">
                <thead><tr className="text-left text-muted"><th>Task</th><th>n</th><th>Success</th><th>Median time</th><th>Mean SEQ</th></tr></thead>
                <tbody>{metrics.data.tasks.map((t) => (
                  <tr key={t.task_id} className="border-t border-border"><td className="py-1">{t.task_id}</td><td>{t.n}</td><td>{Math.round(t.success_rate * 100)}%</td><td>{t.median_time_s != null ? `${t.median_time_s}s` : "–"}</td><td>{t.mean_seq ?? "–"}</td></tr>
                ))}</tbody>
              </table>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
