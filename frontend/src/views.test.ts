import { describe, expect, it } from "vitest";

import { MOBILE_FOCUSES, NAV, parseView } from "./views";

describe("parseView", () => {
  it("defaults to today when there is no query string", () => {
    expect(parseView("")).toBe("today");
  });

  it("defaults to today when the view param is absent", () => {
    expect(parseView("?foo=bar")).toBe("today");
  });

  it("resolves ?view=depots", () => {
    expect(parseView("?view=depots")).toBe("depots");
  });

  it("resolves ?view=inbox", () => {
    expect(parseView("?view=inbox")).toBe("inbox");
  });

  it("falls back to today for an unknown view", () => {
    // A stale Telegram deep link (old view key, typo, future app version) must still
    // land the user somewhere sensible instead of rendering a blank/broken screen.
    expect(parseView("?view=nonsense")).toBe("today");
  });

  it("resolves the view param alongside the token exchange param", () => {
    expect(parseView("?token=abc&view=proof")).toBe("proof");
  });
});

describe("MOBILE_FOCUSES", () => {
  it("is exactly the four phone tabs, in tab order", () => {
    expect(MOBILE_FOCUSES).toEqual(["today", "depots", "inbox", "proof"]);
  });

  it("every focus exists as a NAV entry", () => {
    const navKeys = new Set(NAV.map((item) => item.key));
    for (const focus of MOBILE_FOCUSES) {
      expect(navKeys.has(focus)).toBe(true);
    }
  });
});
