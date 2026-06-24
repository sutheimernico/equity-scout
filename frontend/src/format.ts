// Display helpers + factor ordering, shared across components.

export const FACTOR_ORDER = ["value", "quality", "momentum", "growth", "low_vol"] as const;

export const FACTOR_LABELS: Record<string, string> = {
  value: "Value",
  quality: "Qualität",
  momentum: "Momentum",
  growth: "Wachstum",
  low_vol: "Geringe Vola",
};

export const BUCKET_LABELS: Record<string, string> = {
  defensive: "Defensiv",
  balanced: "Ausgewogen",
  aggressive: "Aggressiv",
};

/** Percentile / score in [0,1] → integer 0–100. */
export function toPercent(value: number): number {
  return Math.round(value * 100);
}
