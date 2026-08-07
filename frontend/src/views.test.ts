import { describe, expect, it } from "vitest";

import {
  MOBILE_FOCUSES,
  NAV,
  parseChatOpen,
  parseTicker,
  parseView,
  resolveView,
} from "./views";

describe("parseView", () => {
  it("defaults to heute when there is no query string", () => {
    expect(parseView("")).toBe("heute");
  });

  it("resolves the new keys", () => {
    expect(parseView("?view=depot")).toBe("depot");
    expect(parseView("?view=entscheiden")).toBe("entscheiden");
    expect(parseView("?view=werkauft")).toBe("werkauft");
  });

  it("maps every legacy key to its new home — old Telegram links keep working", () => {
    expect(parseView("?view=today")).toBe("heute");
    expect(parseView("?view=funnel")).toBe("aktien");
    expect(parseView("?view=radar")).toBe("aktien");
    expect(parseView("?view=inbox")).toBe("entscheiden");
    expect(parseView("?view=depots")).toBe("depot");
    expect(parseView("?view=proof")).toBe("ergebnisse");
    expect(parseView("?view=people")).toBe("werkauft");
    expect(parseView("?view=voices")).toBe("werkauft");
    expect(parseView("?view=strategies")).toBe("labor");
    expect(parseView("?view=model")).toBe("labor");
    expect(parseView("?view=ml")).toBe("labor");
    expect(parseView("?view=learning")).toBe("labor");
  });

  it("falls back to heute for an unknown view", () => {
    expect(parseView("?view=nonsense")).toBe("heute");
  });

  it("routes a profile link with a ticker, and without one lands on the list", () => {
    expect(parseView("?view=profil&ticker=MU")).toBe("profil");
    expect(parseView("?view=profil")).toBe("aktien");
    expect(parseView("?view=profil&ticker=not a ticker!")).toBe("aktien");
  });
});

describe("parseTicker", () => {
  it("uppercases a plausible ticker", () => {
    expect(parseTicker("?view=profil&ticker=mu")).toBe("MU");
  });

  it("rejects garbage", () => {
    expect(parseTicker("?ticker=bad ticker!")).toBeNull();
    expect(parseTicker("")).toBeNull();
  });
});

describe("parseChatOpen", () => {
  it("opens on ?chat=1 and on the legacy ?view=chat deep link", () => {
    expect(parseChatOpen("?chat=1")).toBe(true);
    expect(parseChatOpen("?view=chat")).toBe(true);
    expect(parseChatOpen("?view=heute")).toBe(false);
  });
});

describe("resolveView", () => {
  it("keeps valid keys, maps legacy keys, defaults the rest", () => {
    expect(resolveView("labor")).toBe("labor");
    expect(resolveView("profil")).toBe("profil");
    expect(resolveView("inbox")).toBe("entscheiden");
    expect(resolveView("quatsch")).toBe("heute");
  });
});

describe("MOBILE_FOCUSES", () => {
  it("is exactly the four phone tabs, in tab order", () => {
    expect(MOBILE_FOCUSES).toEqual(["heute", "aktien", "entscheiden", "depot"]);
  });

  it("every focus exists as a NAV entry", () => {
    const navKeys = new Set(NAV.map((item) => item.key));
    for (const focus of MOBILE_FOCUSES) {
      expect(navKeys.has(focus)).toBe(true);
    }
  });
});
