import { describe, expect, it } from "vitest";

import { describeFreshness } from "./useFreshness";

describe("describeFreshness", () => {
  it("returns null while online, regardless of lastSync", () => {
    expect(describeFreshness({ online: true, lastSync: null })).toBeNull();
    expect(describeFreshness({ online: true, lastSync: "2026-08-04T10:00:00.000Z" })).toBeNull();
  });

  it("names the cockpit unreachable and shows a timestamp when offline with a lastSync", () => {
    // No absolute clock assertion here on purpose — toLocaleTimeString formats in the
    // browser's local timezone, which differs across CI machines and Nico's own devices.
    const label = describeFreshness({ online: false, lastSync: "2026-08-04T10:00:00.000Z" });
    expect(label).toContain("Cockpit nicht erreichbar");
    expect(label).toContain("Stand von");
  });

  it("falls back to the no-data message when offline with no lastSync at all", () => {
    expect(describeFreshness({ online: false, lastSync: null })).toBe(
      "Cockpit nicht erreichbar — keine gespeicherten Daten.",
    );
  });
});
