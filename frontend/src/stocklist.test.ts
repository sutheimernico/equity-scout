import { describe, expect, it } from "vitest";

import type { StockBrief } from "./api";
import { splitSections } from "./stocklist";

function brief(over: Partial<StockBrief>): StockBrief {
  return {
    ticker: "AAA", name: "AAA Inc.", sector: null, industry: null, currency: "USD",
    price: 100, score: 40, score_band: "mittel", zone_low: 90, zone_high: 110,
    in_zone: false, zone_gap_pct: 0, zone_verdict: "", analyst_target: null,
    analyst_count: null, analyst_upside_pct: null, trailing_pe: null,
    model_target: null, model_stop: null, insight: null, chart: null,
    ...over,
  };
}

describe("splitSections", () => {
  it("puts in-zone stocks in the entry section, best score first", () => {
    const { inZone } = splitSections([
      brief({ ticker: "LOW", in_zone: true, score: 30 }),
      brief({ ticker: "HIGH", in_zone: true, score: 60 }),
      brief({ ticker: "OUT", in_zone: false, score: 90 }),
    ]);
    expect(inZone.map((b) => b.ticker)).toEqual(["HIGH", "LOW"]);
  });

  it("ranks the potential section by upside, highest first", () => {
    const { potential } = splitSections([
      brief({ ticker: "MID", analyst_upside_pct: 30 }),
      brief({ ticker: "TOP", analyst_upside_pct: 69 }),
      brief({ ticker: "LOWP", analyst_upside_pct: 9 }),
    ]);
    expect(potential.map((b) => b.ticker)).toEqual(["TOP", "MID", "LOWP"]);
  });

  it("never shows the same stock in both sections", () => {
    // MU is in the potential list; if it were also in-zone it must appear only once.
    const both = brief({ ticker: "MU", in_zone: true, analyst_upside_pct: 69 });
    const { inZone, potential } = splitSections([both]);
    expect(inZone.map((b) => b.ticker)).toEqual(["MU"]);
    expect(potential.map((b) => b.ticker)).toEqual([]);
  });

  it("excludes stocks without coverage from the potential section", () => {
    // A missing analyst target is not a potential of zero — it is unknown.
    const { potential } = splitSections([brief({ ticker: "AIRT", analyst_upside_pct: null })]);
    expect(potential).toEqual([]);
  });

  it("excludes negative upside from the potential section", () => {
    // "Potenzial −7 %" under a heading that promises potential is a contradiction; the
    // number still shows on the stock's own card, just not as a potential highlight.
    const { potential } = splitSections([brief({ ticker: "9064.T", analyst_upside_pct: -7 })]);
    expect(potential).toEqual([]);
  });

  it("caps the potential section at four rows", () => {
    const many = Array.from({ length: 9 }, (_, i) =>
      brief({ ticker: `T${i}`, analyst_upside_pct: 10 + i }),
    );
    expect(splitSections(many).potential).toHaveLength(4);
  });
});
