"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Globe, Plus, Search, Sparkles, TriangleExclamationPoint } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { ConflictDrawer } from "@/components/calendar/ConflictDrawer";
import { CopilotRail } from "@/components/calendar/CopilotRail";
import { EventDrawer } from "@/components/calendar/EventDrawer";
import { ScheduleDrawer } from "@/components/calendar/ScheduleDrawer";
import { WeekGrid } from "@/components/calendar/WeekGrid";
import { ProposalView } from "@/components/ProposalView";
import { useUi } from "@/components/providers";
import { Button, Drawer, ErrorNote, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { addLocalDays, tzShort, weekLabel, weekStart } from "@/lib/time";
import type { Conflict, EventsResponse, Health, Me } from "@/lib/types";

function minutes(hhmm: string) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

export function CalendarWorkspace() {
  const { drawer, openDrawer, ghost, setCommandOpen } = useUi();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/api/health") });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me") });
  const tz = me.data?.person.timezone;
  const now = useMemo(() => (health.data ? new Date(health.data.now) : null), [health.data]);
  const [offset, setOffset] = useState(0);
  const [railOpen, setRailOpen] = useState(false); // Copilot as an overlay below the xl breakpoint
  const closeRail = useCallback(() => setRailOpen(false), []);
  const offsetFor = useCallback((iso: string) => {
    if (!now || !tz) return 0;
    return Math.round((weekStart(new Date(iso), tz).getTime() - weekStart(now, tz).getTime()) / (7 * 86400000));
  }, [now, tz]);
  // While a suggestion is previewed, show the week it falls in (derived, no effect); then return.
  const viewOffset = ghost ? offsetFor(ghost.start) : offset;
  const ws = useMemo(() => (now && tz ? weekStart(now, tz, viewOffset) : null), [now, tz, viewOffset]);
  const we = useMemo(() => (ws && tz ? addLocalDays(ws, 7, tz) : null), [ws, tz]);

  const events = useQuery({
    queryKey: ["events", ws?.toISOString()],
    enabled: !!ws && !!we,
    queryFn: () => api.get<EventsResponse>(`/api/events?start=${encodeURIComponent(ws!.toISOString())}&end=${encodeURIComponent(we!.toISOString())}`),
  });
  const conflicts = useQuery({ queryKey: ["conflicts"], queryFn: () => api.get<Conflict[]>("/api/conflicts") });

  const jumpTo = useCallback((iso: string) => setOffset(offsetFor(iso)), [offsetFor]);

  if (health.isError || me.isError) return <div className="p-8"><ErrorNote error={health.error ?? me.error} /></div>;
  if (!now || !tz || !ws || !me.data) return <div className="p-8"><Spinner label="Loading your calendar" /></div>;
  const person = me.data.person;
  const conflictCount = conflicts.data?.length ?? 0;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b border-border bg-surface px-4 py-3">
          <Button size="sm" onClick={() => setOffset(0)}>Today</Button>
          <Button size="sm" variant="ghost" aria-label="Previous week" onClick={() => setOffset(viewOffset - 1)}><ChevronLeft className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" aria-label="Next week" onClick={() => setOffset(viewOffset + 1)}><ChevronRight className="h-4 w-4" /></Button>
          <h1 className="mr-2 text-lg font-semibold">{weekLabel(ws, tz)}</h1>
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600" title={tz}>
            <Globe className="h-3 w-3" aria-hidden />{tzShort(tz, now)} · {person.city}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setCommandOpen(true)} className="hidden items-center gap-2 rounded-lg border border-border bg-slate-50 px-3 py-1.5 text-xs text-muted hover:bg-slate-100 md:inline-flex">
              <Search className="h-3.5 w-3.5" />Ask Kairos… <kbd className="rounded border border-border bg-white px-1">Ctrl K</kbd>
            </button>
            <Button size="sm" variant={conflictCount ? "danger" : "secondary"} onClick={() => openDrawer({ type: "conflicts" })}
              aria-label={conflicts.isPending ? "Checking conflicts" : `${conflictCount} conflict${conflictCount === 1 ? "" : "s"}`}>
              <TriangleExclamationPoint className="h-3.5 w-3.5" />
              {conflicts.isPending ? "Checking…" : `${conflictCount} conflict${conflictCount === 1 ? "" : "s"}`}
            </Button>
            <Button size="sm" variant="primary" onClick={() => openDrawer({ type: "schedule" })}><Plus className="h-3.5 w-3.5" />New meeting</Button>
            <Button size="sm" className="xl:hidden" onClick={() => setRailOpen(true)} aria-expanded={railOpen} aria-controls="copilot-rail">
              <Sparkles className="h-3.5 w-3.5 text-ai" aria-hidden />Open Copilot
            </Button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-auto bg-surface">
          {events.isError ? <div className="p-6"><ErrorNote error={events.error} /></div> : (
            <WeekGrid weekStart={ws} tz={tz} now={now} events={events.data?.events ?? []} holidays={events.data?.holidays ?? []}
              workStart={minutes(person.work_start)} workEnd={minutes(person.work_end)} ghost={ghost}
              onSelect={(id) => openDrawer({ type: "event", eventId: id })} />
          )}
        </div>
      </div>
      <CopilotRail tz={tz} open={railOpen} onClose={closeRail} />

      <ScheduleDrawer key={drawer?.type === "schedule" ? `schedule-${JSON.stringify(drawer.prefill ?? {})}` : "schedule-closed"}
        open={drawer?.type === "schedule"} prefill={drawer?.type === "schedule" ? drawer.prefill : undefined}
        onClose={() => openDrawer(null)} tz={tz} now={now} />
      <ConflictDrawer key={drawer?.type === "conflicts" ? `conflicts-${drawer.conflictId ?? "all"}` : "conflicts-closed"} open={drawer?.type === "conflicts"}
        focusId={drawer?.type === "conflicts" ? drawer.conflictId : undefined} onClose={() => openDrawer(null)} tz={tz} onJump={jumpTo} />
      <EventDrawer eventId={drawer?.type === "event" ? drawer.eventId : null} onClose={() => openDrawer(null)} tz={tz} />
      <Drawer open={drawer?.type === "proposal"} onClose={() => openDrawer(null)} title={drawer?.type === "proposal" ? drawer.proposal.title : ""}
        subtitle="Review before applying. Kairos proposes; you decide.">
        {drawer?.type === "proposal" && <ProposalView proposal={drawer.proposal} draft={drawer.draft} onDone={() => openDrawer(null)} />}
      </Drawer>
    </div>
  );
}
