// What the three Day-Trader lanes actually do, in plain German.
//
// Nico 2026-08-06: "Crypto, dann Session, Swing — macht da irgendwie ein i für Info hin, dass
// sie deutlich erläutert sind und klarer abtrennen." The payload carries the raw key
// ("swing"), which says nothing, and three lanes × two sub-groups produced six
// indistinguishable headings.
//
// `label` is the short name the backend already uses (shortterm_storage.LANE_LABELS) and that
// the Telegram messages and the digest print. It is kept visible next to the plain name so a
// message about "Event-Swing" is still findable here.
//
// The numbers in `what` MUST stay equal to the lane rules they quote (same convention as
// MATERIAL_DELTA_WEIGHT in PhoneDepot.tsx):
//   swing   -> st_swing.PROFIT_TARGET 0.05, STOP_LOSS 0.03, MAX_HOLDING_CALENDAR_DAYS 7
//   session -> st_session.OPENING_RANGE_BARS 2 × 15 min, flat by the close (LAST_BAR_START)
//   crypto  -> st_crypto.ENTRY_LOOKBACK 20, EXIT_LOOKBACK 10, STOP_PCT 0.02

export interface LaneNote {
  /** Plain-language name — what the lane does, not what it is called. */
  name: string;
  /** The backend's short name, as it appears in Telegram and the digest. */
  label: string;
  /** Two or three sentences: when it buys, when it sells, what limits it. */
  what: string;
}

export const LANE_NOTES: Record<string, LaneNote> = {
  swing: {
    name: "Kauft nach guten Nachrichten",
    label: "Event-Swing",
    what:
      "Steigt ein, wenn ein Unternehmen die Gewinnerwartung übertrifft oder seine Prognose " +
      "erhöht. Verkauft bei +5 % Gewinn, bei −3 % Verlust oder spätestens nach sieben Tagen.",
  },
  session: {
    name: "Handelt nur innerhalb eines Tages",
    label: "Intraday-Session",
    what:
      "Merkt sich die Kursspanne der ersten 30 Handelsminuten und kauft, wenn der Kurs " +
      "darüber ausbricht. Ziel und Stop richten sich nach der Breite dieser Spanne. Zum " +
      "Handelsschluss ist die Lane immer flach — es bleibt nie etwas über Nacht liegen. " +
      "Pausiert seit 17.08.2026: Die Einstiegsregel ist an 1.684 Ausbrüchen widerlegt, " +
      "und auch mit Halten über Nacht bringt sie nichts, was ein Einstieg ohne Regel " +
      "nicht auch bekäme. Das Buch bleibt sichtbar.",
  },
  crypto: {
    name: "Folgt Krypto-Ausbrüchen",
    label: "Crypto",
    what:
      "Kauft, wenn eine Kryptowährung das höchste Niveau der letzten 20 Tage erreicht. " +
      "Verkauft am Tief der letzten 10 Tage oder 2 % unter dem Einstieg. Handelt rund um " +
      "die Uhr, auch am Wochenende.",
  },
};

/** The plain name, or the raw key when a lane has no entry — never an invented name. */
export function laneName(lane: string): string {
  return LANE_NOTES[lane]?.name ?? lane;
}

/** "2 laufen noch" / "keine offene Position" — a count reads as information, whereas
 *  "Läuft noch" three times over reads as a repetition (Nico 2026-08-06). */
export function runningLabel(count: number): string {
  if (count === 0) return "keine offene Position";
  return count === 1 ? "1 läuft noch" : `${count} laufen noch`;
}

export function closedLabel(count: number): string {
  if (count === 0) return "noch nichts abgeschlossen";
  return count === 1 ? "1 abgeschlossen" : `${count} abgeschlossen`;
}

/** The three lanes read as one book, the way Long Term already does (Nico 2026-08-16: "ich
 *  hätte gerne so eine Zeile, wo ich alles direkt sehe … wie viel Plus ich gemacht hab seit
 *  Start").
 *
 *  Deliberately WITHOUT a benchmark: two lanes measure against the S&P and one against
 *  Bitcoin, so a single "vs. market" number would average two different questions. The
 *  comparison stays on each lane, where its benchmark is named. */
export function shortTermTotals(
  lanes: { equity: number; initial_capital: number }[],
): { equity: number; invested: number; totalReturn: number | null } {
  const equity = lanes.reduce((sum, lane) => sum + lane.equity, 0);
  const invested = lanes.reduce((sum, lane) => sum + lane.initial_capital, 0);
  return { equity, invested, totalReturn: invested > 0 ? equity / invested - 1 : null };
}

/** Has this lane's result resolved, or is it still noise?
 *
 *  The page used to answer this from the calendar ("Messtag 25 von 60"), which on 2026-08-16
 *  told Nico "too short for a verdict" about the crypto lane — while the trade-based test had
 *  long since settled it at p = 0.0003. Trades are what the lane produces, days are not. */
export function verdictLine(significance: {
  verdict: string;
  significant: boolean;
  trades_missing: number | null;
  n: number;
}): { text: string; settled: boolean } {
  if (significance.significant) {
    const direction = significance.verdict === "positiv" ? "verdient Geld" : "verliert Geld";
    return { text: `Urteil steht: ${direction}`, settled: true };
  }
  if (significance.verdict === "kein messbarer Effekt") {
    return { text: "Kein messbarer Unterschied — zu nah an null", settled: false };
  }
  const missing = significance.trades_missing;
  if (missing && missing > 0) {
    return { text: `Noch kein Urteil — ${missing} Trades fehlen`, settled: false };
  }
  return { text: `Noch kein Urteil — erst ${significance.n} Trades`, settled: false };
}
