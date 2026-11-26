"use client";

import { clsx } from "clsx";
import { LoaderCircle, Sparkles, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef, useState } from "react";

import { sendFeedback } from "@/lib/api";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "ai";

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      {...props}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variant === "primary" && "bg-primary text-white shadow-sm hover:bg-indigo-700",
        variant === "secondary" && "border border-border bg-white text-ink hover:bg-slate-50",
        variant === "ghost" && "text-muted hover:bg-slate-100 hover:text-ink",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-700",
        variant === "ai" && "bg-ai text-white shadow-sm hover:bg-violet-700",
        className,
      )}
    />
  );
}

export function Badge({ tone = "slate", children, className }: { tone?: "slate" | "red" | "amber" | "green" | "violet" | "indigo" | "sky"; children: ReactNode; className?: string }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    red: "bg-red-50 text-red-700 ring-1 ring-red-200",
    amber: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    green: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    violet: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
    indigo: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
    sky: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
  };
  return <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone], className)}>{children}</span>;
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-xl border border-border bg-surface shadow-sm", className)}>{children}</div>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted" role="status">
      <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> {label}…
    </span>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">{msg || "Something went wrong."} Is the API running on port 8000?</p>;
}

export const ENGINE_LABEL: Record<string, string> = { claude: "Claude", gemini: "Gemini" };

export function AiBadge({ engine, model }: { engine?: string; model?: string | null }) {
  const llm = engine ? ENGINE_LABEL[engine] : undefined;
  return (
    <Badge tone={llm ? "violet" : "slate"}>
      <Sparkles className="h-3 w-3" aria-hidden />
      {llm ? `${llm}${model ? ` · ${model}` : ""}` : engine === "template" ? "Template (offline)" : "Offline engine"}
    </Badge>
  );
}

export function ScoreBar({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100" aria-label={`score ${Math.round(value)} of ${max}`}>
      <div className={clsx("h-full rounded-full", pct >= 75 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500")} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Drawer({ open, title, subtitle, onClose, children, width = "w-[440px]" }: { open: boolean; title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; width?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <aside
      ref={ref}
      tabIndex={-1}
      role="dialog"
      aria-modal="false"
      aria-label={typeof title === "string" ? title : undefined}
      className={clsx("animate-slide-in fixed right-0 top-0 z-30 flex h-full max-w-full flex-col border-l border-border bg-surface shadow-2xl outline-none", width)}
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
        <div>
          <h2 className="text-base font-semibold">{title}</h2>
          {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close panel"><X className="h-4 w-4" /></Button>
      </header>
      <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
    </aside>
  );
}

export function Modal({ open, onClose, children, label }: { open: boolean; onClose: () => void; children: ReactNode; label: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-slate-900/40 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={label} className="w-full max-w-2xl" onMouseDown={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

const DOWN_REASONS = ["Wrong time", "Wrong people", "Not useful", "Too pushy"];

export function FeedbackThumbs({ targetType, targetId }: { targetType: string; targetId: string }) {
  const [state, setState] = useState<"none" | "up" | "down" | "asking">("none");
  if (state === "up" || state === "down") return <span className="text-[11px] text-muted">Thanks — saved for the product team.</span>;
  if (state === "asking")
    return (
      <span className="flex flex-wrap gap-1">
        {DOWN_REASONS.map((r) => (
          <button key={r} className="rounded-full border border-border px-2 py-0.5 text-[11px] hover:bg-slate-50"
            onClick={() => { sendFeedback(targetType, targetId, -1, [r]); setState("down"); }}>{r}</button>
        ))}
      </span>
    );
  return (
    <span className="flex items-center gap-1">
      <button aria-label="Helpful" className="rounded p-1 text-muted hover:bg-slate-100 hover:text-emerald-600"
        onClick={() => { sendFeedback(targetType, targetId, 1); setState("up"); }}><ThumbsUp className="h-3.5 w-3.5" /></button>
      <button aria-label="Not helpful" className="rounded p-1 text-muted hover:bg-slate-100 hover:text-red-600"
        onClick={() => setState("asking")}><ThumbsDown className="h-3.5 w-3.5" /></button>
    </span>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-border bg-slate-50 p-0.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={clsx("rounded-md px-2.5 py-1 text-xs font-medium", value === o.value ? "bg-white text-ink shadow-sm" : "text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-border bg-white px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-indigo-100";
