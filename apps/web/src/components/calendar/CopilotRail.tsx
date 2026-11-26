"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Bell, Brain, Car, Sparkles, TriangleExclamationPoint, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { useCardActions } from "@/components/calendar/useCardActions";
import { Badge, Button, FeedbackThumbs, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/time";
import type { InsightCard, Reminder } from "@/lib/types";

const SECTION: Record<InsightCard["section"], string> = { attention: "Needs attention", insights: "Insights", upnext: "Up next" };

/**
 * The Copilot rail. From the xl breakpoint up it sits beside the calendar; below it, it is hidden and
 * `open` shows it as a slide-over (backdrop click, the close button or Escape dismisses it).
 */
export function CopilotRail({ tz, open = false, onClose }: { tz: string; open?: boolean; onClose?: () => void }) {
  const cards = useQuery({ queryKey: ["insights"], queryFn: () => api.get<InsightCard[]>("/api/insights") });
  const reminders = useQuery({ queryKey: ["reminders", "upcoming"], queryFn: () => api.get<Reminder[]>("/api/reminders/upcoming?hours=48"), refetchInterval: 60_000 });
  const digest = useQuery({ queryKey: ["digest"], queryFn: () => api.get<{ headline: string; date: string }>("/api/digest") });
  const act = useCardActions();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open || !onClose) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    // A drawer opened from a card sits above the slide-over: its Escape closes it first, the next one closes the rail.
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector('[role="dialog"]') && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);

  return (
    <>
    {open && <div className="fixed inset-0 z-[25] bg-slate-900/20 xl:hidden" onClick={onClose} aria-hidden />}
    <aside ref={ref} id="copilot-rail" tabIndex={-1} aria-label="Copilot"
      className={clsx("w-[340px] max-w-[calc(100vw-3.5rem)] shrink-0 flex-col overflow-y-auto border-l border-border bg-surface outline-none",
        open ? "animate-slide-in fixed inset-y-0 right-0 z-[26] flex shadow-2xl xl:static xl:z-auto xl:animate-none xl:shadow-none" : "hidden xl:flex")}>
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-ai" aria-hidden />Copilot
          {onClose && (
            <button onClick={onClose} aria-label="Close Copilot" className="ml-auto rounded-md p-1 text-muted hover:bg-slate-100 hover:text-ink xl:hidden">
              <X className="h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
        {digest.data && <p className="mt-1 text-xs text-muted">Today: {digest.data.headline}</p>}
      </div>
      <div className="space-y-5 p-4">
        {cards.isPending && <Spinner label="Reading your week" />}
        {(["attention", "insights", "upnext"] as const).map((section) => {
          const items = (cards.data ?? []).filter((c) => c.section === section);
          if (!items.length) return null;
          return (
            <section key={section}>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">{SECTION[section]} · {items.length}</h3>
              <ul className="space-y-2">
                {items.map((c) => (
                  <li key={c.id} className={clsx("rounded-xl border p-3", c.kind === "conflict" ? (c.severity === "high" ? "border-red-200 bg-red-50/40" : "border-amber-200 bg-amber-50/30") : "border-border bg-white")}>
                    <div className="flex items-start gap-2">
                      {c.kind === "conflict" ? <TriangleExclamationPoint className="mt-0.5 h-4 w-4 shrink-0 text-red-600" aria-hidden /> : <Brain className="mt-0.5 h-4 w-4 shrink-0 text-ai" aria-hidden />}
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold">{c.title}</div>
                        <div className="mt-0.5 text-xs text-slate-700">{c.body}</div>
                        {c.detail && <div className="mt-1 text-[11px] text-muted">{c.detail}</div>}
                        {c.impact && <Badge tone="green" className="mt-1.5">{c.impact}</Badge>}
                        {c.explanation && <p className="mt-1.5 text-[11px] italic text-muted">Why: {c.explanation}</p>}
                        <div className="mt-2 flex flex-wrap items-center gap-1.5">
                          {c.actions.map((a) => (
                            <Button key={a.label} size="sm" variant={a.type === "open_conflict" || a.type === "focus_plan" || a.type === "series_action" || a.type === "operations" ? "primary" : "secondary"} onClick={() => act(a)}>{a.label}</Button>
                          ))}
                          <span className="ml-auto"><FeedbackThumbs targetType="card" targetId={c.id} /></span>
                        </div>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        <section>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Smart reminders · next 48h</h3>
          {reminders.data?.length === 0 && <p className="text-xs text-muted">Nothing needs a nudge.</p>}
          <ul className="space-y-1.5">
            {(reminders.data ?? []).slice(0, 8).map((r) => (
              <li key={r.id} className={clsx("flex gap-2 rounded-lg px-2 py-1.5 text-xs", r.due ? "bg-amber-50" : "bg-slate-50")}>
                {r.kind === "leave" ? <Car className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-600" aria-hidden /> : <Bell className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600" aria-hidden />}
                <div className="min-w-0">
                  <div className="font-medium">{fmtTime(r.fire_at, tz)} · {r.title}</div>
                  <div className="truncate text-[11px] text-muted" title={r.rationale}>{r.rationale}</div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </aside>
    </>
  );
}
