// API types mirror the FastAPI read endpoints (src/equity_scout/api.py).

export interface Instrument {
  ticker: string;
  name: string;
  exchange: string;
  region: string;
  currency: string;
  sector: string;
}

export type Breakdown = Record<string, number>;
export type BucketWeights = Record<string, Record<string, number>>;

export interface Pick {
  instrument: Instrument;
  bucket: string;
  rank: number;
  composite: number;
  breakdown: Breakdown;
  thesis: string | null;
}

export interface GateStats {
  total_gated: number;
  by_reason: Record<string, number>;
  by_region: Record<string, number>;
}

export interface LatestRun {
  created_at?: string;
  universe_size?: number;
  gated_out: Record<string, string>;
  gate_stats: GateStats;
  buckets: Record<string, Pick[]>;
  bucket_weights: BucketWeights;
  disclaimer: string;
}

export interface RunSummary {
  created_at: string;
  universe_size: number;
  total_gated: number;
  picks: Record<string, string[]>;
}

export async function fetchLatestRun(): Promise<LatestRun> {
  const response = await fetch("/api/latest");
  if (!response.ok) throw new Error(`/api/latest returned ${response.status}`);
  return response.json();
}

export async function fetchRunHistory(): Promise<{ runs: RunSummary[] }> {
  const response = await fetch("/api/history");
  if (!response.ok) throw new Error(`/api/history returned ${response.status}`);
  return response.json();
}

export interface PortfolioPosition {
  ticker: string;
  name: string;
  region: string;
  shares: number;
  cost_basis: number;
  opened_at: string;
}

export interface Valuation {
  created_at: string;
  total_value: number;
  total_return: number;
  benchmark_return: number;
  open_positions: number;
}

export interface PortfolioState {
  exists: boolean;
  initial_capital?: number;
  cash?: number;
  benchmark_ticker?: string;
  positions: PortfolioPosition[];
  valuations: Valuation[];
}

export async function fetchPortfolio(): Promise<PortfolioState> {
  const response = await fetch("/api/portfolio");
  if (!response.ok) throw new Error(`/api/portfolio returned ${response.status}`);
  return response.json();
}
