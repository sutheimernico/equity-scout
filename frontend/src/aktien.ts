import type { StockBrief } from "./api";

// The ONE stock list (cockpit rebuild 2026-08-07): Screener + Radar + Heute-Stockliste
// used to be three near-identical card lists with three scores. The radar's timing aspect
// becomes a filter here ("Kaufbereit / Fast / Alle"), the factor bucket becomes a visible
// risk chip — the full depth lives in the stock profile, nothing is deleted.

export type ZoneSegment = "in" | "near" | "all";

/** "Fast" reaches this far above the band's top edge (5 %). Below the band is never
 *  "fast": every support has broken (see backend briefs.zone_gap), which is a "not now",
 *  not a near-entry. */
export const NEAR_LIMIT = 0.05;

export function zoneSegment(
  brief: Pick<StockBrief, "in_zone" | "price" | "zone_high">,
): "in" | "near" | "other" {
  if (brief.in_zone) return "in";
  if (brief.price > brief.zone_high && brief.price <= brief.zone_high * (1 + NEAR_LIMIT)) {
    return "near";
  }
  return "other";
}

export function filterBriefs(
  briefs: StockBrief[],
  segment: ZoneSegment,
  bucket: string,
): StockBrief[] {
  return briefs.filter((brief) => {
    const segmentOk = segment === "all" || zoneSegment(brief) === segment;
    const bucketOk = bucket === "alle" || brief.bucket === bucket;
    return segmentOk && bucketOk;
  });
}

/** Risk profile per factor bucket — violet chip class for aggressive so the risk axis
 *  never collides with the green/amber status colours (mockup v2 rule). */
export const RISK_META: Record<
  NonNullable<StockBrief["bucket"]>,
  { label: string; chip: string; note: string }
> = {
  defensive: {
    label: "Defensiv",
    chip: "brief-chip brief-chip-brand",
    note: "Eher ruhig: etabliertes Geschäft, geringere Schwankungen — dafür meist kleineres Potenzial.",
  },
  balanced: {
    label: "Ausgewogen",
    chip: "brief-chip brief-chip-mute",
    note: "Der Mittelweg: solide Firma, normale Kursschwankungen.",
  },
  aggressive: {
    label: "Aggressiv",
    chip: "brief-chip brief-chip-risk",
    note: "High Risk, High Reward: mehr Chance, aber deutlich stärkere Schwankungen möglich.",
  },
};

export function riskMeta(bucket: StockBrief["bucket"]) {
  return bucket ? RISK_META[bucket] : null;
}
