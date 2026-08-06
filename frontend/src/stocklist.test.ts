import { describe, expect, it } from "vitest";

import type { StockBrief } from "./api";
import { shortVerdict, splitSections } from "./stocklist";

function brief(over: Partial<StockBrief>): StockBrief {
  return {
    ticker: "AAA", name: "AAA Inc.", sector: null, industry: null, currency: "USD",
    price: 100, score: 40, score_band: "mittel", zone_low: 90, zone_high: 110,
    in_zone: false, zone_gap_pct: 0, zone_verdict: "", entry_note: "", analyst_target: null,
    analyst_count: null, analyst_upside_pct: null, trailing_pe: null,
    model_target: null, model_stop: null, insight: null, chart: null,
    ...over,
  };
}

describe("splitSections", () => {
  it("puts in-zone stocks in the entry section, best potential first", () => {
    const { inZone } = splitSections([
      brief({ ticker: "LOW", in_zone: true, analyst_upside_pct: 5 }),
      brief({ ticker: "HIGH", in_zone: true, analyst_upside_pct: 20 }),
      brief({ ticker: "OUT", in_zone: false, analyst_upside_pct: 90 }),
    ]);
    expect(inZone.map((b) => b.ticker)).toEqual(["HIGH", "LOW"]);
  });

  it("sinks an in-zone stock the analysts see no room in", () => {
    // Being in the zone is a timing statement, not a reason to buy — so a negative
    // potential goes last instead of leading the section.
    const { inZone } = splitSections([
      brief({ ticker: "NEG", in_zone: true, analyst_upside_pct: -7 }),
      brief({ ticker: "POS", in_zone: true, analyst_upside_pct: 15 }),
    ]);
    expect(inZone.map((b) => b.ticker)).toEqual(["POS", "NEG"]);
  });

  it("puts an in-zone stock without coverage last, not first", () => {
    const { inZone } = splitSections([
      brief({ ticker: "NONE", in_zone: true, analyst_upside_pct: null }),
      brief({ ticker: "SOME", in_zone: true, analyst_upside_pct: 2 }),
    ]);
    expect(inZone.map((b) => b.ticker)).toEqual(["SOME", "NONE"]);
  });

  it("ranks the potential section by upside, highest first", () => {
    const { potential } = splitSections([
      brief({ ticker: "MID", analyst_upside_pct: 35 }),
      brief({ ticker: "TOP", analyst_upside_pct: 69 }),
      brief({ ticker: "LOWP", analyst_upside_pct: 31 }),
    ]);
    expect(potential.map((b) => b.ticker)).toEqual(["TOP", "MID", "LOWP"]);
  });

  it("keeps only upsides worth a look — 30 % and above", () => {
    // Nico: "ich würd alles ab Potenzial dreißig plus filtern". A +9 % consensus is not a
    // highlight; it still shows on the stock's own card wherever that appears.
    const { potential } = splitSections([
      brief({ ticker: "IN", analyst_upside_pct: 30 }),
      brief({ ticker: "OUT", analyst_upside_pct: 29 }),
    ]);
    expect(potential.map((b) => b.ticker)).toEqual(["IN"]);
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
      brief({ ticker: `T${i}`, analyst_upside_pct: 40 + i }),
    );
    expect(splitSections(many).potential).toHaveLength(4);
  });
});

describe("shortVerdict", () => {
  it("names the entry state in two words when in zone", () => {
    expect(shortVerdict(brief({ in_zone: true, zone_verdict: "im Einstiegsbereich" }))).toBe(
      "Einstiegsbereich",
    );
  });

  it("keeps the distance, which now carries no value claim", () => {
    // The list needs the fact; the reason belongs in the detail view.
    expect(
      shortVerdict(brief({ in_zone: false, zone_verdict: "69 % über der Einstiegszone" })),
    ).toBe("69 % über der Einstiegszone");
  });

  it("handles the broken-support side the same way", () => {
    expect(
      shortVerdict(
        brief({ in_zone: false, zone_verdict: "12 % unter der Zone — Support gebrochen" }),
      ),
    ).toBe("12 % unter der Zone");
  });

  it("passes a verdict without a tail straight through", () => {
    expect(shortVerdict(brief({ zone_verdict: "kein gültiger Kurs verfügbar" }))).toBe(
      "kein gültiger Kurs verfügbar",
    );
  });
});
