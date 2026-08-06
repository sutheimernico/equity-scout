import { describe, expect, it } from "vitest";

import { isUnrated, sortByVerdict, verdictRank } from "./inbox";

const pitch = (id: number, verdict: "green" | "yellow" | "red" | null) =>
  ({ id, verdict }) as Parameters<typeof sortByVerdict>[0][number];

describe("sortByVerdict", () => {
  it("puts the best entry first, not the newest", () => {
    const sorted = sortByVerdict([pitch(1, "red"), pitch(2, "green"), pitch(3, "yellow")]);
    expect(sorted.map((p) => p.verdict)).toEqual(["green", "yellow", "red"]);
  });

  it("keeps newest-first inside one band", () => {
    const sorted = sortByVerdict([pitch(5, "yellow"), pitch(9, "yellow"), pitch(7, "yellow")]);
    expect(sorted.map((p) => p.id)).toEqual([9, 7, 5]);
  });

  it("sorts pitches without a verdict last instead of guessing a band", () => {
    const sorted = sortByVerdict([pitch(1, null), pitch(2, "red")]);
    expect(sorted.map((p) => p.verdict)).toEqual(["red", null]);
  });

  it("does not mutate the input", () => {
    const input = [pitch(1, "red"), pitch(2, "green")];
    sortByVerdict(input);
    expect(input.map((p) => p.verdict)).toEqual(["red", "green"]);
  });
});

describe("verdictRank / isUnrated", () => {
  it("treats an unknown band like an unrated one — never as a guess", () => {
    expect(verdictRank("purple")).toBe(verdictRank(null));
  });

  it("recognises the unrated case", () => {
    expect(isUnrated({ verdict: null })).toBe(true);
    expect(isUnrated({ verdict: "green" })).toBe(false);
  });
});
