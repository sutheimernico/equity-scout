import { describe, expect, it } from "vitest";

import { boundDigits, formatBound, ZONE_END_PCT, ZONE_START_PCT, zoneGeometry } from "./zone";

describe("zoneGeometry", () => {
  it("puts the zone bounds on the thirds", () => {
    // The contract the CSS bands depend on: zone_low → 1/3, zone_high → 2/3.
    const low = zoneGeometry(100, 100, 200);
    const high = zoneGeometry(200, 100, 200);
    expect(low?.pricePct).toBeCloseTo(ZONE_START_PCT, 5);
    expect(high?.pricePct).toBeCloseTo(ZONE_END_PCT, 5);
  });

  it("centres a mid-zone price", () => {
    expect(zoneGeometry(150, 100, 200)?.pricePct).toBeCloseTo(50, 5);
    expect(zoneGeometry(150, 100, 200)?.priceOverflow).toBeNull();
  });

  it("flags a price above the window instead of stretching the scale", () => {
    // Micron on 2026-08-04: 892.67 against a 458.82–524.65 zone (~70 % above).
    const geo = zoneGeometry(892.67, 458.82, 524.65);
    expect(geo?.priceOverflow).toBe("high");
    expect(geo?.pricePct).toBe(100);
  });

  it("flags a price below the window", () => {
    // Needs a NARROW zone to be reachable at all: the window floor is 2·low − high, so a
    // zone wider than low..2·low puts the floor at or below zero, where no valid (> 0)
    // price can sit. Real zones are narrow — Tele2's 154.3–167.0 floors at 141.6.
    const geo = zoneGeometry(50, 100, 110);
    expect(geo?.priceOverflow).toBe("low");
    expect(geo?.pricePct).toBe(0);
  });

  it("keeps in-window markers inset so they cannot clip the track", () => {
    const geo = zoneGeometry(1, 100, 200); // just inside the window floor (0)
    expect(geo?.priceOverflow).toBeNull();
    expect(geo?.pricePct).toBeGreaterThanOrEqual(2);
  });

  it("places an in-window analyst target", () => {
    // Tele2: target 176.41 against a 154.3–167.0 zone → 91 % along the bar.
    const geo = zoneGeometry(165.8, 154.3, 167.0, 176.40526);
    expect(geo?.targetPct).toBeCloseTo(91.4, 1);
  });

  it("drops a target outside the window rather than pinning it to the edge", () => {
    // Two arrows on one edge read as a smear; the upside line states the number anyway.
    expect(zoneGeometry(892.67, 458.82, 524.65, 1507.79)?.targetPct).toBeNull();
    expect(zoneGeometry(150, 100, 200, null)?.targetPct).toBeNull();
  });

  it("refuses to draw when the geometry would be invented", () => {
    expect(zoneGeometry(150, 200, 100)).toBeNull(); // inverted zone
    expect(zoneGeometry(150, 100, 100)).toBeNull(); // collapsed zone
    expect(zoneGeometry(0, 100, 200)).toBeNull(); // no valid price
    expect(zoneGeometry(-5, 100, 200)).toBeNull();
    expect(zoneGeometry(NaN, 100, 200)).toBeNull();
    expect(zoneGeometry(150, NaN, 200)).toBeNull();
  });

  it("ignores a non-positive target", () => {
    expect(zoneGeometry(150, 100, 200, 0)?.targetPct).toBeNull();
  });
});

describe("boundDigits", () => {
  it("uses whole numbers for wide zones", () => {
    expect(boundDigits(3134.86, 4057.3)).toBe(0);
  });

  it("adds decimals until a penny-stock zone stops collapsing to one number", () => {
    expect(boundDigits(2.1, 2.35)).toBe(1);
    expect(boundDigits(2.101, 2.104)).toBe(3);
  });

  it("caps the decimals so a degenerate pair cannot hang the loop", () => {
    expect(boundDigits(2.0, 2.0)).toBe(4);
  });
});

describe("formatBound", () => {
  it("groups German-style at the chosen precision", () => {
    expect(formatBound(3134.86, 0)).toBe("3.135");
    expect(formatBound(2.1, 1)).toBe("2,1");
  });
});
