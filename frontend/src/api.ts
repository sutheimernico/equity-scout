// API types mirror the FastAPI read endpoints (src/equity_scout/api.py).

export interface Instrument {
  ticker: string;
  name: string;
  exchange: string;
  region: string;
  currency: string;
  sector: string;
}

export interface Pick {
  instrument: Instrument;
  bucket: string;
  rank: number;
  composite: number;
  breakdown: Record<string, number>;
  thesis: string | null;
}

export interface GateStats {
  total_gated: number;
  by_reason: Record<string, number>;
  by_region: Record<string, number>;
}

export interface Latest {
  created_at?: string;
  universe_size?: number;
  gated_out: Record<string, string>;
  gate_stats: GateStats;
  buckets: Record<string, Pick[]>;
  disclaimer: string;
}

export interface RunSummary {
  created_at: string;
  universe_size: number;
  total_gated: number;
  picks: Record<string, string[]>;
}

export async function fetchLatest(): Promise<Latest> {
  const res = await fetch("/api/latest");
  if (!res.ok) throw new Error(`/api/latest returned ${res.status}`);
  return res.json();
}

export async function fetchHistory(): Promise<{ runs: RunSummary[] }> {
  const res = await fetch("/api/history");
  if (!res.ok) throw new Error(`/api/history returned ${res.status}`);
  return res.json();
}
