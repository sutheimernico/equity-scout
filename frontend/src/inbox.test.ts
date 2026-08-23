import { describe, expect, it } from "vitest";

import {
  DECIDED_PAGE,
  GROUP_HEADINGS,
  groupKey,
  inboxView,
  sortByVerdict,
} from "./inbox";

const pitch = (
  id: number,
  verdict: "green" | "yellow" | "red" | null,
  composite = 0.5,
  status: "open" | "buy" | "pass" | "later" = "open",
) => ({ id, verdict, composite, status }) as Parameters<typeof sortByVerdict>[0][number];

describe("sortByVerdict", () => {
  it("puts the best entry first, not the newest", () => {
    const sorted = sortByVerdict([pitch(1, "red"), pitch(2, "green"), pitch(3, "yellow")]);
    expect(sorted.map((p) => p.verdict)).toEqual(["green", "yellow", "red"]);
  });

  it("sorts by score descending inside one band (Nico 2026-08-06, round two)", () => {
    const sorted = sortByVerdict([
      pitch(9, "yellow", 0.5),
      pitch(5, "yellow", 0.6),
      pitch(7, "yellow", 0.47),
    ]);
    expect(sorted.map((p) => p.id)).toEqual([5, 9, 7]);
  });

  it("breaks a score tie by newest first", () => {
    const sorted = sortByVerdict([pitch(5, "yellow", 0.5), pitch(9, "yellow", 0.5)]);
    expect(sorted.map((p) => p.id)).toEqual([9, 5]);
  });

  it("sorts pitches without a verdict after the rated ones instead of guessing a band", () => {
    const sorted = sortByVerdict([pitch(1, null), pitch(2, "red")]);
    expect(sorted.map((p) => p.verdict)).toEqual(["red", null]);
  });

  it("moves decided pitches behind every open one, newest decision first", () => {
    const sorted = sortByVerdict([
      pitch(1, "green", 0.9, "buy"),
      pitch(4, "green", 0.9, "pass"),
      pitch(2, "red", 0.1),
      pitch(3, null),
    ]);
    expect(sorted.map((p) => p.id)).toEqual([2, 3, 4, 1]);
  });

  it("does not mutate the input", () => {
    const input = [pitch(1, "red"), pitch(2, "green")];
    sortByVerdict(input);
    expect(input.map((p) => p.verdict)).toEqual(["red", "green"]);
  });
});

describe("groupKey", () => {
  it("maps status and verdict to the five display groups", () => {
    expect(groupKey({ status: "open", verdict: "green" })).toBe("green");
    expect(groupKey({ status: "open", verdict: null })).toBe("unrated");
    expect(groupKey({ status: "buy", verdict: "green" })).toBe("decided");
    expect(groupKey({ status: "expired", verdict: "green" })).toBe("decided");
  });

  it("has a heading for every group", () => {
    for (const key of ["green", "yellow", "red", "unrated", "decided"] as const) {
      expect(GROUP_HEADINGS[key].title).toBeTruthy();
      expect(GROUP_HEADINGS[key].sub).toBeTruthy();
    }
  });
});

describe("inboxView", () => {
  // Measured 2026-08-23 against the live API: 30 pitches, 28 expired, 1 open, 1 bought.
  // The panel rendered all of them and stood 10 158 px tall on a 390 px phone.
  // status "pass" stands in for every non-open state; groupKey only asks "open or not".
  const decided = (id: number) => pitch(id, null, 0.5, "pass");
  const open = (id: number) => pitch(id, "green", 0.5, "open");

  it("never caps the open pitches — they are the reason the screen exists", () => {
    const many = Array.from({ length: 12 }, (_, i) => open(i + 1));
    const view = inboxView(many);
    expect(view.shown).toHaveLength(12);
    expect(view.hidden).toBe(0);
  });

  it("caps the decided tail and says how many it withheld", () => {
    const pitches = [
      open(100),
      ...Array.from({ length: 28 }, (_, i) => decided(i + 1)),
    ];
    const view = inboxView(pitches);
    expect(view.shown).toHaveLength(1 + DECIDED_PAGE);
    expect(view.hidden).toBe(28 - DECIDED_PAGE);
    expect(view.shown[0].id).toBe(100); // the open one still leads
  });

  it("keeps the newest decisions when it caps", () => {
    const view = inboxView([decided(1), decided(9), decided(5)], 2);
    expect(view.shown.map((p) => p.id)).toEqual([9, 5]);
    expect(view.hidden).toBe(1);
  });

  it("a raised limit reveals the rest", () => {
    const pitches = Array.from({ length: 8 }, (_, i) => decided(i + 1));
    expect(inboxView(pitches, 100).shown).toHaveLength(8);
    expect(inboxView(pitches, 100).hidden).toBe(0);
  });
});
