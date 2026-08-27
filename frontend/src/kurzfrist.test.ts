import { describe, expect, it } from "vitest";

import type { ShortTermLane } from "./api";
import {
  LANE_LABELS,
  laneRows,
  plainVerdict,
  realizedNote,
  shortTermHeadline,
} from "./kurzfrist";

function lane(over: Partial<ShortTermLane> = {}): ShortTermLane {
  return {
    lane: "crypto",
    initial_capital: 10_000,
    equity: 11_018,
    total_return: 0.1018,
    benchmark_ticker: "BTC",
    benchmark_return: 0.2138,
    max_drawdown: 0.1,
    execution_regime: null,
    strategy_regime: null,
    broker_equity: null,
    significance: {
      n: 32, mean_pnl: -5, p_value: 0.00028, trades_needed: null, trades_missing: null,
      verdict: "negativ", note: "", significant: true,
    },
    loss_anatomy: [],
    open_positions: [],
    equity_curve: [],
    stats: { n_trades: 32, n_fills: 40, win_rate: 0.4, realized_pnl: -160, fees_paid: 460 },
    recent_trades: [],
    promoted: false,
    promotion: {} as ShortTermLane["promotion"],
    ...over,
  };
}

describe("Lane-Zeilen", () => {
  it("rechnet die Überrendite gegen den Benchmark der Lane", () => {
    // Krypto am 2026-08-27: +10,18 % gegen BTC +21,38 % = 11,2 pp dahinter.
    const [row] = laneRows([lane()]);
    expect(row.excessPct).toBeCloseTo(-11.2, 1);
  });

  it("lässt die Überrendite leer, wenn kein Benchmark gemessen wurde", () => {
    // ignition hatte am 2026-08-27 keinen — eine 0 wäre hier eine Behauptung.
    const [row] = laneRows([lane({ benchmark_return: null })]);
    expect(row.excessPct).toBeNull();
    expect(row.benchmarkPct).toBeNull();
  });

  it("nimmt die Trade-Zahl aus der Signifikanz, nicht aus den Gesamtstatistiken", () => {
    // stats.n_trades zählt auch Offenes; das Urteil beruht auf significance.n.
    const [row] = laneRows([
      lane({
        stats: { n_trades: 99, n_fills: 99, win_rate: 0.5, realized_pnl: 0, fees_paid: 0 },
        significance: { ...lane().significance, n: 32 },
      }),
    ]);
    expect(row.trades).toBe(32);
  });

  it("übersetzt jede Lane-Kennung in einen lesbaren Namen", () => {
    expect(laneRows([lane({ lane: "ignition" })])[0].label).toBe(LANE_LABELS.ignition);
  });

  it("fällt bei unbekannter Lane auf die Kennung zurück statt auf undefined", () => {
    expect(laneRows([lane({ lane: "neu" })])[0].label).toBe("neu");
  });
});

describe("Urteil im Klartext", () => {
  it("nennt einen messbaren Verlust beim Namen", () => {
    const text = plainVerdict("negativ", 32, -11.2);
    expect(text).toContain("Verliert messbar");
    expect(text).toContain("32");
    expect(text).toContain("kein Zufallsergebnis");
  });

  it("verkauft zu wenige Trades nicht als Ergebnis", () => {
    expect(plainVerdict("zu wenige Trades", 3, 1.0)).toContain("nichts ablesen");
  });

  it("sagt bei unklarem Befund, dass es noch keiner ist", () => {
    expect(plainVerdict("noch nicht aussagekräftig", 63, -7.3)).toContain("noch nicht");
  });

  it("erwähnt den Rückstand nur, wenn es einen gibt", () => {
    expect(plainVerdict("noch nicht aussagekräftig", 63, -7.3)).toContain("hinter ihrem");
    expect(plainVerdict("noch nicht aussagekräftig", 63, 2.0)).not.toContain("hinter ihrem");
    expect(plainVerdict("noch nicht aussagekräftig", 63, null)).not.toContain("hinter ihrem");
  });
});

describe("Überschrift", () => {
  it("sagt klar, dass es keine Kaufliste gibt, und nennt den verlierenden Fall", () => {
    const rows = laneRows([lane(), lane({ lane: "swing" })]);
    const text = shortTermHeadline(rows);
    expect(text).toContain("keine Kaufliste");
    expect(text).toContain("verliert messbar");
  });

  it("meldet es, sobald eine Lane das Ergebnis-Gate besteht", () => {
    const rows = laneRows([lane({ promoted: true }), lane({ lane: "swing" })]);
    expect(shortTermHeadline(rows)).toContain("1 von 2");
    expect(shortTermHeadline(rows)).toContain("Depot-Kapital");
  });

  it("kommt ohne Lanes ohne Absturz aus", () => {
    expect(shortTermHeadline([])).toContain("Noch keine");
  });
});

describe("Abgeschlossen vs. offen", () => {
  it("trennt realisierten Verlust vom Buchgewinn offener Positionen", () => {
    // Der reale Krypto-Fall am 2026-08-27: +10,2 % auf dem Papier, −451,60 realisiert.
    const text = realizedNote(-451.6, 548.34, 32, 4);
    expect(text).toContain("−451,60");
    expect(text).toContain("32 Trades");
    expect(text).toContain("548,34");
    expect(text).toContain("4 offene Positionen");
  });

  it("nennt eine einzelne offene Position im Singular", () => {
    expect(realizedNote(10, 1, 5, 1)).toContain("1 offene Position.");
  });

  it("erwähnt offene Positionen gar nicht, wenn es keine gibt", () => {
    // session am 2026-08-27: 63 Trades, 0 offen.
    expect(realizedNote(-260.77, 34.54, 63, 0)).not.toContain("offene");
  });

  it("sagt bei null Trades, dass die Zahl oben reiner Buchwert ist", () => {
    const text = realizedNote(0, 0, 0, 3);
    expect(text).toContain("reiner Buchwert");
    expect(text).toContain("3 offenen");
  });

  it("kommt ohne Trades und ohne offene Positionen aus", () => {
    expect(realizedNote(0, 0, 0, 0)).toBe("Noch nichts abgeschlossen.");
  });

  it("hängt die Zeile an jede Lane-Zeile", () => {
    expect(laneRows([lane()])[0].realizedNote).toContain("Trades");
  });
});
