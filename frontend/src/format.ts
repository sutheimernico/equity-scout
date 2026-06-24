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

/** Fraction → signed percent string, e.g. 0.082 → "+8.2 %". */
export function pct(value: number, digits = 1): string {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)} %`;
}

/** Fraction → unsigned percent, e.g. 0.326 → "32.6 %". */
export function pctAbs(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)} %`;
}

export function num(value: number, digits = 2): string {
  return value.toFixed(digits);
}

// Strategy metric labels + one-line explanations (German UI).
export const METRIC_LABELS: Record<string, string> = {
  cagr: "Rendite p.a.",
  annual_volatility: "Volatilität",
  sharpe: "Sharpe",
  sortino: "Sortino",
  max_drawdown: "Max. Verlust",
  calmar: "Calmar",
  annual_turnover: "Umschlag p.a.",
  deflated_sharpe: "Deflated Sharpe",
};

export const ML_FEATURE_LABELS: Record<string, string> = {
  vol: "Volatilität",
  trend: "Trend (Abstand zur MA)",
  breadth: "Marktbreite",
  drawdown: "Drawdown-Zustand",
  mom_3m: "3-Monats-Momentum",
};

export const METRIC_HELP: Record<string, string> = {
  cagr: "Durchschnittliche jährliche Wachstumsrate über den gesamten Zeitraum.",
  annual_volatility: "Schwankungsbreite der Renditen p.a. — höher = unruhiger.",
  sharpe: "Rendite je Einheit Gesamtrisiko. Höher ist besser; ~1 ist solide.",
  sortino: "Wie Sharpe, bestraft aber nur Verluste, nicht Aufwärtsschwankungen.",
  max_drawdown: "Größter Wertverlust vom Hoch zum Tief — der Schmerztest.",
  calmar: "Rendite p.a. geteilt durch den maximalen Verlust.",
  annual_turnover: "Wie viel des Depots pro Jahr umgeschichtet wird (Kostentreiber).",
  deflated_sharpe:
    "Sharpe, korrigiert um die Zahl getesteter Strategien — gegen zufällig gut aussehende Backtests.",
};
