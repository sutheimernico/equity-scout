// Pure grouping logic behind the Personen view (extracted from PeoplePanel 2026-08-07
// so the congress aggregation is unit-testable). Two projections over the same
// evidence events: by PERSON (who did what) and by STOCK for congress buys
// (Nico: "mach mal eine Kategorie Kongressmitglieder und dann einfach Screen,
// welche Aktien die gekauft haben").

import type { EvidenceEvent } from "./api";

export interface PersonBucket {
  person: string;
  role: string; // "Kongress (Senat, R)" | "Investor / Stimme" | "Insider" | "Fonds"
  events: EvidenceEvent[];
  newest: string;
}

export function roleOf(event: EvidenceEvent): string {
  const details = event.details;
  if (event.source === "congress") {
    const chamber = details.chamber === "senate" ? "Senat" : "Repräsentantenhaus";
    const party = details.party ? `, ${String(details.party)}` : "";
    return `Kongress (${chamber}${party})`;
  }
  if (event.source === "insider") return "Insider (Führungskraft)";
  if (event.source === "13f") return "Fonds";
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
  if (event.source === "congress") {
    const amount = details.amount_range ? ` (${String(details.amount_range)})` : "";
    return `hat gekauft${amount}`;
  }
  if (event.source === "insider") return "hat als Insider gekauft";
  if (event.source === "13f") {
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
    bucket.events.sort((a, b) => String(b.event_date).localeCompare(String(a.event_date)));
    bucket.newest = String(bucket.events[0]?.event_date ?? "");
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
      if (event.source !== "congress") continue;
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
