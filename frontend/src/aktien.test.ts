import { describe, expect, it } from "vitest";

import type { StockBrief } from "./api";
import { filterBriefs, riskMeta, zoneSegment } from "./aktien";

function brief(overrides: Partial<StockBrief> = {}): StockBrief {
  return {
    ticker: "AAA",
    name: "AAA Inc.",
    bucket: "balanced",
    sector: null,
    industry: null,
    currency: "USD",
    price: 100,
    score: 50,
    score_band: "mittel",
    zone_low: 90,
    zone_high: 110,
    in_zone: true,
    zone_gap_pct: 0,
    zone_verdict: "im Einstiegsbereich",
    entry_note: "",
    analyst_target: null,
    analyst_count: null,
    analyst_upside_pct: null,
    trailing_pe: null,
    model_target: null,
    model_stop: null,
    target_source: null,
    insight: null,
    chart: null,
    ...overrides,
  };
}

describe("zoneSegment", () => {
  it("in_zone wins regardless of price", () => {
    expect(zoneSegment(brief({ in_zone: true, price: 200 }))).toBe("in");
  });

  it("just above the band is near, up to 5 % over the top edge", () => {
    expect(zoneSegment(brief({ in_zone: false, price: 112, zone_high: 110 }))).toBe("near");
    expect(zoneSegment(brief({ in_zone: false, price: 115.5, zone_high: 110 }))).toBe("near");
  });

  it("more than 5 % above the band is not near", () => {
    expect(zoneSegment(brief({ in_zone: false, price: 116, zone_high: 110 }))).toBe("other");
  });

  it("below the band is never near — broken support is not an almost-entry", () => {
    expect(zoneSegment(brief({ in_zone: false, price: 80, zone_low: 90 }))).toBe("other");
  });
});

describe("filterBriefs", () => {
  const briefs = [
    brief({ ticker: "IN_DEF", in_zone: true, bucket: "defensive" }),
    brief({ ticker: "IN_AGG", in_zone: true, bucket: "aggressive" }),
    brief({ ticker: "NEAR", in_zone: false, price: 112, bucket: "balanced" }),
    brief({ ticker: "FAR", in_zone: false, price: 150, bucket: "aggressive" }),
  ];

  it("segment and bucket combine", () => {
    expect(filterBriefs(briefs, "in", "aggressive").map((b) => b.ticker)).toEqual(["IN_AGG"]);
  });

  it("'all' segment with 'alle' bucket passes everything through", () => {
    expect(filterBriefs(briefs, "all", "alle")).toHaveLength(4);
  });

  it("near segment excludes stocks far above the zone", () => {
    expect(filterBriefs(briefs, "near", "alle").map((b) => b.ticker)).toEqual(["NEAR"]);
  });
});

describe("riskMeta", () => {
  it("maps every bucket to a German label", () => {
    expect(riskMeta("defensive")?.label).toBe("Defensiv");
    expect(riskMeta("balanced")?.label).toBe("Ausgewogen");
    expect(riskMeta("aggressive")?.label).toBe("Aggressiv");
  });

  it("aggressive wears the violet chip — risk never uses status colours", () => {
    expect(riskMeta("aggressive")?.chip).toContain("risk");
  });

  it("is honest about an unknown bucket", () => {
    expect(riskMeta(null)).toBeNull();
  });
});
