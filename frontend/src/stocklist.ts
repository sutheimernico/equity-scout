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
