"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Sparkles, TriangleExclamationPoint } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ProposalView } from "@/components/ProposalView";
import { useUi } from "@/components/providers";
import { SlotCard } from "@/components/SlotCard";
import { AiBadge, Badge, Button, Card, Modal, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { CommandResult, Slot } from "@/lib/types";

const EXAMPLES = [
  "Find 45 min with Dev and Alex next week, mornings",
  "Find 45 min with Priya and Alex next week",
  "What conflicts do I have?",
  "How much time did I spend in meetings last week?",
  "Brief me on the Brightwave QBR",
  "Block 2 hours for the FY27 strategy before Friday",
];

export function CommandBar() {
  const { commandOpen, setCommandOpen, toast, refreshAll, openDrawer, setGhost } = useUi();
  const router = useRouter();
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const run = useMutation({ mutationFn: (t: string) => api.post<CommandResult>("/api/assistant/command", { text: t }) });
  const [booking, setBooking] = useState(false);

  useEffect(() => {
    if (commandOpen) window.setTimeout(() => inputRef.current?.focus(), 10);
    else setGhost(null);
  }, [commandOpen, setGhost]);

  const close = () => setCommandOpen(false);
  const submit = (t: string) => { if (t.trim()) run.mutate(t.trim()); };
  const data = run.data;

  async function book(slot: Slot) {
    if (!data || data.result.type !== "slots") return;
    const r = data.result;
    setBooking(true);
    try {
      const res = await api.post<{ audit_id: string; summary: string }>("/api/schedule/book", {
        title: r.title, start: slot.start, end: slot.end, attendee_ids: r.request.attendee_ids, optional_ids: r.request.optional_ids,
        mode: r.mode, event_id: r.mode === "reschedule" ? r.event?.id : undefined, chosen_rank: slot.rank,
        chosen_components: slot.components, shown_components: r.slots.map((s) => s.components),
      });
      refreshAll();
      toast(`${res.summary} for ${slot.label}`, { auditId: res.audit_id });
      close();
      run.reset();
      setText("");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Booking failed", { tone: "error" });
    } finally { setBooking(false); }
  }

  return (
    <Modal open={commandOpen} onClose={close} label="Ask Kairos">
      <Card className="overflow-hidden">
        <form className="flex items-center gap-3 border-b border-border px-4 py-3" onSubmit={(e) => { e.preventDefault(); submit(text); }}>
          <Sparkles className="h-5 w-5 text-ai" aria-hidden />
          <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} aria-label="Ask Kairos"
            placeholder="e.g. Find 45 min with Priya and Alex next week, mornings"
            className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-slate-400" />
          <Button type="submit" variant="ai" size="sm" disabled={run.isPending}>Ask <ArrowRight className="h-3.5 w-3.5" /></Button>
        </form>
        <div className="max-h-[65vh] overflow-y-auto p-4">
          {run.isPending && <Spinner label="Thinking" />}
          {run.isError && <p className="text-sm text-red-600">{(run.error as Error).message}</p>}
          {!data && !run.isPending && (
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Try</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((ex) => (
                  <button key={ex} className="rounded-full border border-border px-3 py-1 text-xs hover:bg-slate-50" onClick={() => { setText(ex); submit(ex); }}>{ex}</button>
                ))}
              </div>
            </div>
          )}
          {data && !run.isPending && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <AiBadge engine={data.engine.engine} model={data.engine.model} />
                {data.chips.map((c) => <Badge key={c.label + c.value} tone="indigo">{c.label}: {c.value}</Badge>)}
                {data.engine.fallback_reason && data.engine.engine === "offline" && (
                  <span className="text-[11px] text-muted" title={data.engine.fallback_reason}>· {data.engine.fallback_reason}</span>
                )}
              </div>
              {data.unknown_people.length > 0 && (
                <p className="flex items-center gap-1.5 text-xs text-amber-700"><TriangleExclamationPoint className="h-3.5 w-3.5" />Couldn&apos;t find: {data.unknown_people.join(", ")}</p>
              )}
              <Result data={data} book={book} booking={booking} onExample={(ex) => { setText(ex); submit(ex); }}
                go={(path) => { close(); router.push(path); }}
                openDrawer={(d) => { close(); router.push("/"); openDrawer(d); }} setGhost={setGhost} />
            </div>
          )}
        </div>
      </Card>
    </Modal>
  );
}

function Result({ data, book, booking, onExample, go, openDrawer, setGhost }: {
  data: CommandResult; book: (s: Slot) => void; booking: boolean; onExample: (s: string) => void; go: (p: string) => void;
  openDrawer: (d: Parameters<ReturnType<typeof useUi>["openDrawer"]>[0]) => void; setGhost: ReturnType<typeof useUi>["setGhost"];
}) {
  const r = data.result;
  switch (r.type) {
    case "slots":
      return (
        <div className="space-y-2">
          <p className="text-sm">{r.mode === "reschedule" ? <>New times for <b>{r.title}</b></> : <>Best times for <b>{r.title}</b></>}
            <span className="ml-2 text-[11px] text-muted">{r.stats.feasible} feasible of {r.stats.candidates} checked in {r.stats.elapsed_ms} ms</span></p>
          {r.slots.map((s) => <SlotCard key={s.start} slot={s} onBook={() => book(s)} busy={booking} onHover={(x) => setGhost(x ? { start: x.start, end: x.end, label: x.label } : null)} />)}
          {r.slots.length === 0 && <p className="text-sm text-amber-700">No time works for everyone within working hours.</p>}
          {r.relaxations.map((x) => (
            <div key={x.kind} className="rounded-lg border border-dashed border-violet-300 bg-violet-50/50 p-3 text-xs">
              <b>{x.label}</b> — {x.description} <span className="text-muted">({x.slot_count} options, e.g. {x.preview})</span>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => openDrawer({ type: "schedule", prefill: { attendee_ids: r.request.attendee_ids, duration_min: r.request.duration_min, title: r.title, event_id: r.mode === "reschedule" ? r.event?.id : undefined } })}>
            Refine in the schedule assistant →
          </Button>
        </div>
      );
    case "conflicts":
      return (
        <div className="space-y-2">
          <p className="text-sm">{r.conflicts.length} conflict{r.conflicts.length === 1 ? "" : "s"} in the next two weeks.</p>
          {r.conflicts.slice(0, 5).map((c) => (
            <div key={c.id} className="rounded-lg border border-border p-2 text-sm"><Badge tone={c.severity === "high" ? "red" : c.severity === "medium" ? "amber" : "slate"}>{c.severity}</Badge> <b>{c.title}</b>
              <div className="text-xs text-muted">{c.description} Suggested: {c.options[0]?.label}</div></div>
          ))}
          <Button size="sm" variant="primary" onClick={() => openDrawer({ type: "conflicts" })}>Open conflict center</Button>
        </div>
      );
    case "analytics":
      return (
        <div className="space-y-2">
          <p className="text-sm">{r.headline}</p>
          <div className="flex flex-wrap gap-2">{r.kpis.slice(0, 4).map((k) => <Badge key={k.id}>{k.label}: {k.unit === "$" ? `$${k.value.toLocaleString()}` : `${k.value}${k.unit}`}</Badge>)}</div>
          <Button size="sm" variant="primary" onClick={() => go("/insights")}>Open insights</Button>
        </div>
      );
    case "brief":
      return (
        <div className="space-y-2 text-sm">
          <p className="font-semibold">{r.event.title}</p>
          <p>{r.brief.purpose}</p>
          <ol className="list-decimal pl-5 text-xs">{r.brief.agenda.map((a) => <li key={a.item}>{a.item} ({a.minutes} min)</li>)}</ol>
          <Button size="sm" onClick={() => openDrawer({ type: "event", eventId: r.event.id })}>Open meeting</Button>
        </div>
      );
    case "proposal":
      return <ProposalView proposal={r.proposal} onDone={() => go("/")} />;
    case "reminder":
      return <p className="text-sm text-emerald-700">{r.message}</p>;
    case "clarify":
      return <p className="text-sm text-amber-800">{r.message}</p>;
    case "help":
      return (
        <div className="space-y-2">
          <p className="text-sm">{r.message}</p>
          <div className="flex flex-wrap gap-2">{r.examples.map((ex) => <button key={ex} className="rounded-full border border-border px-3 py-1 text-xs hover:bg-slate-50" onClick={() => onExample(ex)}>{ex}</button>)}</div>
        </div>
      );
  }
}
