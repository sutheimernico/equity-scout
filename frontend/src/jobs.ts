import type { JobState } from "./api";

/** Whole minutes between an ISO timestamp and now; negative clock skew clamps to 0. */
function minutesSince(iso: string, nowMs: number): number {
  return Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 60_000));
}

/**
 * One sentence for the panel. "~12" and not "12": the daily chain prepends two Monday
 * steps, so the expected total is a floor, not a promise.
 */
export function describeProgress(job: JobState, nowMs: number): string {
  const { current, current_since, done_count, expected_total, failed, started_at } = job.progress;
  if (!job.running) return "läuft nicht";

  let text: string;
  if (current) {
    const position = done_count + 1;
    text = `Schritt ${position} von ~${expected_total}: ${current}`;
    if (current_since) text += ` · seit ${minutesSince(current_since, nowMs)} Min.`;
  } else if (started_at) {
    text = `läuft seit ${minutesSince(started_at, nowMs)} Min.`;
  } else {
    text = "läuft";
  }
  if (failed.length > 0) {
    const word = failed.length === 1 ? "Schritt" : "Schritte";
    text += ` · ${failed.length} ${word} fehlgeschlagen (${failed.join(", ")})`;
  }
  return text;
}

/** Marker values are either a day ("2026-08-07") or an ISO week ("2026-W32"). */
export function formatMarker(marker: string | null): string {
  if (!marker) return "noch nie";
  const week = /^(\d{4})-W(\d{2})$/.exec(marker);
  if (week) return `KW ${week[2]}/${week[1]}`;
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(marker);
  if (day) return `${day[3]}.${day[2]}.${day[1]}`;
  return marker;
}

export function blockedText(blocked: JobState["blocked"]): string {
  if (blocked === "weekend") {
    return "Heute ist Wochenende — die Tages-Kette läuft planmäßig nicht.";
  }
  if (blocked === "already_ran") {
    return "Ist heute schon gelaufen.";
  }
  return "";
}
