"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Wand2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { useUi } from "@/components/providers";
import { SlotCard } from "@/components/SlotCard";
import { Badge, Button, Drawer, Field, inputCls, Segmented, Spinner } from "@/components/ui";
import { api, track } from "@/lib/api";
import { addLocalDays, weekStart } from "@/lib/time";
import type { Me, Person, Slot, SlotResult } from "@/lib/types";

type Prefill = { attendee_ids?: string[]; duration_min?: number; title?: string; event_id?: string };
type WindowKey = "7d" | "this" | "next" | "2w";

export function ScheduleDrawer({ open, prefill, onClose, tz, now }: { open: boolean; prefill?: Prefill; onClose: () => void; tz: string; now: Date }) {
  const { toast, refreshAll, setGhost } = useUi();
  const people = useQuery({ queryKey: ["people"], queryFn: () => api.get<Person[]>("/api/people") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const uid = me.data?.person.id;
  const [attendees, setAttendees] = useState<string[]>(prefill?.attendee_ids ?? []);
  const [optional, setOptional] = useState<string[]>([]);
  const [duration, setDuration] = useState(prefill?.duration_min ?? 30);
  const [windowKey, setWindowKey] = useState<WindowKey>(prefill?.event_id ? "7d" : "next");
  const [period, setPeriod] = useState<"any" | "morning" | "afternoon">("any");
  const [respectFocus, setRespectFocus] = useState(true);
  const [title, setTitle] = useState(prefill?.title ?? "");
  const [agenda, setAgenda] = useState("");
  const [patch, setPatch] = useState<Record<string, unknown>>({});
  const [booking, setBooking] = useState(false);
  const reschedule = Boolean(prefill?.event_id);

  const byId = useMemo(() => new Map((people.data ?? []).map((p) => [p.id, p])), [people.data]);
  const candidates = (people.data ?? []).filter((p) => p.id !== uid && !attendees.includes(p.id) && !optional.includes(p.id));

  const window = useMemo(() => {
    if (windowKey === "this") return [now, weekStart(now, tz, 1)];
    if (windowKey === "next") { const s = weekStart(now, tz, 1); return [s, addLocalDays(s, 5, tz)]; }
    return [now, new Date(now.getTime() + (windowKey === "2w" ? 14 : 7) * 86400000)];
  }, [windowKey, now, tz]);

  const suggest = useMutation({
    mutationFn: (extra: Record<string, unknown>) => api.post<SlotResult>("/api/schedule/suggest", {
      attendee_ids: attendees, optional_ids: optional, duration_min: duration, window_start: window[0].toISOString(),
      window_end: window[1].toISOString(), preferred_period: period, respect_focus: respectFocus, exclude_event_id: prefill?.event_id ?? null,
      ...extra,
    }),
  });

  async function book(slot: Slot) {
    const res = suggest.data;
    if (!res) return;
    setBooking(true);
    try {
      const out = await api.post<{ audit_id: string; summary: string; learned: { label: string; delta: number }[] | null }>("/api/schedule/book", {
        title: title || `Sync: ${attendees.map((a) => byId.get(a)?.first_name).join(" / ")}`, start: slot.start, end: slot.end,
        attendee_ids: attendees, optional_ids: optional, agenda, mode: reschedule ? "reschedule" : "new", event_id: prefill?.event_id,
        chosen_rank: slot.rank, chosen_components: slot.components, shown_components: res.slots.map((s) => s.components),
      });
      refreshAll();
      setGhost(null);
      const learned = out.learned?.find((l) => Math.abs(l.delta) >= 0.005);
      toast(`${out.summary} · ${slot.label}${learned ? ` · learned: ${learned.label} ${learned.delta > 0 ? "↑" : "↓"}` : ""}`, { auditId: out.audit_id });
      onClose();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Booking failed", { tone: "error" });
    } finally { setBooking(false); }
  }

  return (
    <Drawer open={open} onClose={() => { setGhost(null); onClose(); }} width="w-[480px]"
      title={reschedule ? "Reschedule meeting" : "Schedule assistant"}
      subtitle="Kairos checks everyone's working hours, time zones, focus time and load, then explains each option.">
      <div className="space-y-4">
        {!reschedule && (
          <>
            <Field label="Title"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Renewal strategy sync" /></Field>
            <Field label="Who" hint="Required attendees. Kairos uses their working hours and time zones.">
              <div className="flex flex-wrap gap-1.5">
                {attendees.map((id) => (
                  <Badge key={id} tone="indigo">{byId.get(id)?.name ?? id} <span className="text-indigo-400">· {byId.get(id)?.city}</span>
                    <button aria-label={`Remove ${byId.get(id)?.name}`} onClick={() => setAttendees(attendees.filter((a) => a !== id))}><X className="h-3 w-3" /></button></Badge>
                ))}
                {optional.map((id) => (
                  <Badge key={id} tone="slate">{byId.get(id)?.name} (optional)
                    <button aria-label={`Remove ${byId.get(id)?.name}`} onClick={() => setOptional(optional.filter((a) => a !== id))}><X className="h-3 w-3" /></button></Badge>
                ))}
              </div>
              <div className="mt-2 flex gap-2">
                <select className={inputCls} aria-label="Add attendee" value="" onChange={(e) => e.target.value && setAttendees([...attendees, e.target.value])}>
                  <option value="">+ Add attendee…</option>
                  {candidates.map((p) => <option key={p.id} value={p.id}>{p.name} — {p.title}{p.is_external ? ` (${p.company})` : ""}, {p.city}</option>)}
                </select>
                <select className={inputCls} aria-label="Add optional attendee" value="" onChange={(e) => e.target.value && setOptional([...optional, e.target.value])}>
                  <option value="">+ Optional…</option>
                  {candidates.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
            </Field>
          </>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Length">
            <select className={inputCls} value={duration} onChange={(e) => setDuration(Number(e.target.value))} disabled={reschedule}>
              {[15, 25, 30, 45, 50, 60, 90].map((d) => <option key={d} value={d}>{d} min</option>)}
            </select>
          </Field>
          <Field label="When">
            <select className={inputCls} value={windowKey} onChange={(e) => setWindowKey(e.target.value as WindowKey)}>
              <option value="7d">Next 7 days</option><option value="this">Rest of this week</option>
              <option value="next">Next week</option><option value="2w">Next 2 weeks</option>
            </select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Segmented label="Time of day" value={period} onChange={setPeriod} options={[{ value: "any", label: "Any time" }, { value: "morning", label: "Morning" }, { value: "afternoon", label: "Afternoon" }]} />
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={respectFocus} onChange={(e) => setRespectFocus(e.target.checked)} /> Respect my focus time</label>
        </div>
        <Button variant="primary" className="w-full" disabled={(!reschedule && attendees.length === 0) || suggest.isPending}
          onClick={() => { setPatch({}); suggest.mutate({}); track("schedule_assistant_search", { attendees: attendees.length }); }}>
          Find the best times
        </Button>

        {suggest.isPending && <Spinner label="Searching" />}
        {suggest.isError && <p className="text-sm text-red-600">{(suggest.error as Error).message}</p>}
        {suggest.data && (
          <div className="space-y-2">
            <p className="text-[11px] text-muted">{suggest.data.stats.feasible} feasible of {suggest.data.stats.candidates} candidate times checked in {suggest.data.stats.elapsed_ms} ms{Object.keys(patch).length ? " (relaxed)" : ""}.</p>
            {suggest.data.slots.map((s) => (
              <SlotCard key={s.start} slot={s} busy={booking} onBook={() => book(s)} onHover={(x) => setGhost(x ? { start: x.start, end: x.end, label: x.label } : null)} />
            ))}
            {suggest.data.slots.length === 0 && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">No time works for everyone inside working hours. Here&apos;s what would have to give:</p>}
            {suggest.data.relaxations.map((r) => (
              <button key={r.kind} className="block w-full rounded-xl border border-dashed border-violet-300 bg-violet-50/50 p-3 text-left text-xs hover:bg-violet-50"
                onClick={() => { setPatch(r.patch); suggest.mutate(r.patch); track("relaxation_applied", { kind: r.kind }); }}>
                <span className="font-semibold text-violet-800">{r.label}</span> · {r.slot_count} option(s), e.g. {r.preview}
                <span className="mt-0.5 block text-muted">{r.description}</span>
              </button>
            ))}
            {suggest.data.slots.length > 0 && (
              <Field label="Agenda (sent with the invite)">
                <textarea className={`${inputCls} h-24 text-xs`} value={agenda} onChange={(e) => setAgenda(e.target.value)} />
                <Button size="sm" variant="ghost" onClick={() => setAgenda(`Goal: ${title || "align on next steps"}\n1. Context and goal (${Math.round(duration * 0.2)} min)\n2. Discussion (${Math.round(duration * 0.6)} min)\n3. Decisions, owners and dates (${Math.round(duration * 0.2)} min)`)}>
                  <Wand2 className="h-3.5 w-3.5" /> Draft agenda
                </Button>
              </Field>
            )}
          </div>
        )}
      </div>
    </Drawer>
  );
}
