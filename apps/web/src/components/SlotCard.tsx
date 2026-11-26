"use client";

import { clsx } from "clsx";
import { Check, TriangleExclamationPoint } from "lucide-react";

import { Button, FeedbackThumbs, ScoreBar } from "@/components/ui";
import type { Slot } from "@/lib/types";

export function SlotCard({ slot, onBook, onHover, busy, compact = false }: {
  slot: Slot; onBook: () => void; onHover?: (s: Slot | null) => void; busy?: boolean; compact?: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-white p-3 transition hover:border-indigo-300 hover:shadow-sm"
      onMouseEnter={() => onHover?.(slot)} onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(slot)}>
      <div className="flex items-center gap-3">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-indigo-50 text-xs font-semibold text-indigo-700">{slot.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{slot.label}</div>
          <div className="mt-1 flex items-center gap-2"><ScoreBar value={slot.score} /><span className="text-[11px] text-muted">{Math.round(slot.score)}</span></div>
        </div>
        <Button variant="primary" size="sm" onClick={onBook} disabled={busy}>Book</Button>
      </div>
      {!compact && (
        <>
          <ul className="mt-2 space-y-0.5">
            {slot.reasons.slice(0, 3).map((r) => (
              <li key={r} className="flex gap-1.5 text-xs text-emerald-700"><Check className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{r}</li>
            ))}
            {slot.warnings.slice(0, 3).map((w) => (
              <li key={w} className="flex gap-1.5 text-xs text-amber-700"><TriangleExclamationPoint className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{w}</li>
            ))}
          </ul>
          <div className="mt-2 flex flex-wrap gap-1">
            {slot.attendees.map((a) => (
              <span key={a.person_id} title={a.timezone}
                className={clsx("rounded-md px-1.5 py-0.5 text-[11px]",
                  a.optional && !a.available ? "bg-slate-100 text-slate-400 line-through" :
                  a.status === "core" ? "bg-emerald-50 text-emerald-800" : a.status === "edge" ? "bg-amber-50 text-amber-800" : "bg-red-50 text-red-700")}>
                {a.name.split(" ")[0]} {a.local_label.split(" ").slice(1).join(" ")} {a.tz_abbr}{a.optional ? " (opt)" : ""}
              </span>
            ))}
          </div>
          <div className="mt-2 flex justify-end"><FeedbackThumbs targetType="slot" targetId={`${slot.start}`} /></div>
        </>
      )}
    </div>
  );
}
