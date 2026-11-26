// Time-zone math with Intl only (no dependencies). Every view renders in the *user's* time zone,
// which can differ from the browser's (e.g. a Bangalore-based EA managing a San Francisco calendar).

export type ZonedParts = { year: number; month: number; day: number; hour: number; minute: number; weekday: number };

const partsCache = new Map<string, Intl.DateTimeFormat>();

function formatter(tz: string): Intl.DateTimeFormat {
  let f = partsCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: tz, year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric",
      weekday: "short", hourCycle: "h23",
    });
    partsCache.set(tz, f);
  }
  return f;
}

const WEEKDAY: Record<string, number> = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };

export function zonedParts(date: Date, tz: string): ZonedParts {
  const out: Record<string, string> = {};
  for (const p of formatter(tz).formatToParts(date)) out[p.type] = p.value;
  return {
    year: Number(out.year), month: Number(out.month), day: Number(out.day),
    hour: Number(out.hour) % 24, minute: Number(out.minute), weekday: WEEKDAY[out.weekday] ?? 0,
  };
}

/** Offset of `tz` from UTC at instant `date`, in minutes (e.g. -480 for PST). */
export function tzOffsetMinutes(date: Date, tz: string): number {
  const p = zonedParts(date, tz);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
  return Math.round((asUtc - Math.floor(date.getTime() / 60000) * 60000) / 60000);
}

/** The UTC instant for a wall-clock time in `tz` (DST-safe: re-checks the offset at the result). */
export function zonedToUtc(year: number, month: number, day: number, hour: number, minute: number, tz: string): Date {
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  let t = guess - tzOffsetMinutes(new Date(guess), tz) * 60000;
  const off2 = tzOffsetMinutes(new Date(t), tz);
  t = guess - off2 * 60000;
  return new Date(t);
}

/** Monday 00:00 (in tz) of the week containing `date`, shifted by `weeks`. */
export function weekStart(date: Date, tz: string, weeks = 0): Date {
  const p = zonedParts(date, tz);
  const base = new Date(Date.UTC(p.year, p.month - 1, p.day - p.weekday + weeks * 7));
  return zonedToUtc(base.getUTCFullYear(), base.getUTCMonth() + 1, base.getUTCDate(), 0, 0, tz);
}

/** Local midnight (in tz) `days` after the local date of `date`. */
export function addLocalDays(date: Date, days: number, tz: string): Date {
  const p = zonedParts(date, tz);
  const base = new Date(Date.UTC(p.year, p.month - 1, p.day + days));
  return zonedToUtc(base.getUTCFullYear(), base.getUTCMonth() + 1, base.getUTCDate(), 0, 0, tz);
}

export function localDateKey(date: Date, tz: string): string {
  const p = zonedParts(date, tz);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

export function minutesIntoDay(date: Date, tz: string): number {
  const p = zonedParts(date, tz);
  return p.hour * 60 + p.minute;
}

export function fmtTime(date: Date | string, tz: string): string {
  return new Date(date).toLocaleTimeString("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit" });
}

export function fmtDay(date: Date | string, tz: string): string {
  return new Date(date).toLocaleDateString("en-US", { timeZone: tz, weekday: "short", month: "short", day: "numeric" });
}

export function fmtRange(start: string, end: string, tz: string): string {
  return `${fmtDay(start, tz)} · ${fmtTime(start, tz)} – ${fmtTime(end, tz)}`;
}

export function weekLabel(start: Date, tz: string): string {
  const end = new Date(start.getTime() + 6 * 86400000);
  const a = start.toLocaleDateString("en-US", { timeZone: tz, month: "short", day: "numeric" });
  const b = end.toLocaleDateString("en-US", { timeZone: tz, month: "short", day: "numeric", year: "numeric" });
  return `${a} – ${b}`;
}

export function tzShort(tz: string, at: Date): string {
  const part = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(at).find((p) => p.type === "timeZoneName");
  return part?.value ?? tz;
}

export function hm(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
}
