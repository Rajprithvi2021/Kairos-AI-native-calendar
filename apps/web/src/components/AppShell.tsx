"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CalendarDays, ChartColumn, Command, FlaskConical, Search, Settings, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { CommandBar } from "@/components/CommandBar";
import { useUi } from "@/components/providers";
import { ENGINE_LABEL } from "@/components/ui";
import { api } from "@/lib/api";
import type { Health } from "@/lib/types";

const NAV = [
  { href: "/", label: "Calendar", icon: CalendarDays },
  { href: "/insights", label: "Insights", icon: ChartColumn },
  { href: "/study", label: "Study mode", icon: FlaskConical },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { setCommandOpen } = useUi();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/api/health"), refetchInterval: 60_000 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setCommandOpen]);

  const ai = health.data?.ai;
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Below the lg breakpoint the sidebar collapses to an icon rail; labels stay available to screen readers. */}
      <nav className="flex w-14 shrink-0 flex-col border-r border-border bg-surface lg:w-56" aria-label="Main">
        <div className="flex items-center justify-center gap-2 px-2 py-5 lg:justify-start lg:px-5">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 text-white shadow">
            <Sparkles className="h-4 w-4" aria-hidden />
          </div>
          <div className="hidden lg:block">
            <div className="text-[15px] font-semibold leading-tight">Kairos</div>
            <div className="text-[11px] text-muted">the right moment</div>
          </div>
        </div>
        <button onClick={() => setCommandOpen(true)} title="Ask Kairos (Ctrl+K)"
          className="mx-2 mb-3 flex items-center justify-center gap-2 rounded-lg border border-border bg-slate-50 px-2 py-2 text-left text-sm text-muted hover:bg-slate-100 lg:mx-3 lg:justify-start lg:px-3"
          aria-label="Ask Kairos (Ctrl+K)">
          <Search className="h-4 w-4 shrink-0" aria-hidden /> <span className="hidden flex-1 lg:inline">Ask Kairos…</span>
          <kbd className="hidden items-center rounded border border-border bg-white px-1 text-[10px] lg:inline-flex"><Command className="h-2.5 w-2.5" />K</kbd>
        </button>
        <ul className="space-y-0.5 px-2 lg:px-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname?.startsWith(href);
            return (
              <li key={href}>
                <Link href={href} aria-current={active ? "page" : undefined} title={label}
                  className={clsx("flex items-center justify-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium lg:justify-start", active ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-ink")}>
                  <Icon className="h-4 w-4 shrink-0" aria-hidden /><span className="sr-only lg:not-sr-only">{label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="mt-auto space-y-2 p-2 text-[11px] text-muted lg:p-4">
          <div className={clsx("flex items-center justify-center gap-2 rounded-lg px-2 py-2 lg:justify-start lg:px-3",
            health.isError ? "bg-red-50 text-red-700" : ai && ai.engine !== "offline" ? "bg-violet-50 text-violet-700" : "bg-slate-100 text-slate-600")}
            title={health.isError ? "API offline — start it with scripts/dev.ps1" : ai?.reason}>
            <Sparkles className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span className="sr-only font-medium lg:not-sr-only">{ai ? (ai.engine !== "offline" ? `${ENGINE_LABEL[ai.engine] ?? ai.engine} · ${ai.model}` : "Offline AI") : "Connecting…"}</span>
          </div>
          {health.data?.simulated_clock && <div className="hidden rounded-lg bg-amber-50 px-3 py-1.5 text-amber-800 lg:block">Simulated clock</div>}
          {health.isError && <div className="hidden rounded-lg bg-red-50 px-3 py-1.5 text-red-700 lg:block">API offline — start it with scripts/dev.ps1</div>}
        </div>
      </nav>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>
      <CommandBar />
    </div>
  );
}
