import { describe, expect, it } from "vitest";

import type { EvidenceEvent } from "./api";
import { buildBuckets, congressByStock, delayNote, moveLabel } from "./people";

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
