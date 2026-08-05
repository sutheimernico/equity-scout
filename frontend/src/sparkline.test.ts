import { describe, expect, it } from "vitest";

import { sparklinePath, yearReturnPct } from "./sparkline";

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
