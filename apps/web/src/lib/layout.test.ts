import { describe, expect, it } from "vitest";

import { layoutDay } from "./layout";
import { addLocalDays, fmtTime, tzOffsetMinutes, weekStart, zonedParts, zonedToUtc } from "./time";

describe("layoutDay", () => {
  it("keeps non-overlapping events full width", () => {
    const m = layoutDay([{ id: "a", start: 540, end: 600 }, { id: "b", start: 600, end: 660 }]);
    expect(m.get("a")).toEqual({ id: "a", col: 0, cols: 1 });
    expect(m.get("b")).toEqual({ id: "b", col: 0, cols: 1 });
  });

  it("places overlapping events side by side and reuses freed columns", () => {
    const m = layoutDay([
      { id: "a", start: 540, end: 660 },
      { id: "b", start: 570, end: 600 },
      { id: "c", start: 600, end: 630 },
      { id: "d", start: 700, end: 720 },
    ]);
    expect(m.get("a")!.cols).toBe(2);
    expect(m.get("b")!.col).toBe(1);
    expect(m.get("c")!.col).toBe(1); // reuses b's column
    expect(m.get("d")).toEqual({ id: "d", col: 0, cols: 1 });
  });
});

describe("time-zone math", () => {
  it("handles US DST and half-hour zones", () => {
    expect(tzOffsetMinutes(new Date("2026-01-15T12:00:00Z"), "America/Los_Angeles")).toBe(-480);
    expect(tzOffsetMinutes(new Date("2026-07-15T12:00:00Z"), "America/Los_Angeles")).toBe(-420);
    expect(tzOffsetMinutes(new Date("2026-07-15T12:00:00Z"), "Asia/Kolkata")).toBe(330);
  });

  it("converts wall-clock to UTC across the spring-forward boundary", () => {
    expect(zonedToUtc(2026, 3, 6, 9, 0, "America/Los_Angeles").toISOString()).toBe("2026-03-06T17:00:00.000Z");
    expect(zonedToUtc(2026, 3, 9, 9, 0, "America/Los_Angeles").toISOString()).toBe("2026-03-09T16:00:00.000Z");
  });

  it("finds the Monday of the week in the user's zone, not the browser's", () => {
    // 2026-11-25 03:00 UTC is still Tuesday evening in San Francisco.
    const ws = weekStart(new Date("2026-11-25T03:00:00Z"), "America/Los_Angeles");
    expect(ws.toISOString()).toBe("2026-11-23T08:00:00.000Z");
    expect(zonedParts(ws, "America/Los_Angeles")).toMatchObject({ weekday: 0, hour: 0 });
    expect(addLocalDays(ws, 7, "America/Los_Angeles").toISOString()).toBe("2026-11-30T08:00:00.000Z");
    expect(fmtTime("2026-11-25T17:00:00Z", "America/Los_Angeles")).toBe("9:00 AM");
  });
});
