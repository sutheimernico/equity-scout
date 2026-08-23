import { describe, expect, it } from "vitest";

import type { EvidenceEvent } from "./api";
import { VOICE_PAGE, isDirected, voiceRows, voiceView } from "./voices";

function event(
  ticker: string,
  date: string,
  kind: string,
  source = "voice",
): EvidenceEvent {
  return {
    ticker,
    event_date: date,
    event_key: `${ticker}-${date}-${kind}`,
    source,
    details: { kind, speaker: "Someone", headline: "h" },
  } as unknown as EvidenceEvent;
}

describe("voiceRows", () => {
  it("keeps only voice events and puts directed calls first", () => {
    const rows = voiceRows({
      A: [event("A", "2026-08-01", "context"), event("A", "2026-08-05", "call")],
      B: [event("B", "2026-08-09", "context"), event("B", "2026-08-02", "insider", "insider")],
    });
    expect(rows.map((r) => r.event_key)).toEqual([
      "A-2026-08-05-call",
      "B-2026-08-09-context",
      "A-2026-08-01-context",
    ]);
  });

  it("treats anything that is not context as a direction", () => {
    expect(isDirected(event("A", "2026-08-01", "call"))).toBe(true);
    expect(isDirected(event("A", "2026-08-01", "call_bearish"))).toBe(true);
    expect(isDirected(event("A", "2026-08-01", "context"))).toBe(false);
  });
});

describe("voiceView", () => {
  const rows = [
    ...Array.from({ length: 5 }, (_, i) => event("D", `2026-08-1${i}`, "call")),
    ...Array.from({ length: 40 }, (_, i) => event("C", `2026-07-${10 + i}`, "context")),
  ];

  it("defaults to the directed calls, which is what the view promises to show", () => {
    // The measured reality on 2026-08-23: 57 directed of 262 voice events. A list that
    // leads with the other 205 is a list about nothing.
    const view = voiceView(rows, "gerichtet", VOICE_PAGE);
    expect(view.shown).toHaveLength(5);
    expect(view.shown.every(isDirected)).toBe(true);
    expect(view.hidden).toBe(0);
    expect(view.directed).toBe(5);
    expect(view.total).toBe(45);
  });

  it("caps the full list and reports what it withheld", () => {
    const view = voiceView(rows, "alle", VOICE_PAGE);
    expect(view.shown).toHaveLength(VOICE_PAGE);
    expect(view.hidden).toBe(45 - VOICE_PAGE);
  });

  it("shows everything once the cap is raised past the pool", () => {
    const view = voiceView(rows, "alle", 1000);
    expect(view.shown).toHaveLength(45);
    expect(view.hidden).toBe(0);
  });

  it("counts stay about the whole pool, not the visible page", () => {
    // Otherwise the tab label would shrink as you page, which reads like data vanishing.
    const view = voiceView(rows, "gerichtet", 2);
    expect(view.directed).toBe(5);
    expect(view.total).toBe(45);
  });
});
