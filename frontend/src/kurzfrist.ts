// Die kurzfristige Seite des Kaufplans (Nachtschicht 2026-08-27).
//
// Nico hat „langfristige Aktie, kurzfristige Aktie" verlangt. Die lange Seite ist der
// Faktor-Screen und liefert Kaufpläne. Für die kurze gibt es KEINE Vorschlagsquelle, die
// diesem Repo zufolge trägt — und das ist am 2026-08-27 keine Vorsicht, sondern Messung:
//
//   crypto    32 Trades, Urteil „negativ", p = 0,0003  → nachweislich verlierend
//   session   63 Trades, „noch nicht aussagekräftig"   → pausiert seit 2026-08-16
//   swing     13 Trades, „noch nicht aussagekräftig"
//   ignition   3 Trades, „zu wenige Trades"
//   promoted: keine einzige — keine Lane handelt Depot-Kapital
//
// Aus ungeprüften Katalysator-Meldungen trotzdem eine Kaufliste zu bauen, wäre genau die
// Sorte Oberfläche, die dieses Repo an anderer Stelle mühsam wieder eingefangen hat. Also
// zeigt die kurze Seite, was gemessen wurde, und sagt, was daraus folgt.

import type { ShortTermLane } from "./api";

export interface LaneVerdictRow {
  lane: string;
  label: string;
  trades: number;
  verdict: string;
  /** true nur, wenn die Lane echtes Depot-Kapital bekommt. */
  promoted: boolean;
  returnPct: number;
  benchmarkPct: number | null;
  benchmarkTicker: string;
  /** Rendite minus Benchmark, oder null wenn kein Benchmark gemessen wurde. */
  excessPct: number | null;
  /** Das Urteil in einem Satz, den man ohne Statistikwissen lesen kann. */
  plain: string;
  realizedPnl: number;
  feesPaid: number;
  openPositions: number;
  /** Trennt abgeschlossen von offen — ohne das widerspricht die Karte sich selbst. */
  realizedNote: string;
}

export const LANE_LABELS: Record<string, string> = {
  swing: "Event-Swing",
  session: "Intraday-Session",
  crypto: "Krypto",
  ignition: "Katalysator-Zündung",
  gapfade: "Gap-Fade",
};

/** Übersetzt das Signifikanz-Urteil in einen Satz ohne Fachbegriffe. */
export function plainVerdict(verdict: string, trades: number, excessPct: number | null): string {
  if (verdict === "negativ") {
    return `Verliert messbar — über ${trades} abgeschlossene Trades, und das ist kein Zufallsergebnis mehr.`;
  }
  if (verdict === "positiv") {
    return `Verdient messbar — über ${trades} abgeschlossene Trades.`;
  }
  if (verdict === "zu wenige Trades") {
    return `Erst ${trades} abgeschlossene Trades — daraus lässt sich nichts ablesen.`;
  }
  if (verdict === "kein messbarer Effekt") {
    return `Über ${trades} Trades kein erkennbarer Effekt in eine Richtung.`;
  }
  const behind =
    excessPct === null ? "" : excessPct < 0 ? " Aktuell liegt sie hinter ihrem Vergleichsindex." : "";
  return `${trades} Trades reichen für ein Urteil noch nicht.${behind}`;
}

/** Warum die Gesamtrendite und das Urteil auseinanderlaufen dürfen.
 *
 *  Der reale Fall am 2026-08-27: die Krypto-Lane steht bei +10,2 % und trägt trotzdem das
 *  Urteil „verliert messbar". Beides stimmt — die Rendite ist Buchwert von vier OFFENEN
 *  Positionen in einer BTC-Rally, während die 32 ABGESCHLOSSENEN Trades zusammen −451,60
 *  gebracht haben, bei 548,34 Gebühren. Eine Karte, die nur die +10,2 % zeigt, liest sich
 *  wie eine funktionierende Strategie. */
export function realizedNote(
  realizedPnl: number,
  feesPaid: number,
  trades: number,
  openPositions: number,
): string {
  if (trades === 0) {
    return openPositions > 0
      ? `Noch nichts abgeschlossen — die Zahl oben ist reiner Buchwert von ${openPositions} offenen Positionen.`
      : "Noch nichts abgeschlossen.";
  }
  const sign = realizedPnl >= 0 ? "+" : "−";
  const parts = [
    `Abgeschlossen: ${sign}${Math.abs(realizedPnl).toFixed(2).replace(".", ",")} über ${trades} Trades`,
  ];
  if (feesPaid > 0) {
    const share = Math.abs(realizedPnl) > 0 ? ` (Gebühren allein ${feesPaid.toFixed(2).replace(".", ",")})` : "";
    parts.push(share);
  }
  if (openPositions > 0) {
    parts.push(`. Die Rendite oben enthält zusätzlich ${openPositions} offene Position${openPositions === 1 ? "" : "en"}.`);
  } else {
    parts.push(".");
  }
  return parts.join("");
}

export function laneRows(lanes: ShortTermLane[]): LaneVerdictRow[] {
  return lanes.map((lane) => {
    // `significance.n` ist die Zahl, auf der das URTEIL beruht — nicht `stats.n_trades`,
    // das auch offene Positionen zählt. Ein Satz „über N Trades" muss dasselbe N nennen,
    // aus dem das Urteil stammt, sonst behauptet er eine Grundlage, die es nicht gibt.
    const trades = lane.significance?.n ?? 0;
    const verdict = lane.significance?.verdict ?? "zu wenige Trades";
    const returnPct = lane.total_return * 100;
    const benchmarkPct =
      lane.benchmark_return === null || lane.benchmark_return === undefined
        ? null
        : lane.benchmark_return * 100;
    const excessPct = benchmarkPct === null ? null : returnPct - benchmarkPct;
    return {
      lane: lane.lane,
      label: LANE_LABELS[lane.lane] ?? lane.lane,
      trades,
      verdict,
      promoted: Boolean(lane.promoted),
      returnPct,
      benchmarkPct,
      benchmarkTicker: lane.benchmark_ticker,
      excessPct,
      plain: plainVerdict(verdict, trades, excessPct),
      realizedPnl: lane.stats?.realized_pnl ?? 0,
      feesPaid: lane.stats?.fees_paid ?? 0,
      openPositions: lane.open_positions?.length ?? 0,
      realizedNote: realizedNote(
        lane.stats?.realized_pnl ?? 0,
        lane.stats?.fees_paid ?? 0,
        trades,
        lane.open_positions?.length ?? 0,
      ),
    };
  });
}

/** Der Satz über der Liste — die eigentliche Antwort auf „welche Aktie kurzfristig?". */
export function shortTermHeadline(rows: LaneVerdictRow[]): string {
  if (rows.length === 0) {
    return "Noch keine kurzfristige Strategie gemessen.";
  }
  const promoted = rows.filter((r) => r.promoted);
  if (promoted.length > 0) {
    return `${promoted.length} von ${rows.length} Strategien haben das Ergebnis-Gate bestanden und handeln Depot-Kapital.`;
  }
  const losing = rows.filter((r) => r.verdict === "negativ");
  if (losing.length > 0) {
    return `Keine der ${rows.length} kurzfristigen Strategien hat das Ergebnis-Gate bestanden — ${losing.length} verliert messbar. Deshalb steht hier keine Kaufliste.`;
  }
  return `Keine der ${rows.length} kurzfristigen Strategien hat das Ergebnis-Gate bestanden. Deshalb steht hier keine Kaufliste, sondern das, was bisher gemessen wurde.`;
}
