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
  // Server-side filter response (only present when filter params were sent).
  filters?: { region: string | null; country: string | null; sector: string | null };
  filter_matches?: number;
  filter_unavailable?: boolean;
}

export interface FilterFacet {
  value: string;
  count: number;
}

export interface FilterOptions {
  region_groups: string[];
  countries: FilterFacet[];
  sectors: FilterFacet[];
}

export interface LatestFilters {
  region?: string;
  country?: string;
  sector?: string;
}

export interface RunSummary {
  created_at: string;
  universe_size: number;
  total_gated: number;
  picks: Record<string, string[]>;
}

export async function fetchLatestRun(filters?: LatestFilters): Promise<LatestRun> {
  const params = new URLSearchParams();
  if (filters?.region) params.set("region", filters.region);
  if (filters?.country) params.set("country", filters.country);
  if (filters?.sector) params.set("sector", filters.sector);
  const query = params.toString();
  const response = await fetch(query ? `/api/latest?${query}` : "/api/latest");
  if (!response.ok) throw new Error(`/api/latest returned ${response.status}`);
  return response.json();
}

export async function fetchFilterOptions(): Promise<FilterOptions> {
  const response = await fetch("/api/filters");
  if (!response.ok) throw new Error(`/api/filters returned ${response.status}`);
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

// --- Sector momentum snapshot (src/equity_scout/sectors.py, /api/sectors) ---

export interface SectorRow {
  ticker: string;
  name: string;
  sector: string;
  // Fractions (0.12 = +12 %); null = not enough history (young ETF / stale panel).
  returns: { m1: number | null; m3: number | null; m6: number | null; m12: number | null };
  blend: number | null;
}

export interface SectorsResponse {
  available: boolean;
  sectors: SectorRow[];
  hint?: string;
  disclaimer?: string;
}

export async function fetchSectors(): Promise<SectorsResponse> {
  const response = await fetch("/api/sectors");
  if (!response.ok) throw new Error(`/api/sectors returned ${response.status}`);
  return response.json();
}

// --- Market regime traffic light (src/equity_scout/regime.py, /api/regime) ---

export interface RegimeSignal {
  key: string;
  label: string;
  green: boolean | null; // null = no data for this signal (honest absence)
  value: number | null;
  note: string;
}

export interface Regime {
  level: "green" | "yellow" | "red" | "unknown";
  emoji: string;
  label: string;
  green_count: number;
  available: number;
  signals: RegimeSignal[];
}

export interface RegimeResponse {
  regime: Regime;
  disclaimer?: string;
}

export async function fetchRegime(): Promise<RegimeResponse> {
  const response = await fetch("/api/regime");
  if (!response.ok) throw new Error(`/api/regime returned ${response.status}`);
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

// v14 strategy-parameter search: own trial pool with its own DSR hurdle,
// in-sample whole-history backtests — evidence only, never auto-promoted.
export interface StrategyTrial {
  strategy: string;
  name: string;
  params: Record<string, number | number[]>;
  dsr: number;
  dsr_hurdle: number | null;
  sharpe: number;
  sortino: number;
  cagr: number;
  max_drawdown: number;
  annual_turnover: number;
}

export interface StrategySearchBlock {
  available: boolean;
  n_trials: number;
  space_size: number;
  hurdle?: number;
  champion: StrategyTrial | null;
  leaderboard: StrategyTrial[];
  best_per_strategy: StrategyTrial[];
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
  strategy_search?: StrategySearchBlock;
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

// --- Auto-Depot: meta-allocated risk-managed paper depot (vision v10) ---

export interface AutodepotAccount {
  initial_capital: number;
  equity: number;
  total_return: number;
  benchmark_ticker: string;
  benchmark_return: number;
  last_as_of: string | null;
  weights: Record<string, number>;
  breaker_stage: number;
  breaker_changed_at: string | null;
  sleeve_mode: string; // "anchor" | "tilt"
}

export interface AutodepotValuation {
  created_at: string;
  equity: number;
  total_return: number;
  benchmark_equity: number;
  benchmark_return: number;
  gross_exposure: number;
  drawdown: number;
  equity_eur: number | null;
  fx_rate: number | null;
}

export interface AutodepotSleeveWeight {
  month: string;
  strategy_name: string;
  weight: number;
  sharpe: number | null;
  mode: string;
}

export interface AutodepotTrade {
  created_at: string;
  ticker: string;
  delta_weight: number;
  notional: number;
  cost: number;
  // v13 next-open fills: "open" when the trade filled at the following session's open,
  // "close_fallback" when no open existed. Absent on rows written before v13.
  fill?: string | null;
  fill_price?: number | null;
  decided_as_of?: string | null;
}

export interface AutodepotRiskEvent {
  created_at: string;
  protection: string;
  action: string;
  detail: string;
}

export interface AutodepotResponse {
  available: boolean;
  account?: AutodepotAccount;
  latest?: AutodepotValuation | null;
  equity_curve?: [string, number, number][]; // [date, equity, benchmark_equity]
  sleeve_weights?: AutodepotSleeveWeight[];
  trades?: AutodepotTrade[];
  risk_events?: AutodepotRiskEvent[];
  /** e.g. "next-open (seit v13)" — how a decided rebalance became a fill. */
  fill_convention?: string;
  disclaimer: string;
}

export async function fetchAutodepot(): Promise<AutodepotResponse> {
  const response = await fetch("/api/autodepot");
  if (!response.ok) throw new Error(`/api/autodepot returned ${response.status}`);
  return response.json();
}

// --- Kurzfrist-Arena: three short-term paper lanes raced against each other (vision v11) ---

export interface ShortTermStats {
  n_trades: number;
  n_fills: number;
  win_rate: number | null;
  realized_pnl: number;
  fees_paid: number;
}

export interface ShortTermPosition {
  ticker: string;
  qty: number;
  entry_price: number;
  opened_at: string;
  /** Last close from the lane runner's own local snapshot; null when the lane keeps none
   *  (session trades intraday bars, crypto pulls Kraken — neither leaves a panel). */
  last_price: number | null;
  unrealized_pct: number | null;
  /** Exit levels per that lane's rules; null where the level is not a fixed price. */
  target_price: number | null;
  stop_price: number | null;
  max_hold_days: number | null;
  rule: string;
}

export interface ShortTermTrade {
  executed_at: string;
  ticker: string;
  side: string;
  qty: number;
  price: number;
  fees: number;
  reason: string;
  realized_pnl: number | null;
}

// v12 I2/I3: the evidence gate an arena lane must pass before it earns depot capital.
export interface PromotionStatus {
  realized_trades: number;
  days_active: number;
  net_pnl: number;
  profit_factor: number | null;
  profit_factor_unbounded?: boolean; // all wins, no realised loss yet
  eligible: boolean;
  missing: string[];
}

export interface ShortTermLane {
  lane: string; // "swing" | "session" | "crypto"
  initial_capital: number;
  equity: number;
  total_return: number;
  benchmark_ticker: string;
  benchmark_return: number | null;
  max_drawdown: number;
  open_positions: ShortTermPosition[];
  equity_curve: [string, number][];
  stats: ShortTermStats;
  recent_trades: ShortTermTrade[];
  promoted: boolean;
  promotion: PromotionStatus;
}

export interface ShortTermResponse {
  available: boolean;
  lanes: ShortTermLane[];
  disclaimer: string;
}

export async function fetchShortterm(): Promise<ShortTermResponse> {
  const response = await fetch("/api/shortterm");
  if (!response.ok) throw new Error(`/api/shortterm returned ${response.status}`);
  return response.json();
}

// --- Total wealth across all horizons (v12 I1) ---

export interface OverviewBook {
  key: string;
  label: string;
  horizon: "short" | "mid_long";
  equity: number;
  initial: number;
  total_return: number;
  day_pnl: number | null;
  as_of: string;
}

export interface OverviewHorizon {
  equity: number;
  label: string;
  note?: string;
}

export interface OverviewResponse {
  available: boolean;
  books?: OverviewBook[];
  horizons?: Record<string, OverviewHorizon>;
  total?: { equity: number; initial: number; day_pnl: number | null };
  disclaimer: string;
}

export async function fetchOverview(): Promise<OverviewResponse> {
  const response = await fetch("/api/overview");
  if (!response.ok) throw new Error(`/api/overview returned ${response.status}`);
  return response.json();
}

// --- Proof report cards (v12 P2) ---

export interface ProofBook {
  label: string;
  n_days: number;
  period: string | null;
  total_return_pct: number | null;
  cagr_pct: number | null;
  sharpe_annualised: number | null;
  max_drawdown_pct: number | null;
  realized_win_rate: number | null;
  cost_share_of_pnl: number | null;
  vs_benchmark_pct: number | null;
  verdict_label: string;
}

export interface ProofResponse {
  available: boolean;
  books?: ProofBook[];
  conviction?: {
    min_track_days: number;
    min_sharpe_after_costs: number;
    max_drawdown_pct: number;
  };
  disclaimer: string;
}

export async function fetchProof(): Promise<ProofResponse> {
  const response = await fetch("/api/proof");
  if (!response.ok) throw new Error(`/api/proof returned ${response.status}`);
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

// entry.compute_target_stop's return shape (A4): a deterministic model target/stop from
// the entry_tb champion's own vol-scaled barrier config — distinct from both the
// rule-based EntryPlan levels above and any third-party analyst consensus. null when no
// champion/barrier config/long-enough history exists yet (honest gap, never a guess).
export interface TargetStop {
  target: number;
  stop: number;
  sigma: number;
  horizon_days: number;
}

export interface EntryResponse {
  available: boolean;
  ticker?: string;
  plan?: EntryPlan;
  target_stop?: TargetStop | null;
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

// "Stand: letzter Score-Lauf" — the ledger-logged champion score, never recomputed live.
export interface MlScoreStamp {
  score: number;
  created_at: string;
  model_version: number;
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
  ml?: MlScoreStamp | null;
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
  // v8 at-a-glance verdict; null on pitches from before the verdict column existed.
  verdict: "green" | "yellow" | "red" | null;
  verdict_why: string | null;
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

export interface ResolvedWindow {
  window_days: number;
  n_resolved: number;
  hit_rate: number | null;
  rank_ic: number | null;
}

export interface DriftEntry {
  train_mean: number;
  recent_mean: number | null;
  z_shift: number | null;
  flagged: boolean;
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
  resolved_windows: ResolvedWindow[];
  drift: Record<string, DriftEntry> | null;
  // Structural pipeline caveats (rebalance-cadence mismatch, survivorship bias) — see
  // equity_scout.constants.MODEL_CAVEATS. Present regardless of `available`.
  caveats: string[];
  disclaimer: string;
}

export async function fetchModel(): Promise<ModelResponse> {
  const response = await fetch("/api/model");
  if (!response.ok) throw new Error(`/api/model returned ${response.status}`);
  return response.json();
}

// --- learning curve (/api/model/history), evidence (/api/evidence), signal stack -------------

export interface ModelHistoryPoint {
  version: number;
  created_at: string;
  model_kind: string;
  is_champion: boolean;
  auc: number | null;
  brier: number | null;
  rank_ic: number | null;
  n_oos: number | null;
  calibrated: boolean | null;
  horizon_days: number | null;
}

export interface Promotion {
  family: string;
  version: number;
  prior_version: number | null;
  promoted_at: string;
  auc: number | null;
  n_oos: number | null;
}

// One persisted point per calendar day (scripts/run_learning_snapshot.py, chained after the
// nightly retrain) — daily training visible even on nights the champion does not flip. Fields
// are null when a metric was not determinable that day (no champion yet, nothing resolved yet
// in the rolling window) — an honest gap, never a fabricated 0.
export interface DailyCurvePoint {
  snapshot_date: string;
  created_at: string;
  n_train: number | null;
  n_resolved: number | null;
  hit_rate: number | null;
  rank_ic: number | null;
}

export interface ModelHistoryResponse {
  available: boolean;
  families: Record<string, ModelHistoryPoint[]>;
  promotions: Promotion[];
  resolved_windows: ResolvedWindow[];
  daily_curve: DailyCurvePoint[];
  // Same structural pipeline caveats as ModelResponse.caveats — see
  // equity_scout.constants.MODEL_CAVEATS. Optional so an older cached/served API response
  // (before this field existed) still parses instead of crashing the panel.
  caveats?: string[];
  disclaimer: string;
}

export async function fetchModelHistory(): Promise<ModelHistoryResponse> {
  const response = await fetch("/api/model/history");
  if (!response.ok) throw new Error(`/api/model/history returned ${response.status}`);
  return response.json();
}

export interface EvidenceEvent {
  source: string;
  ticker: string;
  event_key: string;
  event_date: string;
  details: Record<string, unknown>;
}

export interface PersonScore {
  person: string;
  source: string;
  scoreable: boolean;
  n_calls: number;
  hit_rate_long: number | null;
  weighted_score: number | null;
  [key: string]: unknown;
}

export interface EvidenceAlert {
  ticker: string;
  /** Company name joined server-side from the watchlist / last run; null when unknown. */
  name: string | null;
  created_at: string;
  reasons: string[];
  text: string;
  [key: string]: unknown;
}

export interface EvidenceResponse {
  events_by_ticker: Record<string, EvidenceEvent[]>;
  recent_alerts: EvidenceAlert[];
  stats_by_source: Record<string, Record<string, unknown>>;
  person_scores: PersonScore[];
  disclaimer: string;
}

export async function fetchEvidence(): Promise<EvidenceResponse> {
  const response = await fetch("/api/evidence");
  if (!response.ok) throw new Error(`/api/evidence returned ${response.status}`);
  return response.json();
}

export interface StackResponse {
  ticker: string;
  screener: {
    bucket: string;
    composite: number | null;
    factors: Record<string, number> | null;
    run_created_at: string | null;
  } | null;
  radar: WatchlistEntry | null;
  ml: MlScoreStamp | null;
  evidence_events: EvidenceEvent[];
  person_scores: PersonScore[];
  disclaimer: string;
}

export async function fetchStack(ticker: string): Promise<StackResponse> {
  const response = await fetch(`/api/stack/${encodeURIComponent(ticker)}`);
  if (!response.ok) throw new Error(`/api/stack returned ${response.status}`);
  return response.json();
}

// --- Stock briefs (src/equity_scout/api.py → /api/briefs) -------------------------------
// One row per watchlist stock, carrying the answers to the four questions the phone card
// asks: which company (name/sector), is the price a good entry (zone verdict), what is the
// upside (analyst consensus — never our own forecast), how is it valued (KGV/score).
// Pre-generated by the nightly scripts/run_insights.py — never computed in the request
// (a warm local LLM call is ~5.6 s). null means "not generated yet", which the card says.
export interface StockInsight {
  generated_at: string;
  business: string | null;
  news_summary: string | null;
  headlines: string[];
  /** One short German line per headline. Empty for rows generated before this existed —
   *  the card then falls back to the English originals. */
  headlines_de: string[];
  model: string | null;
}

export interface StockChart {
  as_of: string;
  first_date: string;
  last_date: string;
  /** Downsampled 1-year closes; first and last are the real endpoints. */
  closes: number[];
  /** One ISO day per close, so the chart's month ticks sit on real trading days.
   *  Empty for cache rows written before the column existed. */
  dates: string[];
}

export interface StockBrief {
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  currency: string | null;
  price: number;
  score: number;
  score_band: string;
  zone_low: number;
  zone_high: number;
  in_zone: boolean;
  zone_gap_pct: number | null;
  zone_verdict: string;
  /** One sentence relating the timing observation (our zone) to the value claim (analyst
   *  upside) — they answer different questions and read as a contradiction side by side. */
  entry_note: string;
  analyst_target: number | null;
  analyst_count: number | null;
  analyst_upside_pct: number | null;
  trailing_pe: number | null;
  model_target: number | null;
  model_stop: number | null;
  insight: StockInsight | null;
  chart: StockChart | null;
}

export interface BriefsResponse {
  briefs: StockBrief[];
  disclaimer: string;
}

export async function fetchBriefs(limit = 12): Promise<BriefsResponse> {
  const response = await fetch(`/api/briefs?limit=${limit}`);
  if (!response.ok) throw new Error(`/api/briefs returned ${response.status}`);
  return response.json();
}
