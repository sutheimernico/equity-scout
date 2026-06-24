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
  last_price: number;
  invested: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
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

// --- Strategy backtests (src/equity_scout/strategy_service.py) ---

export interface StrategyMetrics {
  cagr: number;
  annual_volatility: number;
  sharpe: number;
  sortino: number;
  max_drawdown: number;
  calmar: number;
  annual_turnover: number | null;
  deflated_sharpe: number | null;
}

export interface StrategyTrade {
  date: string;
  weights: Record<string, number>;
  turnover: number;
}

export interface StrategyReport {
  name: string;
  is_benchmark: boolean;
  metrics: StrategyMetrics;
  equity: [string, number][];
  benchmark_equity: [string, number][];
  current_weights: Record<string, number>;
  recent_trades: StrategyTrade[];
  cost_sweep: [number, number][];
}

export interface StrategiesResponse {
  available: boolean;
  benchmark?: string;
  strategies: StrategyReport[];
  hint?: string;
  disclaimer: string;
}

export async function fetchStrategies(): Promise<StrategiesResponse> {
  const response = await fetch("/api/strategies");
  if (!response.ok) throw new Error(`/api/strategies returned ${response.status}`);
  return response.json();
}

// --- ML meta-model (src/equity_scout/ml + strategy_service.build_ml_report) ---

export interface MlReport {
  trained: boolean;
  metrics: StrategyMetrics | null;
  equity: [string, number][];
  benchmark_equity: [string, number][];
  n_bets: number;
  oos_hit_rate: number;
  avg_probability: number;
  avg_exposure: number;
  feature_importance: Record<string, number>;
}

export interface MlResponse {
  available: boolean;
  report?: MlReport;
  disclaimer: string;
}

export async function fetchMlReport(): Promise<MlResponse> {
  const response = await fetch("/api/ml");
  if (!response.ok) throw new Error(`/api/ml returned ${response.status}`);
  return response.json();
}

// --- Continuous research loop (src/equity_scout/ml/research_view + ledger) ---

export interface ResearchConfig {
  features: string[];
  model: string;
  primary_lookback_months: number;
  horizon_days: number;
  barrier: number;
  dsr: number;
  sharpe: number;
  sortino: number;
  cagr: number;
  max_drawdown: number;
  oos_hit_rate: number;
  n_bets: number;
  feature_importance: Record<string, number>;
}

export interface ResearchResponse {
  available: boolean;
  n_trials: number;
  hurdle?: number;
  champion: ResearchConfig | null;
  leaderboard: ResearchConfig[];
  model_frequency?: Record<string, number>;
  feature_frequency?: Record<string, number>;
  disclaimer: string;
}

export async function fetchResearch(): Promise<ResearchResponse> {
  const response = await fetch("/api/research");
  if (!response.ok) throw new Error(`/api/research returned ${response.status}`);
  return response.json();
}
