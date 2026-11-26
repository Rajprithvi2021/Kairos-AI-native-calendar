"use client";

import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { Undo2, X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";

let browserClient: QueryClient | undefined;

function getClient() {
  if (typeof window === "undefined") return new QueryClient({ defaultOptions: { queries: { retry: 1 } } });
  browserClient ??= new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
  return browserClient;
}

// --- Toasts with one-click undo -----------------------------------------------------------------
type Toast = { id: number; message: string; tone: "ok" | "error" | "info"; auditId?: string };

// --- Cross-page UI requests (command bar, calendar drawers) ---------------------------------------
export type DrawerRequest =
  | { type: "schedule"; prefill?: { attendee_ids?: string[]; duration_min?: number; title?: string; event_id?: string } }
  | { type: "conflicts"; conflictId?: string }
  | { type: "event"; eventId: string }
  | { type: "proposal"; proposal: Proposal; draft?: { subject: string; body: string } | null };

type UiContext = {
  toast: (message: string, opts?: { tone?: Toast["tone"]; auditId?: string }) => void;
  commandOpen: boolean;
  setCommandOpen: (v: boolean) => void;
  drawer: DrawerRequest | null;
  openDrawer: (d: DrawerRequest | null) => void;
  refreshAll: () => void;
  ghost: { start: string; end: string; label?: string } | null;
  setGhost: (g: { start: string; end: string; label?: string } | null) => void;
};

const Ctx = createContext<UiContext | null>(null);

export function useUi(): UiContext {
  const c = useContext(Ctx);
  if (!c) throw new Error("useUi must be used inside <Providers>");
  return c;
}

function UiProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [commandOpen, setCommandOpen] = useState(false);
  const [drawer, openDrawer] = useState<DrawerRequest | null>(null);
  const [ghost, setGhost] = useState<UiContext["ghost"]>(null);

  const refreshAll = useCallback(() => {
    for (const key of ["events", "conflicts", "insights", "reminders", "analytics", "forecast", "recurring", "event", "brief", "digest", "proposals", "me", "ai-status", "metrics", "audit"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  }, [qc]);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const toast = useCallback<UiContext["toast"]>((message, opts) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, message, tone: opts?.tone ?? "ok", auditId: opts?.auditId }]);
    window.setTimeout(() => dismiss(id), opts?.auditId ? 12000 : 6000);
  }, [dismiss]);

  const undo = useCallback(async (t: Toast) => {
    if (!t.auditId) return;
    dismiss(t.id);
    try {
      await api.post(`/api/audit/${t.auditId}/undo`);
      refreshAll();
      toast("Undone — your calendar is back as it was.", { tone: "info" });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Undo failed", { tone: "error" });
    }
  }, [dismiss, refreshAll, toast]);

  const value = useMemo(() => ({ toast, commandOpen, setCommandOpen, drawer, openDrawer, refreshAll, ghost, setGhost }),
    [toast, commandOpen, drawer, refreshAll, ghost]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`pointer-events-auto flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm text-white shadow-lg ${t.tone === "error" ? "bg-red-600" : t.tone === "info" ? "bg-slate-700" : "bg-slate-900"}`}>
            <span>{t.message}</span>
            {t.auditId && (
              <button className="inline-flex items-center gap-1 rounded-md bg-white/15 px-2 py-0.5 font-medium hover:bg-white/25" onClick={() => undo(t)}>
                <Undo2 className="h-3.5 w-3.5" /> Undo
              </button>
            )}
            <button aria-label="Dismiss" className="opacity-70 hover:opacity-100" onClick={() => dismiss(t.id)}><X className="h-3.5 w-3.5" /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={getClient()}>
      <UiProvider>{children}</UiProvider>
    </QueryClientProvider>
  );
}
