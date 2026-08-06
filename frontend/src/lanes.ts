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
      "Handelsschluss ist die Lane immer flach — es bleibt nie etwas über Nacht liegen.",
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
