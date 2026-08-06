// How the phone's stock tab is divided. Measured on 2026-08-05, the funnel's own order
// (in-zone first, then score) puts a −7 % analyst upside in row one and +69 % in row
// three — so one list cannot answer both "what is buyable now" (our signal) and "what
// has potential" (third-party consensus). Two labelled sections keep both honest and
// keep the fremde Meinung from outranking our own.
import type { StockBrief } from "./api";

// Four rows is one thumb-scroll on a 390 px screen; more turns the highlight into a list.
const POTENTIAL_ROWS = 4;

// Nico 2026-08-06: "ich würd alles ab Potenzial dreißig plus filtern" — the section is
// there to answer "which ones should I actually look at", and a +9 % consensus does not
// earn a highlight slot. Only this section is gated: the entry section leads with OUR
// signal, where a small or negative upside is information, not a reason to hide the row.
const MIN_POTENTIAL_PCT = 30;

export interface Sections {
  /** Our own signal: the price sits inside the support-derived entry zone. */
  inZone: StockBrief[];
  /** Highest analyst upside among the stocks NOT already shown above. */
  potential: StockBrief[];
}

export function splitSections(briefs: StockBrief[]): Sections {
  // Sorted by POTENTIAL, not by our score (2026-08-06). Sorting by score put Yamato at
  // −7 % in row one and Nico's reaction was the right one: "dann ist ja scheiße, warum
  // sollte ich die Aktie dann kaufen?" Being in the entry zone says the timing is fine, it
  // does not say the stock is worth buying — so a title the analysts see no room in
  // belongs at the bottom of the section, not at the top. It stays visible because our own
  // signal did flag it and hiding a disagreement would be dishonest.
  const inZone = briefs
    .filter((b) => b.in_zone)
    .sort((a, b) => (b.analyst_upside_pct ?? -999) - (a.analyst_upside_pct ?? -999));

  const potential = briefs
    .filter((b) => !b.in_zone)
    // A null upside means no coverage, not zero potential; a negative one contradicts
    // the heading. Both stay visible on their own card, just not as a highlight.
    .filter((b) => b.analyst_upside_pct !== null && b.analyst_upside_pct >= MIN_POTENTIAL_PCT)
    .sort((a, b) => (b.analyst_upside_pct ?? 0) - (a.analyst_upside_pct ?? 0))
    .slice(0, POTENTIAL_ROWS);

  return { inZone, potential };
}

/** The entry state in as few words as a list row can carry.
 *
 * The backend's `zone_verdict` states the timing fact ("69 % über der Einstiegszone"). The
 * list needs the fact, not the reason: everything after the em dash is explanation and
 * belongs in the detail view, where the zone meter and the bounds live. "im
 * Einstiegsbereich" loses its preposition so the chip reads as a state, not a sentence
 * fragment.
 */
export function shortVerdict(brief: StockBrief): string {
  const head = brief.zone_verdict.split("—")[0].trim();
  return head.startsWith("im ") ? head.slice(3) : head;
}
