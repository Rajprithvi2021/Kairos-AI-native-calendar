"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Copy, Plus, Sparkles, Trash2, UserX } from "lucide-react";
import { useState } from "react";

import { useUi } from "@/components/providers";
import { AiBadge, Button, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtRange } from "@/lib/time";
import type { Me, Operation, Proposal } from "@/lib/types";

function describe(op: Operation, tz: string): { icon: typeof Plus; text: string } {
  const ev = op.event as Record<string, string> | undefined;
  const ch = op.changes as Record<string, string> | undefined;
  if (op.op === "create" && ev) return { icon: Plus, text: `Create “${ev.title}” · ${fmtRange(ev.start, ev.end, tz)}` };
  if (op.op === "update" && ch?.start) return { icon: CalendarClock, text: `Move ${String(op.event_id).replace(/^plant_/, "")} → ${fmtRange(ch.start, ch.end, tz)}` };
  if (op.op === "update" && ch?.end) return { icon: CalendarClock, text: `Shorten ${String(op.event_id)} to end ${fmtRange(ch.end, ch.end, tz).split("·")[1]}` };
  if (op.op === "respond") return { icon: UserX, text: `Respond “${String(op.response)}” to ${String(op.event_id)}` };
  if (op.op === "delete") return { icon: Trash2, text: `Cancel ${String(op.event_id)}` };
  return { icon: CalendarClock, text: `${op.op} ${String(op.event_id ?? "")}` };
}

export function DraftBox({ draft }: { draft: { subject: string; body: string } }) {
  const { toast } = useUi();
  const [text, setText] = useState(draft);
  const [engine, setEngine] = useState<string>("template");
  const [busy, setBusy] = useState(false);
  return (
    <div className="mt-3 rounded-xl border border-violet-200 bg-violet-50/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-violet-800">Message draft</span>
        <AiBadge engine={engine} />
      </div>
      <input className={inputCls} value={text.subject} onChange={(e) => setText({ ...text, subject: e.target.value })} aria-label="Subject" />
      <textarea className={`${inputCls} mt-2 h-40 font-mono text-xs`} value={text.body} onChange={(e) => setText({ ...text, body: e.target.value })} aria-label="Message body" />
      <div className="mt-2 flex gap-2">
        <Button size="sm" onClick={() => { navigator.clipboard?.writeText(`${text.subject}\n\n${text.body}`); toast("Draft copied — Kairos never sends messages without you."); }}>
          <Copy className="h-3.5 w-3.5" /> Copy
        </Button>
        <Button size="sm" variant="ai" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            const r = await api.post<{ subject: string; body: string; engine: string; note?: string }>("/api/ai/draft", text);
            setText({ subject: r.subject, body: r.body });
            setEngine(r.engine);
            if (r.engine !== "claude") toast(r.note ?? "Claude isn't configured — kept the template (add a key in services/api/.env).", { tone: "info" });
          } finally { setBusy(false); }
        }}><Sparkles className="h-3.5 w-3.5" /> Polish with AI</Button>
      </div>
    </div>
  );
}

export function ProposalView({ proposal, draft, onDone }: { proposal: Proposal; draft?: { subject: string; body: string } | null; onDone: () => void }) {
  const { toast, refreshAll } = useUi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const tz = me.data?.person.timezone ?? "America/Los_Angeles";
  const [busy, setBusy] = useState(false);
  const exp = proposal.explanation as { draft?: { subject: string; body: string }; reasons?: string[]; moves?: { title: string; from: string; to: string; gain_min: number }[] };
  const theDraft = draft ?? exp?.draft ?? null;
  return (
    <div>
      <p className="text-sm text-slate-700">{proposal.summary}</p>
      {exp?.moves && exp.moves.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {exp.moves.map((m) => (
            <li key={m.title + m.to} className="rounded-lg bg-slate-50 px-3 py-2 text-xs">
              <b>{m.title}</b>: {m.from} → {m.to} <span className="text-emerald-700">(+{m.gain_min} min deep work)</span>
            </li>
          ))}
        </ul>
      )}
      <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Changes ({proposal.operations.length})</h4>
      <ul className="mt-2 max-h-60 space-y-1 overflow-y-auto">
        {proposal.operations.map((op, i) => {
          const d = describe(op, tz);
          return <li key={i} className="flex items-start gap-2 text-xs text-slate-700"><d.icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600" />{d.text}</li>;
        })}
      </ul>
      {theDraft && <DraftBox draft={theDraft} />}
      <div className="mt-4 flex gap-2">
        <Button variant="primary" disabled={busy || proposal.status !== "pending"} onClick={async () => {
          setBusy(true);
          try {
            const r = await api.post<{ audit_id: string; summary: string }>(`/api/proposals/${proposal.id}/apply`);
            refreshAll();
            toast(`${r.summary} — applied.`, { auditId: r.audit_id });
            onDone();
          } catch (e) { toast(e instanceof Error ? e.message : "Failed", { tone: "error" }); } finally { setBusy(false); }
        }}>Apply changes</Button>
        <Button disabled={busy} onClick={async () => { await api.post(`/api/proposals/${proposal.id}/discard`); onDone(); }}>Discard</Button>
      </div>
      <p className="mt-3 text-[11px] text-muted">Nothing changes until you apply. Every change is audited and can be undone.</p>
    </div>
  );
}
