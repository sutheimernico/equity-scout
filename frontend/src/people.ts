// Pure grouping logic behind the Personen view (extracted from PeoplePanel 2026-08-07
// so the congress aggregation is unit-testable). Two projections over the same
// evidence events: by PERSON (who did what) and by STOCK for congress buys
// (Nico: "mach mal eine Kategorie Kongressmitglieder und dann einfach Screen,
// welche Aktien die gekauft haben").

import type { EvidenceEvent } from "./api";

// The `source` strings the API actually emits — mirrored from evidence/base.py, where the
// 13F constant is SOURCE_13F = "thirteen_f". Named here because a literal got it wrong:
// three checks compared against "13f", which nothing ever sends, so all 80 fund filings
// (Berkshire, Baupost, Appaloosa, Duquesne, Himalaya, Third Point) fell through to the
// press-mention branch and were labelled "wird in der Presse erwähnt" — in the view that
// asks who is BUYING. Found 2026-08-23 by counting the API against the code.
export const SOURCE = {
  congress: "congress",
  insider: "insider",
  fund: "thirteen_f",
  voice: "voice",
} as const;

export interface PersonBucket {
  person: string;
  role: string; // "Kongress (Senat, R)" | "Investor / Stimme" | "Insider" | "Fonds"
  events: EvidenceEvent[];
  newest: string;
}

export function roleOf(event: EvidenceEvent): string {
  const details = event.details;
  if (event.source === SOURCE.congress) {
    const chamber = details.chamber === "senate" ? "Senat" : "Repräsentantenhaus";
    const party = details.party ? `, ${String(details.party)}` : "";
    return `Kongress (${chamber}${party})`;
  }
  if (event.source === SOURCE.insider) return "Insider (Führungskraft)";
  if (event.source === SOURCE.fund) return "Fonds";
  return "Investor / Stimme";
}

export function personOf(event: EvidenceEvent): string | null {
  const details = event.details;
  const raw = details.politician ?? details.insider ?? details.fund ?? details.speaker;
  return raw ? String(raw) : null;
}

/** What this person DID, in one plain clause — from the recorded facts only. */
export function moveLabel(event: EvidenceEvent): string {
  const details = event.details;
  if (event.source === SOURCE.congress) {
    const amount = details.amount_range ? ` (${String(details.amount_range)})` : "";
    return `hat gekauft${amount}`;
  }
  if (event.source === SOURCE.insider) return "hat als Insider gekauft";
  if (event.source === SOURCE.fund) {
    return details.change === "new" ? "neue Position gemeldet" : "Position aufgestockt";
  }
  const kind = String(details.kind ?? "context");
  if (kind === "context") return "wird in der Presse erwähnt";
  return details.direction === "bullish"
    ? "äußert sich positiv (Kauf/Empfehlung)"
    : "äußert sich negativ (Verkauf/Short/Warnung)";
}

/** The reporting delay, said out loud: a congress trade from March filed in August is
 *  history, not news — hiding that would turn a disclosure into a fake signal. */
export function delayNote(event: EvidenceEvent): string | null {
  const days = event.details.days_to_file;
  if (typeof days !== "number" || days <= 0) return null;
  return days >= 45
    ? `erst ${days} Tage nach dem Handel gemeldet`
    : `${days} Tage nach dem Handel gemeldet`;
}


/** Did this person DO something, or were they merely mentioned?
 *
 * A card shows the first `MAX_MOVES_SHOWN` of a person's events, and the list used to be
 * sorted by date alone. Measured on 2026-08-23: Michael Burry carried 95 events and
 * 475 of the 589 evidence events are press mentions — so the six visible rows on the
 * biggest cards were mentions, while the actual disclosed purchases sat behind
 * "+89 weitere anzeigen". The view is called "Wer kauft gerade was"; a filing answers
 * that question and a mention does not, so filings sort first even when older. The
 * reporting delay stays on every row, so nothing here pretends to be fresh.
 */
export function isAction(event: EvidenceEvent): boolean {
  if (
    event.source === SOURCE.congress ||
    event.source === SOURCE.insider ||
    event.source === SOURCE.fund
  ) {
    return true;
  }
  return String(event.details.kind ?? "context") !== "context";
}

export function buildBuckets(
  eventsByTicker: Record<string, EvidenceEvent[]>,
): PersonBucket[] {
  const byPerson = new Map<string, PersonBucket>();
  for (const events of Object.values(eventsByTicker)) {
    for (const event of events) {
      const person = personOf(event);
      if (!person) continue;
      const bucket = byPerson.get(person) ?? {
        person,
        role: roleOf(event),
        events: [],
        newest: "",
      };
      bucket.events.push(event);
      byPerson.set(person, bucket);
    }
  }
  for (const bucket of byPerson.values()) {
    // Actions before mentions, newest first inside each group (see `isAction`).
    bucket.events.sort(
      (a, b) =>
        Number(isAction(b)) - Number(isAction(a)) ||
        String(b.event_date).localeCompare(String(a.event_date)),
    );
    // `newest` orders the CARDS and must stay a pure date, independent of the sort above —
    // otherwise a person whose only filing is old would sink below one merely mentioned.
    bucket.newest = bucket.events.reduce(
      (max, e) => (String(e.event_date) > max ? String(e.event_date) : max),
      "",
    );
  }
  return [...byPerson.values()].sort((a, b) => b.newest.localeCompare(a.newest));
}

export interface CongressStockAgg {
  ticker: string;
  /** Number of reported congress purchases in the window. */
  buys: number;
  /** Unique buyer names, first-appearance order. */
  buyers: string[];
  /** Newest event date. */
  latest: string;
}

/** Congress buys regrouped by STOCK: which names are members of congress buying.
 *  Most-bought first (then newest) — a count of disclosures, never a signal. */
export function congressByStock(
  eventsByTicker: Record<string, EvidenceEvent[]>,
): CongressStockAgg[] {
  const byStock = new Map<string, CongressStockAgg>();
  for (const [ticker, events] of Object.entries(eventsByTicker)) {
    for (const event of events) {
      if (event.source !== SOURCE.congress) continue;
      const agg = byStock.get(ticker) ?? { ticker, buys: 0, buyers: [], latest: "" };
      agg.buys += 1;
      const who = personOf(event);
      if (who && !agg.buyers.includes(who)) agg.buyers.push(who);
      const date = String(event.event_date);
      if (date > agg.latest) agg.latest = date;
      byStock.set(ticker, agg);
    }
  }
  return [...byStock.values()].sort(
    (a, b) => b.buys - a.buys || b.latest.localeCompare(a.latest),
  );
}


/** How many person cards the phone shows before asking. Same reasoning as VOICE_PAGE and
 *  DECIDED_PAGE: on 2026-08-23 this page stood 68 005 px tall, and the person list was
 *  the half that survived capping the voices. Cards are sorted newest-move-first, so the
 *  cap keeps who moved most recently. */
export const PERSON_PAGE = 10;

export interface PersonView {
  shown: PersonBucket[];
  hidden: number;
}

export function personView(
  buckets: PersonBucket[],
  limit: number = PERSON_PAGE,
): PersonView {
  return {
    shown: buckets.slice(0, limit),
    hidden: Math.max(0, buckets.length - limit),
  };
}
