import { describe, expect, it } from "vitest";

import { todaysSignals, todayVerdict } from "./today";

describe("todaysSignals", () => {
  it("keeps only what was notified today", () => {
    const rows = [
      { notified_at: "2026-08-27T06:00:00+00:00", stance: "kaufbereit" },
      { notified_at: "2026-08-25T06:00:00+00:00", stance: "kaufbereit" },
    ];
    expect(todaysSignals(rows, "2026-08-27")).toHaveLength(1);
  });

  it("does not leave the card claiming an old find for days", () => {
    const rows = [{ notified_at: "2026-08-20T06:00:00+00:00", stance: "kaufbereit" }];
    expect(todaysSignals(rows, "2026-08-27")).toEqual([]);
  });
});

describe("todayVerdict", () => {
  it("ranks by urgency, not by count", () => {
    expect(todayVerdict({ ready: 1, decisions: 9, soon: 9 })).toBe("kaufbereit");
    expect(todayVerdict({ ready: 0, decisions: 1, soon: 9 })).toBe("entscheiden");
    expect(todayVerdict({ ready: 0, decisions: 0, soon: 1 })).toBe("bald");
  });

  it("treats an empty day as a real answer, not as an absence", () => {
    expect(todayVerdict({ ready: 0, decisions: 0, soon: 0 })).toBe("ruhig");
  });
});
