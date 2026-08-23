// Pure list logic behind "Wer kauft? · Stimmen" (2026-08-23). Extracted so the cap and
// the direction filter are unit-testable, same split as people.ts.
//
// Why this exists: the panel rendered EVERY voice event as a full card — 262 of them on
// 2026-08-23, which made the page 68 005 px tall on a 390 px phone (80 screen lengths).
// 205 of the 262 voice events are "context" ("wird in der Presse erwähnt"), so the view
// promising "was bekannte Investoren öffentlich sagen" was four fifths made of cards
// saying that no direction was recognisable. That is Nico's "man checkt nix" in numbers.
// (Corrected 2026-08-23 in review: an earlier note said "475 of 589 evidence events" —
// that count defaulted sources without a `kind` field to "context" and is wrong. The
// four-fifths share holds for the voice events this panel actually shows.)

import type { EvidenceEvent } from "./api";

/** How many cards a phone list shows before asking. Deliberately small: the point of the
 *  list is to be readable, and everything beyond is one tap away. */
export const VOICE_PAGE = 15;

export type VoiceFilter = "gerichtet" | "alle";

export function isDirected(event: EvidenceEvent): boolean {
  return String(event.details.kind ?? "context") !== "context";
}

/** All voice events, directed calls first, newest first within each group. */
export function voiceRows(
  eventsByTicker: Record<string, EvidenceEvent[]>,
): EvidenceEvent[] {
  const rows = Object.values(eventsByTicker)
    .flat()
    .filter((e) => e.source === "voice");
  const rank = (e: EvidenceEvent) => (isDirected(e) ? 0 : 1);
  return rows.sort(
    (a, b) => rank(a) - rank(b) || String(b.event_date).localeCompare(String(a.event_date)),
  );
}

export interface VoiceView {
  shown: EvidenceEvent[];
  hidden: number;
  directed: number;
  total: number;
}

/** What the panel actually renders: filtered, capped, and the counts the tabs need.
 *  `limit` is the current cap — the caller raises it when "mehr anzeigen" is tapped. */
export function voiceView(
  rows: EvidenceEvent[],
  filter: VoiceFilter,
  limit: number,
): VoiceView {
  const directed = rows.filter(isDirected);
  const pool = filter === "gerichtet" ? directed : rows;
  return {
    shown: pool.slice(0, limit),
    hidden: Math.max(0, pool.length - limit),
    directed: directed.length,
    total: rows.length,
  };
}
