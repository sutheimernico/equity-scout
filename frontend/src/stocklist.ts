// How the phone's stock tab is divided. Measured on 2026-08-05, the funnel's own order
// (in-zone first, then score) puts a −7 % analyst upside in row one and +69 % in row
// three — so one list cannot answer both "what is buyable now" (our signal) and "what
// has potential" (third-party consensus). Two labelled sections keep both honest and
// keep the fremde Meinung from outranking our own.
import type { StockBrief } from "./api";

// Four rows is one thumb-scroll on a 390 px screen; more turns the highlight into a list.
const POTENTIAL_ROWS = 4;

export interface Sections {
  /** Our own signal: the price sits inside the support-derived entry zone. */
  inZone: StockBrief[];
  /** Highest analyst upside among the stocks NOT already shown above. */
  potential: StockBrief[];
}

export function splitSections(briefs: StockBrief[]): Sections {
  const inZone = briefs.filter((b) => b.in_zone).sort((a, b) => b.score - a.score);

  const potential = briefs
    .filter((b) => !b.in_zone)
    // A null upside means no coverage, not zero potential; a negative one contradicts
    // the heading. Both stay visible on their own card, just not as a highlight.
    .filter((b) => b.analyst_upside_pct !== null && b.analyst_upside_pct > 0)
    .sort((a, b) => (b.analyst_upside_pct ?? 0) - (a.analyst_upside_pct ?? 0))
    .slice(0, POTENTIAL_ROWS);

  return { inZone, potential };
}

/** The entry state in as few words as a list row can carry.
 *
 * The backend's `zone_verdict` is a full sentence ("69 % über der Zone — zu teuer"). The
 * list needs the fact, not the reason: everything after the em dash is explanation and
 * belongs in the detail view, where the zone meter and the bounds live. "im
 * Einstiegsbereich" loses its preposition so the chip reads as a state, not a sentence
 * fragment.
 */
export function shortVerdict(brief: StockBrief): string {
  const head = brief.zone_verdict.split("—")[0].trim();
  return head.startsWith("im ") ? head.slice(3) : head;
}
