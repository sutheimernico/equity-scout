import { describe, expect, it } from "vitest";

import { companyInitials, shortCompanyName } from "./company";

describe("shortCompanyName", () => {
  it("strips stacked legal forms", () => {
    expect(shortCompanyName("Yamato Holdings Co., Ltd.")).toBe("Yamato");
    expect(shortCompanyName("Micron Technology, Inc.")).toBe("Micron Technology");
    expect(shortCompanyName("Microsoft Corporation")).toBe("Microsoft");
    expect(shortCompanyName("Allianz SE")).toBe("Allianz");
  });

  it("leaves names without a legal form alone", () => {
    expect(shortCompanyName("Petrobras")).toBe("Petrobras");
  });

  it("strips Yahoo's share-class descriptions", () => {
    // These describe the instrument, not the company, and eat the whole row on a phone.
    expect(shortCompanyName("Air T, Inc. - Common Stock")).toBe("Air T");
    expect(shortCompanyName("Alphabet Inc. - Class A Common Stock")).toBe("Alphabet");
  });

  it("normalises whitespace", () => {
    expect(shortCompanyName("  Central  Japan Railway Company ")).toBe("Central Japan Railway");
  });

  it("never returns empty, even when the name IS a legal form", () => {
    // A company literally called "Group" must not render as a blank line.
    expect(shortCompanyName("Group")).toBe("Group");
  });
});

describe("companyInitials", () => {
  it("uses the first two words", () => {
    expect(companyInitials("Micron Technology, Inc.")).toBe("MT");
    expect(companyInitials("Central Japan Railway Company")).toBe("CJ");
  });

  it("falls back to two characters for single-word names", () => {
    expect(companyInitials("Microsoft Corporation")).toBe("MI");
    expect(companyInitials("Petrobras")).toBe("PE");
  });

  it("ignores punctuation-only fragments", () => {
    expect(companyInitials("A.P. Moller - Maersk")).toBe("AP");
  });
});
