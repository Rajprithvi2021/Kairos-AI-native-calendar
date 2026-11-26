"use client";

import { clsx } from "clsx";
import { Lock, MapPin, Sparkles, TriangleExclamationPoint, Users } from "lucide-react";
import { useMemo } from "react";

import { layoutDay } from "@/lib/layout";
import { addLocalDays, fmtTime, localDateKey, minutesIntoDay, zonedParts } from "@/lib/time";
import type { CalEvent, Holiday } from "@/lib/types";

const DEFAULT_START = 7;
const DEFAULT_END = 20;
const PX_PER_MIN = 0.9;

type Props = {
  weekStart: Date;
  tz: string;
  now: Date;
  events: CalEvent[];
  holidays: Holiday[];
  workStart: number;
  workEnd: number;
  ghost: { start: string; end: string; label?: string } | null;
  onSelect: (id: string) => void;
};

export function WeekGrid({ weekStart, tz, now, events, holidays, workStart, workEnd, ghost, onSelect }: Props) {
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addLocalDays(weekStart, i, tz)), [weekStart, tz]);
  const byDay = useMemo(() => {
    const map = new Map<string, CalEvent[]>();
    for (const ev of events) {
      const key = localDateKey(new Date(ev.start), tz);
      map.set(key, [...(map.get(key) ?? []), ev]);
    }
    return map;
  }, [events, tz]);
  const todayKey = localDateKey(now, tz);
  // Show 7 AM - 8 PM by default, widened to fit anything earlier/later (e.g. a 6 AM cross-time-zone slot).
  const [START_HOUR, END_HOUR] = useMemo(() => {
    let lo = DEFAULT_START * 60;
    let hi = DEFAULT_END * 60;
    const spans = events.map((e) => [new Date(e.start), new Date(e.end)] as const);
    if (ghost) spans.push([new Date(ghost.start), new Date(ghost.end)] as const);
    for (const [s, e] of spans) {
      const sm = minutesIntoDay(s, tz);
      lo = Math.min(lo, sm);
      hi = Math.max(hi, sm + (e.getTime() - s.getTime()) / 60000);
    }
    return [Math.max(0, Math.floor(lo / 60)), Math.min(24, Math.ceil(hi / 60))];
  }, [events, ghost, tz]);
  const GRID_H = (END_HOUR - START_HOUR) * 60 * PX_PER_MIN;
  const top = (min: number) => Math.max(0, (min - START_HOUR * 60) * PX_PER_MIN);

  return (
    <div className="flex min-w-[880px] flex-col">
      {/* header */}
      <div className="sticky top-0 z-10 grid border-b border-border bg-surface" style={{ gridTemplateColumns: "56px repeat(7, minmax(0, 1fr))" }}>
        <div />
        {days.map((d) => {
          const key = localDateKey(d, tz);
          const p = zonedParts(d, tz);
          const evs = byDay.get(key) ?? [];
          const meetingMin = evs.filter((e) => e.kind === "meeting").reduce((s, e) => s + (Date.parse(e.end) - Date.parse(e.start)) / 60000, 0);
          const hol = holidays.find((h) => h.date === key);
          const isToday = key === todayKey;
          return (
            <div key={key} className="border-l border-border px-2 py-2">
              <div className="flex items-baseline gap-1.5">
                <span className="text-[11px] font-medium uppercase text-muted">{d.toLocaleDateString("en-US", { timeZone: tz, weekday: "short" })}</span>
                <span className={clsx("text-lg font-semibold", isToday && "grid h-7 w-7 place-items-center rounded-full bg-primary text-sm text-white")}>{p.day}</span>
              </div>
              <div className="mt-1 h-1 w-full rounded-full bg-slate-100" title={`${(meetingMin / 60).toFixed(1)}h of meetings`}>
                <div className={clsx("h-full rounded-full", meetingMin > 300 ? "bg-red-400" : meetingMin > 180 ? "bg-amber-400" : "bg-emerald-400")}
                  style={{ width: `${Math.min(100, (meetingMin / 480) * 100)}%` }} />
              </div>
              {hol && <div className="mt-1 truncate rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700" title={hol.name}>{hol.name} ({hol.country})</div>}
            </div>
          );
        })}
      </div>
      {/* body */}
      <div className="relative grid" style={{ gridTemplateColumns: "56px repeat(7, minmax(0, 1fr))", height: GRID_H }}>
        <div className="relative">
          {Array.from({ length: END_HOUR - START_HOUR }, (_, i) => (
            <div key={i} className="absolute right-2 -translate-y-1.5 text-[10px] text-muted" style={{ top: i * 60 * PX_PER_MIN }}>
              {i === 0 ? "" : `${((START_HOUR + i + 11) % 12) + 1} ${START_HOUR + i < 12 ? "AM" : "PM"}`}
            </div>
          ))}
        </div>
        {days.map((d) => {
          const key = localDateKey(d, tz);
          const weekend = zonedParts(d, tz).weekday >= 5 || holidays.some((h) => h.date === key);
          const evs = (byDay.get(key) ?? []).filter((e) => e.status !== "cancelled");
          const placed = layoutDay(evs.map((e) => ({ id: e.id, start: minutesIntoDay(new Date(e.start), tz), end: minutesIntoDay(new Date(e.start), tz) + (Date.parse(e.end) - Date.parse(e.start)) / 60000 })));
          const ghostHere = ghost && localDateKey(new Date(ghost.start), tz) === key;
          return (
            <div key={key} className={clsx("relative border-l border-border", weekend && "bg-slate-50/80")}>
              {Array.from({ length: END_HOUR - START_HOUR }, (_, i) => (
                <div key={i} className="absolute inset-x-0 border-t border-slate-100" style={{ top: i * 60 * PX_PER_MIN }} />
              ))}
              {!weekend && (
                <>
                  <div className="nonworking absolute inset-x-0 top-0" style={{ height: top(workStart) }} aria-hidden />
                  <div className="nonworking absolute inset-x-0 bottom-0" style={{ top: top(workEnd) }} aria-hidden />
                </>
              )}
              {evs.map((ev) => {
                const s = minutesIntoDay(new Date(ev.start), tz);
                const dur = (Date.parse(ev.end) - Date.parse(ev.start)) / 60000;
                const p = placed.get(ev.id)!;
                const h = Math.max(18, dur * PX_PER_MIN - 2);
                const conflict = ev.flags.length > 0;
                const focus = ev.kind === "focus" || ev.kind === "prep";
                return (
                  <button key={ev.id} onClick={() => onSelect(ev.id)} data-event-id={ev.id}
                    aria-label={`${ev.title}, ${fmtTime(ev.start, tz)} to ${fmtTime(ev.end, tz)}${conflict ? ", has a conflict" : ""}`}
                    className={clsx("absolute overflow-hidden rounded-md border px-1.5 py-0.5 text-left text-[11px] leading-tight shadow-sm transition hover:z-20 hover:shadow-md",
                      focus ? "focus-hatch border-emerald-300 text-emerald-900" : "bg-white",
                      conflict && "ring-2 ring-red-500",
                      ev.optional_for_me && "border-dashed opacity-80")}
                    style={{
                      top: top(s) + 1, height: h, left: `calc(${(p.col / p.cols) * 100}% + 2px)`, width: `calc(${100 / p.cols}% - 4px)`,
                      borderLeft: focus ? undefined : `3px solid ${ev.color}`, background: focus ? undefined : `${ev.color}14`,
                    }}>
                    <div className="flex items-center gap-1 font-semibold">
                      {conflict && <TriangleExclamationPoint className="h-3 w-3 shrink-0 text-red-600" aria-hidden />}
                      {focus && <Lock className="h-3 w-3 shrink-0" aria-hidden />}
                      {ev.ai_generated && <Sparkles className="h-3 w-3 shrink-0 text-ai" aria-hidden />}
                      <span className="truncate">{ev.title}</span>
                    </div>
                    {h > 30 && (
                      <div className="flex items-center gap-1 truncate text-[10px] text-slate-600">
                        {fmtTime(ev.start, tz)}
                        {!ev.is_virtual && ev.location && <MapPin className="h-2.5 w-2.5" aria-hidden />}
                        {ev.attendees.length > 2 && <><Users className="h-2.5 w-2.5" aria-hidden />{ev.attendees.length}</>}
                      </div>
                    )}
                  </button>
                );
              })}
              {ghostHere && ghost && (
                <div className="ghost-slot pointer-events-none absolute inset-x-1 z-20 rounded-md border-2 border-dashed border-violet-500 px-1.5 py-0.5 text-[11px] font-semibold text-violet-800"
                  style={{ top: top(minutesIntoDay(new Date(ghost.start), tz)), height: Math.max(18, ((Date.parse(ghost.end) - Date.parse(ghost.start)) / 60000) * PX_PER_MIN) }}>
                  <Sparkles className="mr-1 inline h-3 w-3" aria-hidden />{ghost.label ?? "Suggested"}
                </div>
              )}
              {key === todayKey && (
                <div className="pointer-events-none absolute inset-x-0 z-20 border-t-2 border-red-500" style={{ top: top(minutesIntoDay(now, tz)) }} aria-hidden>
                  <div className="-ml-1 -mt-[5px] h-2 w-2 rounded-full bg-red-500" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
