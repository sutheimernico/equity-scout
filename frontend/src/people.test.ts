import { describe, expect, it } from "vitest";

import type { EvidenceEvent } from "./api";
import {
  buildBuckets,
  congressByStock,
  delayNote,
  moveLabel,
  personView,
  type PersonBucket,
} from "./people";

const congress = (
  ticker: string,
  politician: string,
  date: string,
  extra: Record<string, unknown> = {},
): EvidenceEvent => ({
  source: "congress",
  ticker,
  event_key: `${politician}-${date}`,
  event_date: date,
  details: { politician, chamber: "senate", party: "R", ...extra },
});

const voice = (ticker: string, speaker: string, date: string): EvidenceEvent => ({
  source: "voice",
  ticker,
  event_key: `${speaker}-${date}`,
  event_date: date,
  details: { speaker, kind: "context", headline: "…" },
});

describe("congressByStock", () => {
  it("groups congress buys by stock, most-bought first", () => {
    const rows = congressByStock({
      INTC: [
        congress("INTC", "Tuberville", "2026-08-05"),
        congress("INTC", "Pelosi", "2026-08-01"),
      ],
      WBA: [congress("WBA", "Tuberville", "2026-08-06")],
      FOA: [voice("FOA", "Ackman", "2026-08-06")], // no congress buy -> not listed
    });
    expect(rows.map((r) => r.ticker)).toEqual(["INTC", "WBA"]);
    expect(rows[0]!.buys).toBe(2);
    expect(rows[0]!.buyers).toEqual(["Tuberville", "Pelosi"]);
    expect(rows[0]!.latest).toBe("2026-08-05");
  });

  it("dedupes repeat buyers but counts every buy", () => {
    const rows = congressByStock({
      INTC: [
        congress("INTC", "Tuberville", "2026-08-05"),
        congress("INTC", "Tuberville", "2026-08-04"),
      ],
    });
    expect(rows[0]!.buys).toBe(2);
    expect(rows[0]!.buyers).toEqual(["Tuberville"]);
  });
});

describe("person grouping", () => {
  it("labels congress buys with the amount and the reporting delay", () => {
    const event = congress("WBA", "Tuberville", "2026-08-05", {
      amount_range: "$15,001 - $50,000",
      days_to_file: 867,
    });
    expect(moveLabel(event)).toBe("hat gekauft ($15,001 - $50,000)");
    expect(delayNote(event)).toBe("erst 867 Tage nach dem Handel gemeldet");
  });

  it("sorts persons by their newest event", () => {
    const buckets = buildBuckets({
      INTC: [congress("INTC", "Pelosi", "2026-08-01")],
      WBA: [congress("WBA", "Tuberville", "2026-08-06")],
    });
    expect(buckets.map((b) => b.person)).toEqual(["Tuberville", "Pelosi"]);
  });
});

describe("buildBuckets: actions before mentions", () => {
  // Measured 2026-08-23: 475 of 589 evidence events are press mentions, and the biggest
  // card (Michael Burry, 95 events) showed six of them while his disclosed buys sat
  // behind "+89 weitere anzeigen". A card that answers "wer kauft" with six mentions
  // answers nothing.
  const insider = (ticker: string, who: string, date: string): EvidenceEvent => ({
    source: "insider",
    ticker,
    event_key: `${who}-${date}`,
    event_date: date,
    details: { insider: who },
  });
  const call = (ticker: string, speaker: string, date: string): EvidenceEvent => ({
    source: "voice",
    ticker,
    event_key: `${speaker}-call-${date}`,
    event_date: date,
    details: { speaker, kind: "call", direction: "bullish", headline: "…" },
  });

  it("puts a filing above newer mentions of the same person", () => {
    const [bucket] = buildBuckets({
      AAA: [
        voice("AAA", "Michael Burry", "2026-08-21"),
        voice("AAA", "Michael Burry", "2026-08-20"),
        insider("AAA", "Michael Burry", "2026-08-02"),
      ],
    });
    expect(bucket.events.map((e) => e.event_key)).toEqual([
      "Michael Burry-2026-08-02", // the actual purchase, older but the answer
      "Michael Burry-2026-08-21",
      "Michael Burry-2026-08-20",
    ]);
  });

  it("counts a directed call as an action, a plain mention not", () => {
    const [bucket] = buildBuckets({
      AAA: [voice("AAA", "Ackman", "2026-08-21"), call("AAA", "Ackman", "2026-08-19")],
    });
    expect(bucket.events[0].event_key).toBe("Ackman-call-2026-08-19");
  });

  it("orders the CARDS by real recency, not by the action-first sort", () => {
    // Otherwise a person whose only filing is months old would jump ahead of someone
    // active today — the card order is about who moved recently.
    const buckets = buildBuckets({
      AAA: [insider("AAA", "Alt", "2026-01-02")],
      BBB: [voice("BBB", "Neu", "2026-08-21")],
    });
    expect(buckets.map((b) => b.person)).toEqual(["Neu", "Alt"]);
  });
});

describe("personView", () => {
  const card = (person: string, newest: string) =>
    ({ person, role: "Investor / Stimme", events: [], newest }) as PersonBucket;

  it("caps the card list and names what it withheld", () => {
    // 23 people carried 589 events on 2026-08-23; with the voice list capped, these
    // cards were what remained of the 68 005 px page.
    const buckets = Array.from({ length: 23 }, (_, i) =>
      card(`P${i}`, `2026-08-${String(21 - i).padStart(2, "0")}`),
    );
    const view = personView(buckets, 10);
    expect(view.shown).toHaveLength(10);
    expect(view.hidden).toBe(13);
    expect(view.shown[0].person).toBe("P0"); // buildBuckets already sorted by recency
  });

  it("shows everything when the cap is raised past the list", () => {
    const view = personView([card("A", "2026-08-01")], 10);
    expect(view.shown).toHaveLength(1);
    expect(view.hidden).toBe(0);
  });
});
