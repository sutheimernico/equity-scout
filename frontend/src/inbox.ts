// Ordering of the decision inbox.
//
// Nico 2026-08-06: "die ganzen Einstiege schwach oben, aber Einstieg neutral dann weiter unten.
// Also macht schon Sinn, absteigend zu sortieren."
//
// The inbox arrives newest-first, which scattered the verdicts: a weak entry sat above an
// attractive one for no reason a reader could see. Best entry first is the order the list is
// actually read in.
//
// The BANDS are not re-derived here — they come from `pitch.compute_verdict`
// (src/equity_scout/pitch.py: <40 red, 40-70 yellow, ≥70 green, with a penalty for a very weak
// component). This module only orders what the server decided; rebuilding the thresholds in the
// frontend would let the two drift.

import type { Pitch } from "./api";

/** Best entry first. A pitch without a verdict is NOT guessed into a band — it sorts last. */
const VERDICT_RANK: Record<string, number> = { green: 0, yellow: 1, red: 2 };

export function verdictRank(verdict: string | null | undefined): number {
  if (!verdict) return 3; // unrated: own group at the end
  return VERDICT_RANK[verdict] ?? 3;
}

/** True when the pitch carries no verdict at all — rendered as its own labelled group so the
 *  absence is visible instead of looking like the weakest band. */
export function isUnrated(pitch: Pick<Pitch, "verdict">): boolean {
  return !pitch.verdict;
}

/** Sorted copy: verdict descending, newest first inside each band. */
export function sortByVerdict<T extends Pick<Pitch, "verdict" | "id">>(pitches: T[]): T[] {
  return [...pitches].sort((a, b) => {
    const byVerdict = verdictRank(a.verdict) - verdictRank(b.verdict);
    return byVerdict !== 0 ? byVerdict : b.id - a.id;
  });
}
