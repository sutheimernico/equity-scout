import { describe, expect, it } from "vitest";

import { monthTicks, priceTicks, sparklinePath, yearReturnPct } from "./sparkline";

describe("sparklinePath", () => {
  it("spans the full width and pins the extremes to the padded box", () => {
    const path = sparklinePath([10, 20], { width: 100, height: 40, pad: 2 });
    // First point at x=0, last at x=width; the low sits at the bottom, the high at the top.
    expect(path).toBe("M 0 38 L 100 2");
  });

  it("draws a flat series through the vertical middle instead of dividing by zero", () => {
    const path = sparklinePath([5, 5, 5], { width: 100, height: 40, pad: 2 });
    expect(path).toBe("M 0 20 L 50 20 L 100 20");
  });

  it("returns an empty path for fewer than two points", () => {
    expect(sparklinePath([], { width: 100, height: 40, pad: 2 })).toBe("");
    expect(sparklinePath([7], { width: 100, height: 40, pad: 2 })).toBe("");
  });
});

describe("yearReturnPct", () => {
  it("computes the return from the real endpoints", () => {
    expect(yearReturnPct([100, 150])).toBe(50);
  });

  it("is null without enough data or with a non-positive start", () => {
    expect(yearReturnPct([100])).toBeNull();
    expect(yearReturnPct([0, 50])).toBeNull();
  });
});

describe("priceTicks", () => {
  it("rounds to clean numbers inside the value range", () => {
    // 1879..1965 -> steps of 50 land on 1900/1950, both inside the range.
    expect(priceTicks(1879, 1965, 3)).toEqual([1900, 1950]);
  });

  it("handles small prices without collapsing to a single tick", () => {
    const ticks = priceTicks(1.07, 1.94, 3);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    // Every tick must sit inside the range, or it would draw outside the plot.
    for (const t of ticks) {
      expect(t).toBeGreaterThanOrEqual(1.07);
      expect(t).toBeLessThanOrEqual(1.94);
    }
  });

  it("returns no ticks for a flat series (no range to label)", () => {
    expect(priceTicks(50, 50, 3)).toEqual([]);
  });
});

describe("monthTicks", () => {
  const year = (() => {
    // One ISO date per month start across 13 months, as the cache stores them.
    const out: string[] = [];
    for (let m = 0; m < 13; m++) {
      const month = ((7 + m) % 12) + 1;
      const yr = 7 + m < 12 ? 2025 : 2026;
      out.push(`${yr}-${String(month).padStart(2, "0")}-01`);
    }
    return out;
  })();

  it("labels every third month, so a year fits without collisions", () => {
    const ticks = monthTicks(year, 3);
    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks.length).toBeLessThanOrEqual(5);
  });

  it("labels months in German short form", () => {
    const labels = monthTicks(year, 3).map((t) => t.label);
    // Aug 2025 is index 0; every third month from there.
    expect(labels[0]).toBe("Aug");
    expect(labels).toContain("Nov");
  });

  it("places each tick at the index of its first day in the series", () => {
    const ticks = monthTicks(year, 3);
    expect(ticks[0].index).toBe(0);
    // Nov 2025 is the 4th entry (Aug, Sep, Okt, Nov) -> index 3.
    expect(ticks.find((t) => t.label === "Nov")?.index).toBe(3);
  });

  it("returns nothing without dates (legacy cache rows)", () => {
    expect(monthTicks([], 3)).toEqual([]);
  });
});

describe("sparklinePath origin", () => {
  it("shifts the whole path into a plot box inside a larger viewBox", () => {
    // Same series as the first test, offset by the axis gutter.
    const path = sparklinePath([10, 20], { width: 100, height: 40, pad: 2, x: 34, y: 6 });
    expect(path).toBe("M 34 44 L 134 8");
  });
});
