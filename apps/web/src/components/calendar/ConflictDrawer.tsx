"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Car, Eye, Flame, Lock, Moon, TriangleExclamationPoint, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { DraftBox } from "@/components/ProposalView";
import { useUi } from "@/components/providers";
import { Badge, Button, Drawer, FeedbackThumbs, ScoreBar, Spinner } from "@/components/ui";
import { api, track } from "@/lib/api";
import { fmtRange } from "@/lib/time";
import type { Conflict, ConflictOption } from "@/lib/types";

const ICON = { overlap: TriangleExclamationPoint, travel: Car, focus: Lock, overload: Flame, outside_hours: Moon };
const LABEL = { overlap: "Double-booked", travel: "Not enough travel time", focus: "Meeting inside focus time", overload: "Overloaded day", outside_hours: "Outside working hours" };

export function ConflictDrawer({ open, focusId, onClose, tz, onJump }: { open: boolean; focusId?: string; onClose: () => void; tz: string; onJump: (iso: string) => void }) {
  const { toast, refreshAll, setGhost } = useUi();
  const conflicts = useQuery({ queryKey: ["conflicts"], queryFn: () => api.get<Conflict[]>("/api/conflicts") });
  const [expanded, setExpanded] = useState<string | null>(focusId ?? null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  const active = expanded ?? conflicts.data?.[0]?.id ?? null;
  const tracked = useRef(false);
  useEffect(() => { // once per opening: the denominator of the acceptance rate
    if (!open || tracked.current || !conflicts.data) return;
    tracked.current = true;
    track("suggestion_shown", { kind: "conflicts", count: conflicts.data.length });
  }, [open, conflicts.data]);

  async function apply(c: Conflict, o: ConflictOption) {
    setBusy(o.id);
    try {
      const r = await api.post<{ audit_id: string; summary: string; draft: { subject: string; body: string } | null }>("/api/conflicts/resolve", { conflict_id: c.id, option_id: o.id });
      setGhost(null);
      refreshAll();
      toast(`Resolved: ${r.summary}`, { auditId: r.audit_id });
      setDraft(r.draft);
      setExpanded(null);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not apply", { tone: "error" });
    } finally { setBusy(null); }
  }

  return (
    <Drawer open={open} onClose={() => { setGhost(null); onClose(); }} width="w-[500px]" title="Conflict center"
      subtitle="Ranked fixes: value kept minus disruption to other people. Preview first; every fix can be undone.">
      {conflicts.isPending && <Spinner />}
      {draft && <div className="mb-4"><p className="text-xs text-muted">Kairos drafted a note for the people affected (it never sends anything for you):</p><DraftBox draft={draft} /></div>}
      {conflicts.data?.length === 0 && <p className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800">No conflicts in the next two weeks. 🎉</p>}
      <ul className="space-y-3">
        {(conflicts.data ?? []).map((c) => {
          const Icon = ICON[c.type];
          const open = active === c.id;
          return (
            <li key={c.id} className={clsx("rounded-xl border", c.severity === "high" ? "border-red-200" : c.severity === "medium" ? "border-amber-200" : "border-border")}>
              <button className="flex w-full items-start gap-3 p-3 text-left" aria-expanded={open} onClick={() => { setExpanded(open ? "" : c.id); onJump(c.starts_at); }}>
                <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", c.severity === "high" ? "text-red-600" : "text-amber-600")} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="text-xs font-semibold">{LABEL[c.type]}</span>
                    <Badge tone={c.severity === "high" ? "red" : c.severity === "medium" ? "amber" : "slate"}>{c.severity}</Badge>
                    <span className="text-[11px] text-muted">{c.day}</span></div>
                  <div className="mt-0.5 text-sm">{c.title}</div>
                  <div className="text-xs text-muted">{c.description}</div>
                </div>
              </button>
              {open && (
                <ol className="space-y-2 border-t border-border bg-slate-50/60 p-3">
                  {c.options.map((o, i) => (
                    <li key={o.id} className="rounded-lg border border-border bg-white p-3">
                      <div className="flex items-start gap-2">
                        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-indigo-50 text-[11px] font-semibold text-indigo-700">{i + 1}</span>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium">{o.label}</div>
                          <div className="text-xs text-muted">{o.description}</div>
                          <ul className="mt-1 space-y-0.5">{o.reasons.map((r) => <li key={r} className="text-[11px] text-emerald-700">✓ {r}</li>)}</ul>
                          <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted">
                            <Users className="h-3 w-3" aria-hidden />{o.people_affected === 0 ? "No one else affected" : `Affects ${o.people_affected} ${o.people_affected === 1 ? "person" : "people"}`}
                            <span className="w-20"><ScoreBar value={o.score} /></span>
                          </div>
                          {o.preview && <div className="mt-1 text-[11px] text-violet-700">New time: {fmtRange(o.preview.start, o.preview.end, tz)}</div>}
                        </div>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <Button size="sm" variant="primary" disabled={busy !== null} onClick={() => apply(c, o)}>Apply</Button>
                        {o.preview && <Button size="sm" onClick={() => { setGhost({ start: o.preview!.start, end: o.preview!.end, label: "Proposed" }); onJump(o.preview!.start); }}><Eye className="h-3.5 w-3.5" /> Preview</Button>}
                        <span className="ml-auto"><FeedbackThumbs targetType="conflict_option" targetId={o.id} /></span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </li>
          );
        })}
      </ul>
    </Drawer>
  );
}
