import { describe, expect, it } from "vitest";

import { formatEarnings, fscoreSummary, keyFigureRows, upsidePct } from "./profil";

describe("upsidePct", () => {
  it("rounds the target upside over the price", () => {
    expect(upsidePct(152, 118.4)).toBe(28);
  });

  it("is honest about a missing target or broken price", () => {
    expect(upsidePct(null, 100)).toBeNull();
    expect(upsidePct(120, 0)).toBeNull();
  });
});

describe("formatEarnings", () => {
  it("renders an ISO day in German", () => {
    expect(formatEarnings("2026-09-25")).toBe("25. Sept. 2026");
  });

  it("passes null and garbage through as null", () => {
    expect(formatEarnings(null)).toBeNull();
    expect(formatEarnings("kaputt")).toBeNull();
  });
});

describe("fscoreSummary", () => {
  it("uses the evaluable count as the honest denominator", () => {
    expect(
      fscoreSummary({ computed_on: "", score: 7, evaluable: 8, fiscal_year: 2025, criteria: {} }),
    ).toBe("7 von 8 Punkten");
  });
});

describe("keyFigureRows", () => {
  it("converts ratios to percent and keeps the KGV raw", () => {
    const rows = keyFigureRows({
      trailing_pe: 12.13,
      revenue_growth: 0.38,
      profit_margins: 0.281,
      return_on_equity: null,
      price_to_book: null,
    });
    expect(rows).toEqual([
      { label: "Bewertung (KGV)", value: "12,1" },
      { label: "Umsatzwachstum", value: "+38 %" },
      { label: "Gewinnmarge", value: "28,1 %" },
    ]);
  });

  it("returns nothing for a missing cache row", () => {
    expect(keyFigureRows(null)).toEqual([]);
  });
});
