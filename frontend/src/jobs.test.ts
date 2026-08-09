import { describe, expect, it } from "vitest";

import type { JobState } from "./api";
import { blockedText, describeProgress, formatMarker } from "./jobs";

const RUNNING: JobState = {
  key: "daily",
  label: "Tages-Update",
  running: true,
  blocked: null,
  last_run: "2026-08-07",
  progress: {
    current: "evidence",
    current_since: "2026-08-09T21:00:00+02:00",
    done_count: 3,
    expected_total: 12,
    failed: [],
    started_at: "2026-08-09T20:54:00+02:00",
  },
  tail: [],
};

const IDLE: JobState = {
  ...RUNNING,
  running: false,
  progress: { ...RUNNING.progress, current: null },
};

describe("describeProgress", () => {
  it("names the running step, its number and how long it has been running", () => {
    const now = new Date("2026-08-09T21:06:00+02:00").getTime();
    expect(describeProgress(RUNNING, now)).toBe("Schritt 4 von ~12: evidence · seit 6 Min.");
  });

  it("falls back to the total runtime when no step has started yet", () => {
    const job: JobState = {
      ...RUNNING,
      progress: { ...RUNNING.progress, current: null, current_since: null, done_count: 0 },
    };
    const now = new Date("2026-08-09T20:56:00+02:00").getTime();
    expect(describeProgress(job, now)).toBe("läuft seit 2 Min.");
  });

  it("reports failed steps of a running chain", () => {
    const job: JobState = { ...RUNNING, progress: { ...RUNNING.progress, failed: ["notify"] } };
    const now = new Date("2026-08-09T21:06:00+02:00").getTime();
    expect(describeProgress(job, now)).toContain("1 Schritt fehlgeschlagen (notify)");
  });

  it("pluralises several failed steps", () => {
    const job: JobState = {
      ...RUNNING,
      progress: { ...RUNNING.progress, failed: ["notify", "digest"] },
    };
    expect(describeProgress(job, Date.now())).toContain("2 Schritte fehlgeschlagen");
  });

  it("says when the job is idle", () => {
    expect(describeProgress(IDLE, Date.now())).toBe("läuft nicht");
  });
});

describe("formatMarker", () => {
  it("renders a day marker as a German date", () => {
    expect(formatMarker("2026-08-07")).toBe("07.08.2026");
  });

  it("leaves an ISO week marker readable", () => {
    expect(formatMarker("2026-W32")).toBe("KW 32/2026");
  });

  it("says never for a missing marker", () => {
    expect(formatMarker(null)).toBe("noch nie");
  });
});

describe("blockedText", () => {
  it("explains the weekend guard", () => {
    expect(blockedText("weekend")).toContain("Wochenende");
  });

  it("explains the day marker", () => {
    expect(blockedText("already_ran")).toContain("schon gelaufen");
  });

  it("is empty when nothing blocks", () => {
    expect(blockedText(null)).toBe("");
  });
});
