import { describe, expect, it } from "vitest";

import { ETF_NOTES, NAME_IN_ROW_WEIGHT, rowName } from "./etfs";

describe("rowName", () => {
  it("names a large holding in the row", () => {
    expect(rowName("SPY", 0.1)).toBe("S&P 500");
  });

  it("leaves small holdings to the tap so eleven rows stay one line each", () => {
    expect(rowName("XLK", 0.0417)).toBeNull();
    expect(ETF_NOTES.XLK?.name).toBe("Technologie (S&P)"); // still available behind the tap
  });

  it("judges on size, not direction", () => {
    expect(rowName("GLD", -0.08)).toBe("Gold");
  });

  it("returns null rather than inventing a name for an unknown ticker", () => {
    expect(rowName("ZZZZ", 0.4)).toBeNull();
  });

  it("includes the boundary weight itself", () => {
    expect(rowName("BIL", NAME_IN_ROW_WEIGHT)).toBe("US-Geldmarkt 1–3 Mon.");
  });
});
