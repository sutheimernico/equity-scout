import { describe, expect, it } from "vitest";

import {
  closedLabel,
  LANE_NOTES,
  laneName,
  runningLabel,
  shortTermTotals,
  verdictLine,
} from "./lanes";

describe("laneName", () => {
  it("replaces the raw key with what the lane does", () => {
    expect(laneName("swing")).toBe("Kauft nach guten Nachrichten");
  });

  it("falls back to the key for an unknown lane instead of inventing a name", () => {
    expect(laneName("futures")).toBe("futures");
  });

  it("keeps the backend short name available for the Telegram cross-reference", () => {
    expect(LANE_NOTES.session?.label).toBe("Intraday-Session");
  });
});

describe("group labels", () => {
  it("counts instead of repeating the same heading per lane", () => {
    expect(runningLabel(2)).toBe("2 laufen noch");
    expect(closedLabel(5)).toBe("5 abgeschlossen");
  });

  it("uses the singular for one", () => {
    expect(runningLabel(1)).toBe("1 läuft noch");
    expect(closedLabel(1)).toBe("1 abgeschlossen");
  });

  it("says plainly that there is nothing", () => {
    expect(runningLabel(0)).toBe("keine offene Position");
    expect(closedLabel(0)).toBe("noch nichts abgeschlossen");
  });
});

describe("shortTermTotals", () => {
  it("adds the lanes into one book and its return since start", () => {
    const totals = shortTermTotals([
      { equity: 10_148.92, initial_capital: 10_000 },
      { equity: 9_739.23, initial_capital: 10_000 },
      { equity: 9_393.42, initial_capital: 10_000 },
    ]);
    expect(totals.equity).toBeCloseTo(29_281.57, 2);
    expect(totals.invested).toBe(30_000);
    expect(totals.totalReturn).toBeCloseTo(-0.023948, 5);
  });

  it("reports no return rather than dividing by zero when nothing was invested", () => {
    expect(shortTermTotals([]).totalReturn).toBeNull();
  });
});

describe("verdictLine", () => {
  it("states a settled verdict instead of asking for more days", () => {
    // The live crypto lane on 2026-08-16: 32 trades, p = 0.0003 — the page still said
    // "Track Record zu kurz für ein Urteil" because it counted calendar days.
    const line = verdictLine({
      verdict: "negativ",
      significant: true,
      trades_missing: 0,
      n: 32,
    });
    expect(line).toEqual({ text: "Urteil steht: verliert Geld", settled: true });
  });

  it("names how many trades are still missing while it is open", () => {
    expect(
      verdictLine({ verdict: "noch nicht aussagekräftig", significant: false, trades_missing: 26, n: 8 }),
    ).toEqual({ text: "Noch kein Urteil — 26 Trades fehlen", settled: false });
  });

  it("does not promise a future verdict when the effect is too small to ever resolve", () => {
    expect(
      verdictLine({ verdict: "kein messbarer Effekt", significant: false, trades_missing: null, n: 40 }).text,
    ).toBe("Kein messbarer Unterschied — zu nah an null");
  });

  it("falls back to the trade count when no target is known", () => {
    expect(
      verdictLine({ verdict: "zu wenige Trades", significant: false, trades_missing: null, n: 3 }).text,
    ).toBe("Noch kein Urteil — erst 3 Trades");
  });
});
