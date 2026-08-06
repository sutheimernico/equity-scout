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
  /** Our own signal: in the entry zone AND the analysts see room. */
  inZone: StockBrief[];
  /** Highest analyst upside among the stocks NOT already shown above. */
  potential: StockBrief[];
  /** In the zone, but the analysts see no upside — counted, not listed. */
  contested: StockBrief[];
}

export function splitSections(briefs: StockBrief[]): Sections {
  // A stock the analysts see NO room in does not belong in a list whose job is "what
  // should I look at" — Nico asked twice why Yamato at −7 % was there at all, which is the
  // right question. Being in the entry zone is a timing statement; it does not make a
  // stock worth looking at on its own. Such titles move out of the list but are COUNTED,
  // because silently dropping a disagreement between our signal and the analysts would
  // hide exactly the thing that makes it interesting. Sorted by potential within.
  const zoned = briefs.filter((b) => b.in_zone);
  const inZone = zoned
    .filter((b) => (b.analyst_upside_pct ?? -1) > 0)
    .sort((a, b) => (b.analyst_upside_pct ?? 0) - (a.analyst_upside_pct ?? 0));
  const contested = zoned.filter((b) => (b.analyst_upside_pct ?? -1) <= 0);

  const potential = briefs
    .filter((b) => !b.in_zone)
    // A null upside means no coverage, not zero potential; a negative one contradicts
    // the heading. Both stay visible on their own card, just not as a highlight.
    .filter((b) => b.analyst_upside_pct !== null && b.analyst_upside_pct >= MIN_POTENTIAL_PCT)
    .sort((a, b) => (b.analyst_upside_pct ?? 0) - (a.analyst_upside_pct ?? 0))
    .slice(0, POTENTIAL_ROWS);

  return { inZone, potential, contested };
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
