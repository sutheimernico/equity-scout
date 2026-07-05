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

export interface NewsItem {
  title: string;
  publisher: string;
  published: string;
  link: string;
}

export interface Pick {
  instrument: Instrument;
  bucket: string;
  rank: number;
  composite: number;
  breakdown: Breakdown;
  thesis: string | null;
  news?: NewsItem[];
}

export interface GateStats {
  total_gated: number;
  by_reason: Record<string, number>;
  by_region: Record<string, number>;
}

// See equity_scout.data_quality.build_data_quality_report. attempted=0 means no yfinance fetch
// stats were wired for this run (e.g. a --provider fake run) — the error rate is not meaningful then.
export interface DataQuality {
  attempted: number;
  info_failed: number;
  closes_failed: number;
  fetch_error_rate: number;
  missing_fields: Record<string, number>;
  gate_filtered: number;
}

export interface LatestRun {
  created_at?: string;
  universe_size?: number;
  gated_out: Record<string, string>;
  gate_stats: GateStats;
  data_quality?: DataQuality;
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

export interface AttributionBet {
  date: string;
  decision: string; // "follow" | "avoid"
  probability: number;
  label: number; // 1 = profit barrier hit first
  features: Record<string, number>;
}

export interface Attribution {
  n_bets: number;
  n_errors: number;
  hit_rate: number;
  worst: AttributionBet[];
  regime_contrast: Record<string, { correct: number | null; wrong: number | null }>;
}

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
  attribution?: Attribution;
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

export interface PboResult {
  pbo: number; // [0,1] — probability of backtest overfitting (CSCV)
  n_configs: number;
  n_blocks: number;
  computed_at: string;
}

export interface ResearchResponse {
  available: boolean;
  n_trials: number;
  hurdle?: number;
  champion: ResearchConfig | null;
  leaderboard: ResearchConfig[];
  model_frequency?: Record<string, number>;
  feature_frequency?: Record<string, number>;
  pbo?: PboResult;
  disclaimer: string;
}

export async function fetchResearch(): Promise<ResearchResponse> {
  const response = await fetch("/api/research");
  if (!response.ok) throw new Error(`/api/research returned ${response.status}`);
  return response.json();
}

// --- Forward paper trading (src/equity_scout/forward_paper + forward_storage) ---

export interface ForwardAccount {
  strategy_name: string;
  initial_capital: number;
  equity: number;
  total_return: number;
  benchmark_ticker: string;
  benchmark_return: number;
  last_as_of: string | null;
  n_points: number;
  equity_curve: [string, number, number][]; // [date, equity, benchmark_equity]
}

export interface ForwardResponse {
  available: boolean;
  accounts: ForwardAccount[];
  disclaimer: string;
}

export async function fetchForward(): Promise<ForwardResponse> {
  const response = await fetch("/api/forward");
  if (!response.ok) throw new Error(`/api/forward returned ${response.status}`);
  return response.json();
}

// --- Local chatbot over the dashboard data (src/equity_scout/chat.py via Ollama) ---

export interface ChatReply {
  answer?: string;
  error?: string;
}

export async function askChat(question: string): Promise<ChatReply> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return response.json(); // body carries {answer} or {error} on both 200 and 503
}

// --- Per-stock entry reference levels + tranche plan (src/equity_scout/entry.py) ---

export interface EntryLevel {
  label: string;
  price: number;
  kind: "anchor" | "support" | "volatility";
  note: string;
}

export interface Tranche {
  label: string;
  fraction: number;
  trigger_price: number | null;
}

export interface EntryPlan {
  ticker: string;
  price: number;
  sma200: number | null;
  high_52w: number;
  low_52w: number;
  drawdown_from_high: number;
  atr: number | null;
  levels: EntryLevel[];
  dca_tranches: Tranche[];
  dip_tranches: Tranche[];
  near_reference: boolean;
  reference_note: string;
}

export interface EntryResponse {
  available: boolean;
  ticker?: string;
  plan?: EntryPlan;
  disclaimer: string;
}

export async function fetchEntry(ticker: string): Promise<EntryResponse> {
  const response = await fetch(`/api/entry/${encodeURIComponent(ticker)}`);
  if (!response.ok) throw new Error(`/api/entry returned ${response.status}`);
  return response.json();
}

// ============================================================
// Trading-copilot surfaces (Phase 6): Radar / Inbox / Arena / Model
// Field names mirror the live endpoint shapes 1:1. Fetchers follow the inline
// per-endpoint pattern above (no shared getJSON helper in this file).
// ============================================================

// --- Radar (src/equity_scout/api.py → /api/radar) ---
export interface SignalReading {
  name: string;
  score: number;
  reason: string;
}

export interface WatchlistEntry {
  ticker: string;
  name: string;
  bucket: string;
  price: number;
  entry_zone_low: number;
  entry_zone_high: number;
  proximity: number;
  in_zone: boolean;
  composite: number;
  readings: SignalReading[];
  zone_note: string;
  breakdown: Record<string, number>;
}

export interface Watchlist {
  created_at: string;
  entries: WatchlistEntry[];
  skipped: Record<string, string>;
  watchlist_id: number;
}

export interface RadarResponse {
  watchlist: Watchlist | null;
  disclaimer: string;
}

export async function fetchRadar(): Promise<RadarResponse> {
  const response = await fetch("/api/radar");
  if (!response.ok) throw new Error(`/api/radar returned ${response.status}`);
  return response.json();
}

// --- Inbox (src/equity_scout/api.py → /api/inbox + decision POST) ---
export type PitchStatus = "open" | "buy" | "pass" | "later";

export interface Pitch {
  id: number;
  created_at: string;
  ticker: string;
  watchlist_id: number;
  price: number;
  composite: number;
  zone_low: number;
  zone_high: number;
  pitch: string;
  status: PitchStatus;
  decided_at: string | null;
  telegram_message_id: number | null;
}

export interface InboxResponse {
  pitches: Pitch[];
  disclaimer: string;
}

export async function fetchInbox(): Promise<InboxResponse> {
  const response = await fetch("/api/inbox");
  if (!response.ok) throw new Error(`/api/inbox returned ${response.status}`);
  return response.json();
}

export interface DecisionResponse {
  ok?: boolean;
  pitch?: Pitch;
  error?: string;
  disclaimer?: string; // present on 200; absent on the 409/422 error bodies
  status: number; // HTTP status — lets the caller branch 200 vs 409 (refetch) vs 422 (inline error)
}

export async function decidePitch(
  id: number,
  action: "buy" | "pass" | "later",
): Promise<DecisionResponse> {
  const response = await fetch(`/api/inbox/${id}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  // 200/409/422 all carry a JSON body; the status distinguishes success from the two conflict paths.
  const body = (await response.json()) as Omit<DecisionResponse, "status">;
  return { ...body, status: response.status };
}

// --- Arena (src/equity_scout/api.py → /api/arena) ---
export interface LanePosition {
  ticker: string;
  name: string;
  shares: number;
  cost_basis: number;
  last_price: number | null;
  opened_at: string;
}

export interface LaneTrade {
  id: number;
  created_at: string;
  lane: string;
  ticker: string;
  side: string;
  shares: number;
  fill_price: number;
  cost: number;
  reason: string;
  pitch_id: number | null;
}

export interface Lane {
  lane: string;
  initial_capital: number;
  total_value: number;
  total_return: number;
  benchmark_return: number;
  open_positions: LanePosition[];
  equity_curve: [string, number, number][];
  trades: LaneTrade[];
}

export interface ArenaResponse {
  available: boolean;
  lanes: Lane[];
  disclaimer: string;
}

export async function fetchArena(): Promise<ArenaResponse> {
  const response = await fetch("/api/arena");
  if (!response.ok) throw new Error(`/api/arena returned ${response.status}`);
  return response.json();
}

// --- Model (src/equity_scout/api.py → /api/model) ---
export interface RegistryEntry {
  version: number;
  created_at: string;
  model_kind: string;
  n_train: number;
  metrics: Record<string, number | null>;
  is_champion: boolean;
}

export interface ResolvedStats {
  n_resolved: number;
  n_open: number;
  hit_rate: number | null;
  rank_ic: number | null;
  by_score_bucket: Record<string, number>;
}

export interface ModelResponse {
  available: boolean;
  champion: {
    version: number;
    created_at: string;
    model_kind: string;
    metrics: Record<string, number | null>;
  } | null;
  registry: RegistryEntry[];
  resolved: ResolvedStats;
  drift: null;
  disclaimer: string;
}

export async function fetchModel(): Promise<ModelResponse> {
  const response = await fetch("/api/model");
  if (!response.ok) throw new Error(`/api/model returned ${response.status}`);
  return response.json();
}
