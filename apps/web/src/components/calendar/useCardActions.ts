"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { useUi } from "@/components/providers";
import { api, track } from "@/lib/api";
import type { CardAction, Proposal } from "@/lib/types";

type FocusResp = { proposal: Proposal | null; applied?: boolean; audit_id?: string; plan: { added_hours?: number; moves?: unknown[] } };

export function useCardActions() {
  const { openDrawer, toast, refreshAll } = useUi();
  const router = useRouter();

  return useCallback(async (a: CardAction) => {
    track("card_action", { type: a.type });
    try {
      switch (a.type) {
        case "open_conflict":
          openDrawer({ type: "conflicts", conflictId: a.conflict_id });
          return;
        case "open_event":
          if (a.event_id) openDrawer({ type: "event", eventId: a.event_id });
          return;
        case "navigate":
          if (a.to) router.push(a.to);
          return;
        case "focus_plan": {
          const r = await api.post<FocusResp>("/api/focus/protect", { week_start: a.week_start });
          if (r.applied) { refreshAll(); toast(`Protected ${r.plan.added_hours}h of focus (autonomy: auto)`, { auditId: r.audit_id }); }
          else if (r.proposal) openDrawer({ type: "proposal", proposal: r.proposal });
          else toast("Your focus goal is already protected that week.", { tone: "info" });
          return;
        }
        case "defrag": {
          const r = await api.post<FocusResp>("/api/focus/defrag", { week_start: a.week_start });
          if (r.proposal) openDrawer({ type: "proposal", proposal: r.proposal });
          else toast("That week is already as consolidated as it can be without moving other people's meetings.", { tone: "info" });
          return;
        }
        case "series_action": {
          const r = await api.post<{ proposal: Proposal | null; draft: { subject: string; body: string } | null; message?: string }>(`/api/analytics/recurring/${a.series_id}/proposal`);
          if (r.proposal) openDrawer({ type: "proposal", proposal: r.proposal, draft: r.draft });
          else toast(r.message ?? "Nothing to change automatically.", { tone: "info" });
          return;
        }
        case "operations": {
          const r = await api.post<{ audit_id: string; summary: string }>("/api/operations", { operations: a.operations, summary: a.summary ?? a.label });
          refreshAll();
          toast(r.summary, { auditId: r.audit_id });
          return;
        }
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed", { tone: "error" });
    }
  }, [openDrawer, refreshAll, router, toast]);
}
