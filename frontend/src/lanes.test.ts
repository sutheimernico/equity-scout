import { describe, expect, it } from "vitest";

import { closedLabel, LANE_NOTES, laneName, runningLabel } from "./lanes";

describe("laneName", () => {
  it("replaces the raw key with what the lane does", () => {
    expect(laneName("swing")).toBe("Kauft nach guten Nachrichten");
  });

  it("falls back to the key for an unknown lane instead of inventing a name", () => {
    expect(laneName("futures")).toBe("futures");
  });

  it("keeps the backend short name available for the Telegram cross-reference", () => {
    expect(LANE_NOTES.session?.label).toBe("Intraday-Session");
  });
});

describe("group labels", () => {
  it("counts instead of repeating the same heading per lane", () => {
    expect(runningLabel(2)).toBe("2 laufen noch");
    expect(closedLabel(5)).toBe("5 abgeschlossen");
  });

  it("uses the singular for one", () => {
    expect(runningLabel(1)).toBe("1 läuft noch");
    expect(closedLabel(1)).toBe("1 abgeschlossen");
  });

  it("says plainly that there is nothing", () => {
    expect(runningLabel(0)).toBe("keine offene Position");
    expect(closedLabel(0)).toBe("noch nichts abgeschlossen");
  });
});
