"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Car, CircleDollarSign, Clock, FileText, Lightbulb, MapPin, RefreshCw, Video } from "lucide-react";
import { useState } from "react";

import { DraftBox } from "@/components/ProposalView";
import { useUi } from "@/components/providers";
import { AiBadge, Badge, Button, Drawer, FeedbackThumbs, Spinner } from "@/components/ui";
import { api, track } from "@/lib/api";
import { fmtRange, fmtTime } from "@/lib/time";
import type { Brief, EventDetail, Me, Reminder } from "@/lib/types";

export function EventDrawer({ eventId, onClose, tz }: { eventId: string | null; onClose: () => void; tz: string }) {
  const { openDrawer, toast, refreshAll } = useUi();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const uid = me.data?.person.id;
  const detail = useQuery({ queryKey: ["event", eventId], enabled: !!eventId, queryFn: () => api.get<EventDetail>(`/api/events/${eventId}`) });
  const rem = useQuery({ queryKey: ["reminders", eventId], enabled: !!eventId, queryFn: () => api.get<{ reminders: Reminder[] }>(`/api/events/${eventId}/reminders`) });
  const brief = useQuery({ queryKey: ["brief", eventId], enabled: !!eventId && detail.data?.kind === "meeting",
    queryFn: () => api.get<{ brief: Brief; engine: string; cached: boolean }>(`/api/events/${eventId}/brief`) });
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  // Local, synchronous toggle state so the switch responds on click; the server is updated after.
  const [enabledOverride, setEnabledOverride] = useState<Record<string, boolean>>({});
  const ev = detail.data;

  async function toggle(r: Reminder) {
    const next = !(enabledOverride[r.kind] ?? r.enabled);
    setEnabledOverride((o) => ({ ...o, [r.kind]: next }));
    try {
      await api.patch(`/api/events/${eventId}/reminders/${r.kind}`, { enabled: next });
      qc.invalidateQueries({ queryKey: ["reminders", "upcoming"] });
    } catch (e) {
      setEnabledOverride((o) => ({ ...o, [r.kind]: !next }));
      toast(e instanceof Error ? e.message : "Could not update the reminder", { tone: "error" });
    }
  }

  async function runAction(r: Reminder) {
    if (!r.action) return;
    if (r.action.type === "block_prep" && r.action.operations) {
      const out = await api.post<{ audit_id: string; summary: string }>("/api/operations", { operations: r.action.operations, summary: `Blocked prep time for ${r.event_title}` });
      refreshAll();
      toast(out.summary, { auditId: out.audit_id });
    } else if (r.action.type === "draft" && r.action.draft) {
      setDraft(r.action.draft); // drafted server-side: addressed to the attendees, signed by the current user
    }
  }

  async function cancelOrDecline() {
    if (!ev || !uid) return;
    try {
      const out = ev.organizer_id === uid
        ? await api.del<{ audit_id: string }>(`/api/events/${ev.id}`)
        : await api.post<{ audit_id: string }>("/api/operations", { operations: [{ op: "respond", event_id: ev.id, person_id: uid, response: "declined" }], summary: `Declined ${ev.title}` });
      refreshAll();
      toast(ev.organizer_id === uid ? `Cancelled “${ev.title}”` : `Declined “${ev.title}”`, { auditId: out.audit_id });
      onClose();
    } catch (e) { toast(e instanceof Error ? e.message : "Failed", { tone: "error" }); }
  }

  return (
    <Drawer open={!!eventId} onClose={onClose} width="w-[480px]" title={ev?.title ?? "Meeting"}
      subtitle={ev ? fmtRange(ev.start, ev.end, tz) : undefined}>
      {!ev && <Spinner />}
      {ev && (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="indigo">{ev.category_label}</Badge>
            <Badge tone={ev.priority >= 75 ? "red" : ev.priority >= 50 ? "amber" : "slate"}>Priority {ev.priority}/100</Badge>
            {ev.is_virtual ? <Badge><Video className="h-3 w-3" />Video call</Badge> : <Badge tone="sky"><MapPin className="h-3 w-3" />{ev.location}</Badge>}
            {ev.series && <Badge><Clock className="h-3 w-3" />{ev.series.cadence}</Badge>}
            {ev.ai_generated && <Badge tone="violet">Created with Kairos</Badge>}
          </div>
          {ev.flags.length > 0 && <p className="rounded-lg bg-red-50 p-2 text-xs text-red-700">Conflict: {ev.flags.join(", ")} — <button className="underline" onClick={() => openDrawer({ type: "conflicts" })}>resolve</button></p>}
          {ev.description && <p className="text-sm text-slate-700">{ev.description}</p>}

          <section>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">People · their local time</h3>
            <ul className="space-y-1">
              {ev.attendees.map((a) => (
                <li key={a.person_id} className="flex items-center justify-between text-xs">
                  <span><b>{a.name}</b> <span className="text-muted">{a.title}{a.is_external ? `, ${a.company}` : ""}{a.organizer ? " · organizer" : ""}{a.optional ? " · optional" : ""}</span></span>
                  <span className="text-muted">{fmtTime(ev.start, a.timezone)} {a.response !== "accepted" && <Badge tone="amber">{a.response}</Badge>}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-slate-50 p-2.5 text-xs"><CircleDollarSign className="mb-1 h-4 w-4 text-slate-500" />Meeting cost <b className="block text-base">${ev.cost.toLocaleString()}</b><span className="text-muted">attendee time at loaded rates</span></div>
            <div className="rounded-lg bg-slate-50 p-2.5 text-xs">Why priority {ev.priority}
              <ul className="mt-1 space-y-0.5 text-[11px]">{ev.priority_factors.map((f) => <li key={f.label}>{f.points > 0 ? "+" : ""}{f.points} {f.label}</li>)}</ul></div>
          </section>
          {ev.necessity_tip && <p className="flex gap-2 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900"><Lightbulb className="h-4 w-4 shrink-0" />{ev.necessity_tip}</p>}

          {ev.kind === "meeting" && (
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted"><Bell className="h-3.5 w-3.5" />Smart reminders</h3>
              <ul className="space-y-2">
                {(rem.data?.reminders ?? []).map((r) => (
                  <li key={r.id} className="rounded-lg border border-border p-2.5">
                    <div className="flex items-start gap-2">
                      {r.kind === "leave" ? <Car className="mt-0.5 h-4 w-4 text-sky-600" /> : <Bell className="mt-0.5 h-4 w-4 text-indigo-600" />}
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold">{r.suppressed ? r.title : `${fmtTime(r.fire_at, tz)} · ${r.title}`}</div>
                        <div className="text-[11px] text-muted">{r.rationale}</div>
                        {r.action && (enabledOverride[r.kind] ?? r.enabled) && <Button size="sm" className="mt-1.5" onClick={() => runAction(r)}>{r.action.label}</Button>}
                      </div>
                      <label className="flex items-center gap-1 text-[11px]">
                        <input type="checkbox" checked={enabledOverride[r.kind] ?? r.enabled} onChange={() => { toggle(r); track("reminder_toggle_ui", { kind: r.kind }); }} aria-label={`${r.kind} reminder`} />on
                      </label>
                    </div>
                  </li>
                ))}
              </ul>
              {draft && <DraftBox draft={draft} />}
            </section>
          )}

          {ev.kind === "meeting" && (
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted"><FileText className="h-3.5 w-3.5" />Meeting brief</h3>
                <div className="flex items-center gap-2">
                  {brief.data && <AiBadge engine={brief.data.engine} />}
                  <Button size="sm" variant="ghost" aria-label="Regenerate brief" onClick={async () => { await api.get(`/api/events/${eventId}/brief?refresh=true`); qc.invalidateQueries({ queryKey: ["brief", eventId] }); }}><RefreshCw className="h-3.5 w-3.5" /></Button>
                </div>
              </div>
              {brief.isPending && <Spinner label="Preparing brief" />}
              {brief.data && (
                <div className="space-y-2 rounded-xl bg-slate-50 p-3 text-xs">
                  <p className="font-medium">{brief.data.brief.purpose}</p>
                  <ul className="list-disc space-y-0.5 pl-4 text-slate-700">{brief.data.brief.context.map((c) => <li key={c}>{c}</li>)}</ul>
                  <div><b>Agenda</b><ol className="mt-0.5 list-decimal pl-4">{brief.data.brief.agenda.map((a) => <li key={a.item}>{a.item} — {a.minutes} min</li>)}</ol></div>
                  <div><b>Talking points</b><ul className="mt-0.5 list-disc pl-4">{brief.data.brief.talking_points.map((t) => <li key={t}>{t}</li>)}</ul></div>
                  <div><b>Prep</b><ul className="mt-0.5 list-disc pl-4">{brief.data.brief.prep_checklist.map((t) => <li key={t}>{t}</li>)}</ul></div>
                  <div><b>Watch-outs</b><ul className="mt-0.5 list-disc pl-4">{brief.data.brief.watch_outs.map((t) => <li key={t}>{t}</li>)}</ul></div>
                  <div className="flex justify-end"><FeedbackThumbs targetType="brief" targetId={ev.id} /></div>
                </div>
              )}
            </section>
          )}

          <div className="flex gap-2 border-t border-border pt-4">
            {ev.kind === "meeting" && (ev.organizer_id === uid ? ev.is_movable : true) && (
              <Button onClick={() => openDrawer({ type: "schedule", prefill: { event_id: ev.id, title: ev.title, duration_min: Math.round((Date.parse(ev.end) - Date.parse(ev.start)) / 60000), attendee_ids: ev.attendees.filter((a) => a.person_id !== uid).map((a) => a.person_id) } })}>Reschedule</Button>
            )}
            <Button variant="danger" onClick={cancelOrDecline}>{ev.organizer_id === uid ? "Cancel meeting" : "Decline"}</Button>
          </div>
        </div>
      )}
    </Drawer>
  );
}
