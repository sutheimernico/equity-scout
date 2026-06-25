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

export function eur(value: number): string {
  return value.toLocaleString("de-DE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  });
}

// Readable names for the ETF basket (ticker → what it actually is).
export const ETF_NAMES: Record<string, string> = {
  SPY: "US-Aktien (S&P 500)",
  VEU: "Aktien Welt ex-USA",
  VWO: "Schwellenländer-Aktien",
  IEF: "US-Staatsanleihen 7–10 J.",
  TLT: "US-Staatsanleihen 20 J.+",
  BND: "US-Anleihen (breit)",
  BIL: "Geldmarkt / T-Bills",
  GLD: "Gold",
  DBC: "Rohstoffe",
  VNQ: "Immobilien (REITs)",
};

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

// One-paragraph pitch per strategy (keyed by the backend strategy name), shown atop each tab.
export const STRATEGY_PITCH: Record<string, string> = {
  "DCA (12-month entry)":
    "Dollar-Cost-Averaging: Kapital in 12 gleichen Tranchen über ein Jahr in einen 60/40-Mix " +
    "einzahlen, dann halten. Senkt das Risiko, zum falschen Zeitpunkt all-in zu gehen, kostet aber " +
    "Rendite (länger in Cash). Der Bildungs-Anker — kein Timing-Anspruch.",
  "60/40":
    "Der klassische Benchmark: fix 60 % Aktien / 40 % Anleihen, monatlich zurückgesetzt. Die stumpf, " +
    "aber solide diversifizierte Messlatte, die jede aktive Strategie nach Kosten erst schlagen muss.",
  "Permanent Portfolio":
    "Harry Brownes Allwetter-Portfolio: fix 25/25/25/25 auf Aktien, lange Staatsanleihen, Cash und " +
    "Gold — ein Quadrant für jedes Makro-Szenario (Wachstum, Deflation, Rezession, Inflation). Kein Timing.",
  "Volatility Targeting":
    "Steuert das Aktien-Exposure so, dass die Schwankung ein Ziel (≈10 % p.a.) trifft, gedeckelt bei " +
    "100 % (kein Hebel). Ruhiger Markt → voll investiert, unruhiger → reduziert. Reine Risiko-Steuerung.",
  "Dual Momentum (GEM)":
    "Antonaccis Dual Momentum: hält das stärkere von US- vs. Welt-Aktien (relatives Momentum), aber " +
    "nur, wenn es auch T-Bills schlägt (absolutes Momentum); sonst Anleihen. Trendfolge mit Crash-Schalter.",
  "Defensive Asset Allocation":
    "Keller & Keunings DAA: ein „Canary“-Frühwarnsystem (Schwellenländer + Anleihen) misst die " +
    "Marktgesundheit und steuert die Cash-Quote; der Rest geht in die 3 stärksten Risk-Assets. " +
    "Regelbasierter Crashschutz.",
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
