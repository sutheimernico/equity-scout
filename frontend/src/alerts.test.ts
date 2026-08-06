import { describe, expect, it } from "vitest";

import { alertClaim } from "./alerts";

describe("alertClaim", () => {
  it("drops the quoted English source headline", () => {
    expect(
      alertClaim("Stimme: Michael Burry äußert sich negativ — »Michael Burry Warns on Loans«"),
    ).toBe("Stimme: Michael Burry äußert sich negativ");
  });

  it("leaves a plain reason untouched", () => {
    expect(alertClaim("2 Kongress-Mitglieder haben gekauft")).toBe(
      "2 Kongress-Mitglieder haben gekauft",
    );
  });

  it("does not cut on an em dash that is not a quote", () => {
    expect(alertClaim("Insider-Kauf — mehrere Vorstände")).toBe("Insider-Kauf — mehrere Vorstände");
  });
});
