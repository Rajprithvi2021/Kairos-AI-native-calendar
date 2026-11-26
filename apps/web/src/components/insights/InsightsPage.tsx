"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Gauge, Globe, Scale, TrendingUp, Users } from "lucide-react";
import { useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ProposalView } from "@/components/ProposalView";
import { useUi } from "@/components/providers";
import { Badge, Button, Card, Drawer, ErrorNote, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { AnalyticsSummary, Forecast, Proposal, RecurringRow } from "@/lib/types";

function fmtVal(v: number, unit: string) {
  return unit === "$" ? `$${Math.round(v).toLocaleString()}` : `${v}${unit}`;
}

export function InsightsPage() {
  const summary = useQuery({ queryKey: ["analytics", "summary"], queryFn: () => api.get<AnalyticsSummary>("/api/analytics/summary") });
  const forecast = useQuery({ queryKey: ["forecast"], queryFn: () => api.get<Forecast>("/api/analytics/forecast") });
  const recurring = useQuery({ queryKey: ["recurring"], queryFn: () => api.get<RecurringRow[]>("/api/analytics/recurring") });
  const { toast } = useUi();
  const [proposal, setProposal] = useState<{ p: Proposal; draft: { subject: string; body: string } | null } | null>(null);

  if (summary.isError) return <div className="p-8"><ErrorNote error={summary.error} /></div>;
  if (!summary.data) return <div className="p-8"><Spinner label="Analysing 13 weeks of calendar" /></div>;
  const s = summary.data;
  const cats = s.categories.map((c) => c.category);
  const colors = Object.fromEntries(s.categories.map((c) => [c.category, c.color]));
  const labels = Object.fromEntries(s.categories.map((c) => [c.category, c.label]));
  const allocation = s.weeks.map((w) => ({ label: w.label, phase: w.phase, ...Object.fromEntries(cats.map((c) => [c, w.by_category[c] ?? 0])) }));
  const fc = forecast.data;
  const fcData = (fc?.weeks ?? []).map((w) => ({ label: w.label, booked: w.booked_hours, forecast: w.forecast_hours, band: [w.low, w.high], p: w.p_over_cap }));
  const maxCell = Math.max(1, ...s.heatmap.minutes_per_week.flat());

  async function applySeries(row: RecurringRow) {
    const r = await api.post<{ proposal: Proposal | null; draft: { subject: string; body: string } | null; message?: string }>(`/api/analytics/recurring/${row.series_id}/proposal`);
    if (r.proposal) setProposal({ p: r.proposal, draft: r.draft });
    else toast(r.message ?? "No automatic change available.", { tone: "info" });
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Insights</h1>
            <p className="text-sm text-muted">Where your time goes, what it costs, and what&apos;s coming — computed from calendar metadata only.</p>
          </div>
          <Badge tone={s.workload.level === "healthy" ? "green" : s.workload.level === "elevated" ? "amber" : "red"}>
            <Gauge className="h-3 w-3" />Workload signal {s.workload.score}/100 · {s.workload.level}
          </Badge>
        </header>

        <section className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6" aria-label="Key metrics">
          {s.kpis.map((k) => {
            const delta = k.baseline != null ? k.value - k.baseline : null;
            const good = delta == null ? null : k.better === "lower" ? delta <= 0 : delta >= 0;
            return (
              <Card key={k.id} className="p-3">
                <div className="text-[11px] text-muted">{k.label}</div>
                <div className="mt-1 text-xl font-semibold">{fmtVal(k.value, k.unit)}</div>
                {delta != null && (Math.abs(delta) < 0.05 ? (
                  <div className="text-[11px] text-muted">≈ 8-wk avg</div>
                ) : (
                  <div className={clsx("text-[11px]", good ? "text-emerald-700" : "text-red-600")}>
                    {delta > 0 ? "▲" : "▼"} {fmtVal(Math.abs(Math.round(delta * 10) / 10), k.unit)} vs 8-wk avg
                  </div>
                ))}
                {k.target != null && <div className="text-[11px] text-muted">goal {k.target}h</div>}
              </Card>
            );
          })}
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="p-4">
            <h2 className="mb-1 text-sm font-semibold">Time allocation by week</h2>
            <p className="mb-3 text-[11px] text-muted">Hours per category; future weeks show what&apos;s booked so far.</p>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={allocation} margin={{ left: -18 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef0f4" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={1} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v, n) => [`${Number(v).toFixed(1)}h`, labels[String(n)] ?? n]} />
                  <Legend formatter={(v) => labels[v] ?? v} wrapperStyle={{ fontSize: 10 }} />
                  {cats.map((c) => <Bar key={c} dataKey={c} stackId="a" fill={colors[c]} isAnimationActive={false} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card className="p-4">
            <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold"><TrendingUp className="h-4 w-4 text-ai" />Meeting-load forecast</h2>
            <p className="mb-3 text-[11px] text-muted">Booked so far (bars) vs. forecast with 80% interval (band). Dashed line: your {fc?.max_week_hours ?? 20}h weekly cap.</p>
            {forecast.isPending ? <Spinner /> : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={fcData} margin={{ left: -18 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eef0f4" />
                    <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                    <YAxis tick={{ fontSize: 10 }} />
                    <Tooltip formatter={(v, n) => [Array.isArray(v) ? `${v[0]}–${v[1]}h` : `${v}h`, n]} />
                    <Area dataKey="band" name="80% interval" fill="#c4b5fd" stroke="none" fillOpacity={0.45} isAnimationActive={false} />
                    <Bar dataKey="booked" name="Booked" fill="#94a3b8" barSize={22} isAnimationActive={false} />
                    <Line dataKey="forecast" name="Forecast" stroke="#7c3aed" strokeWidth={2} dot isAnimationActive={false} />
                    <ReferenceLine y={fc?.max_week_hours} stroke="#dc2626" strokeDasharray="4 4" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
            {fc && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {fc.weeks.filter((w) => w.offset > 0).map((w) => (
                  <Badge key={w.week_start} tone={w.p_over_cap >= 0.5 ? "red" : w.focus_at_risk ? "amber" : "green"}>
                    {w.label}: {Math.round(w.p_over_cap * 100)}% over cap{w.focus_at_risk ? " · focus at risk" : ""}
                  </Badge>
                ))}
              </div>
            )}
          </Card>
        </div>

        {fc && (
          <Card className="p-4">
            <h2 className="text-sm font-semibold">Model card · forecast</h2>
            <p className="mt-1 text-xs text-slate-700">{fc.method}</p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-left text-muted"><th className="py-1">Lead time</th><th>Model MAE</th><th>Booked-so-far</th><th>Last week</th><th>Trailing mean</th><th>80% coverage</th><th>Beats all baselines?</th></tr></thead>
                <tbody>
                  {(fc.backtest.by_lead ?? [fc.backtest]).map((b) => (
                    <tr key={b.lead_days} className="border-t border-border">
                      <td className="py-1">{b.lead_days} days</td><td className="font-semibold">{b.mae_hours.model}h</td><td>{b.mae_hours.booked_so_far}h</td>
                      <td>{b.mae_hours.last_week}h</td><td>{b.mae_hours.trailing_mean}h</td><td>{b.interval_coverage != null ? `${Math.round(b.interval_coverage * 100)}%` : "–"}</td>
                      <td>{b.beats_baselines ? "Yes" : "Not yet"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-amber-700">{fc.backtest.caveat} Rolling-origin backtest over {fc.backtest.evaluated_weeks} weeks; results are reported as-is.</p>
          </Card>
        )}

        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-4 lg:col-span-2">
            <h2 className="mb-3 text-sm font-semibold">When your meetings happen (avg minutes / week)</h2>
            <div className="grid gap-1" style={{ gridTemplateColumns: `40px repeat(${s.heatmap.hours.length}, minmax(0,1fr))` }}>
              <div />
              {s.heatmap.hours.map((h) => <div key={h} className="text-center text-[10px] text-muted">{((h + 11) % 12) + 1}{h < 12 ? "a" : "p"}</div>)}
              {s.heatmap.days.map((d, i) => (
                <div key={d} className="contents">
                  <div className="text-[11px] text-muted">{d}</div>
                  {s.heatmap.minutes_per_week[i].map((v, j) => (
                    <div key={j} title={`${d} ${s.heatmap.hours[j]}:00 — ${v} min/week`} className="h-7 rounded"
                      style={{ background: `rgba(79, 70, 229, ${0.06 + 0.9 * (v / maxCell)})` }} />
                  ))}
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Users className="h-4 w-4" />Top collaborators (4 weeks)</h2>
            <ul className="space-y-1.5">
              {s.collaborators.map((c) => (
                <li key={c.person_id} className="flex items-center justify-between text-xs">
                  <span>{c.name} <span className="text-muted">{c.is_external ? c.company : c.title}</span></span><b>{c.hours}h</b>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <Card className="p-4">
          <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold"><Scale className="h-4 w-4" />Recurring meeting audit</h2>
          <p className="mb-3 text-[11px] text-muted">Meeting necessity advisor: shorten, thin out or go async — with the message drafted for you.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-muted"><th className="py-1.5">Series</th><th>Cadence</th><th>People</th><th>Cost / month</th><th>Typical length</th><th>Suggestion</th><th /></tr></thead>
              <tbody>
                {(recurring.data ?? []).map((r) => (
                  <tr key={r.series_id} className="border-t border-border align-top">
                    <td className="py-2 font-medium">{r.title}{r.optional && <Badge className="ml-1">optional</Badge>}</td>
                    <td>{r.cadence}</td><td>{r.attendees}</td><td>${r.cost_month.toLocaleString()}</td>
                    <td>{r.avg_actual_min ? `${Math.round(r.avg_actual_min)} of ${r.duration_min} min` : `${r.duration_min} min`}</td>
                    <td><b className={r.suggestion.kind === "keep" ? "text-slate-500" : "text-ai"}>{r.suggestion.label}</b><div className="text-[11px] text-muted">{r.suggestion.detail}</div>
                      {r.suggestion.saves_hours_month > 0 && <Badge tone="green" className="mt-1">saves {r.suggestion.saves_hours_month}h/mo</Badge>}</td>
                    <td className="text-right">{(r.suggestion.kind === "shorten" || r.suggestion.kind === "async") && <Button size="sm" variant="primary" onClick={() => applySeries(r)}>Apply…</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="p-4" >
          <h2 id="fairness" className="mb-1 flex items-center gap-2 text-sm font-semibold"><Globe className="h-4 w-4" />Time-zone fairness</h2>
          <p className="mb-3 text-[11px] text-muted">Who takes the inconvenient slot when they meet with you (last 4 weeks + next 2).</p>
          {s.fairness.length === 0 ? <p className="text-xs text-muted">Nobody is meeting you outside their working hours.</p> : (
            <ul className="grid gap-2 md:grid-cols-2">
              {s.fairness.map((f) => (
                <li key={f.person_id} className="rounded-lg border border-border p-3 text-xs">
                  <div className="flex items-center justify-between"><b>{f.name}</b><Badge tone={f.count >= 5 ? "red" : "amber"}>{f.count} outside-hours meetings</Badge></div>
                  <div className="text-muted">{f.city} · {f.timezone}</div>
                  <ul className="mt-1 list-disc pl-4">{f.examples.map((e, i) => <li key={`${i}-${e}`}>{e}</li>)}</ul>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Drawer open={!!proposal} onClose={() => setProposal(null)} title={proposal?.p.title ?? ""} subtitle="Review before applying. Kairos proposes; you decide.">
        {proposal && <ProposalView proposal={proposal.p} draft={proposal.draft} onDone={() => setProposal(null)} />}
      </Drawer>
    </div>
  );
}
