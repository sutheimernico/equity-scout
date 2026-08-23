// Ordering and grouping of the decision inbox.
//
// Nico 2026-08-06 (round two): "es ist nicht absteigend sortiert, also nach diesem Score".
// Round one sorted by verdict band but kept newest-first INSIDE each band — with the score
// as the most prominent number on the card, 50 → 60 → 61 → 47 still read as no order at
// all. Inside a band the score now descends, and each band gets a visible group heading so
// the band-first order is readable instead of implicit.
//
// The BANDS are not re-derived here — they come from `pitch.compute_verdict`
// (src/equity_scout/pitch.py: <40 red, 40-70 yellow, ≥70 green, with a penalty for a very
// weak component — which is why a 61 can sit in "schwach" while a 60 is "neutral"; the
// card's verdict_why carries that reason). This module only orders and groups what the
// server decided.

import type { Pitch } from "./api";

export type InboxGroupKey = "green" | "yellow" | "red" | "unrated" | "decided";

/** Display order of the groups: best entry first, unrated after the rated ones
 *  (absence of a rating is NOT the weakest band), decided history last. */
const GROUP_ORDER: InboxGroupKey[] = ["green", "yellow", "red", "unrated", "decided"];

export const GROUP_HEADINGS: Record<InboxGroupKey, { title: string; sub: string }> = {
  green: {
    title: "🟢 Einstieg attraktiv",
    sub: "Modell-Score 70–100 — innerhalb der Gruppe absteigend sortiert.",
  },
  yellow: {
    title: "🟡 Einstieg neutral",
    sub: "Modell-Score 40–70. Ein höherer Score kann hier landen, wenn ein einzelnes Signal sehr schwach ist — der Grund steht auf der Karte.",
  },
  red: {
    title: "🔴 Einstieg schwach",
    sub: "Modell-Score unter 40, oder ein sehr schwaches Einzelsignal bremst.",
  },
  unrated: {
    title: "Ohne Bewertung",
    sub: "Für diese Titel fehlt ein Einstiegs-Score — ältere Pitches von vor der Bewertung.",
  },
  decided: {
    title: "Bereits entschieden oder verfallen",
    sub: "Deine bisherigen Entscheidungen und Pitches, deren Titel nicht mehr beobachtet wird — nur Notizen, kein realer Handel.",
  },
};

export function groupKey(pitch: Pick<Pitch, "verdict" | "status">): InboxGroupKey {
  if (pitch.status !== "open") return "decided";
  if (!pitch.verdict) return "unrated";
  return pitch.verdict;
}

type Sortable = Pick<Pitch, "verdict" | "status" | "composite" | "id">;

/** Sorted copy: open before decided, best band first, score descending inside a band
 *  (decided: newest decision first via id). */
export function sortByVerdict<T extends Sortable>(pitches: T[]): T[] {
  return [...pitches].sort((a, b) => {
    const byGroup = GROUP_ORDER.indexOf(groupKey(a)) - GROUP_ORDER.indexOf(groupKey(b));
    if (byGroup !== 0) return byGroup;
    if (groupKey(a) === "decided") return b.id - a.id;
    const byScore = b.composite - a.composite;
    return byScore !== 0 ? byScore : b.id - a.id;
  });
}

/** How many decided/expired pitches the phone shows before asking. The open ones are
 *  never capped — they are the whole point of the screen. */
export const DECIDED_PAGE = 5;

export interface InboxView<T> {
  /** Sorted, with the decided tail capped. */
  shown: T[];
  /** How many decided pitches are withheld. */
  hidden: number;
}

/** The list the panel renders. Measured 2026-08-23: 30 pitches, 28 of them expired —
 *  the view was 10 158 px tall on a 390 px phone, and twelve of those thirteen screens
 *  were history nobody scrolls to. Capping the tail is not hiding data: the count is
 *  named on the button that reveals it. */
export function inboxView<T extends Sortable>(
  pitches: T[],
  decidedLimit: number = DECIDED_PAGE,
): InboxView<T> {
  const sorted = sortByVerdict(pitches);
  const open = sorted.filter((p) => groupKey(p) !== "decided");
  const decided = sorted.filter((p) => groupKey(p) === "decided");
  return {
    shown: [...open, ...decided.slice(0, decidedLimit)],
    hidden: Math.max(0, decided.length - decidedLimit),
  };
}
