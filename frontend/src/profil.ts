import type { FScore } from "./api";

// Pure logic for the stock profile view (mockup v2): label maps and tiny formatters,
// kept out of the component so they are unit-testable.

/** Factor-percentile labels for the "Im Detail: die 5 Faktoren" disclosure. */
export const FACTOR_LABELS: Record<string, string> = {
  value: "Bewertung — wie günstig",
  quality: "Qualität — wie solide",
  momentum: "Kurs-Schwung (Momentum)",
  growth: "Wachstum",
  low_vol: "Ruhiger Kursverlauf",
};

/** Radar timing signals, same wording RadarPanel uses. */
export const READING_LABELS: Record<string, string> = {
  dip_quality: "Dip-Qualität",
  value_gap: "Bewertungslücke",
  momentum: "Momentum",
};

/** The nine Piotroski criteria in plain German for the Bilanz-Check disclosure. */
export const FSCORE_LABELS: Record<string, string> = {
  roa_positive: "Verdient Geld (Gesamtkapitalrendite positiv)",
  cfo_positive: "Echter Geldzufluss aus dem Geschäft",
  roa_improving: "Rentabilität verbessert sich",
  cfo_exceeds_net_income: "Cashflow höher als der Buchgewinn",
  leverage_down: "Schuldenquote sinkt",
  liquidity_up: "Kurzfristige Zahlungsfähigkeit steigt",
  no_dilution: "Keine neuen Aktien ausgegeben",
  gross_margin_up: "Rohmarge steigt",
  asset_turnover_up: "Setzt sein Kapital effizienter ein",
};

/** Upside of a target over the current price in %, or null without both. */
export function upsidePct(target: number | null, price: number): number | null {
  if (target === null || price <= 0) return null;
  return Math.round((target / price - 1) * 100);
}

/** ISO date -> "25. Sep. 2026" (de-DE); null-safe. */
export function formatEarnings(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("de-DE", { day: "numeric", month: "short", year: "numeric" });
}

/** "7 von 9 Punkten" — evaluable is the honest denominator, not always 9. */
export function fscoreSummary(fscore: FScore): string {
  return `${fscore.score} von ${fscore.evaluable} Punkten`;
}

export interface KeyFigureRow {
  label: string;
  value: string;
}

/** Quote-cache metrics -> display rows; ratios become percent, absent values are
 *  dropped rather than shown as zero. */
export function keyFigureRows(metrics: Record<string, number | null> | null): KeyFigureRow[] {
  if (!metrics) return [];
  const pct = (v: number) => `${(v * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;
  const num = (v: number) => v.toLocaleString("de-DE", { maximumFractionDigits: 1 });
  const rows: [string, number | null | undefined, (v: number) => string][] = [
    ["Bewertung (KGV)", metrics.trailing_pe, num],
    ["Umsatzwachstum", metrics.revenue_growth, (v) => `${v > 0 ? "+" : ""}${pct(v)}`],
    ["Gewinnmarge", metrics.profit_margins, pct],
    ["Eigenkapitalrendite", metrics.return_on_equity, pct],
    ["Kurs/Buchwert", metrics.price_to_book, num],
  ];
  return rows
    .filter((r): r is [string, number, (v: number) => string] => typeof r[1] === "number")
    .map(([label, value, format]) => ({ label, value: format(value) }));
}
