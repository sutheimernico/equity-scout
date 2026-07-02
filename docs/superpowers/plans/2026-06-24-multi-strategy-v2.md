# Plan: Multi-Strategy Paper-Trading + ML Meta-Model (v2)

**Source of truth (vision):** `docs/superpowers/specs/2026-06-24-multi-strategy-ml-vision.md`
**Research / decisions:** `docs/research/2026-06-24-strategy-ml-data-research.md`
**Started:** 2026-06-24 · interactive autonomous build (Nico granted full local autonomy).

Generalises the existing **one buy-and-hold paper account** into **N systematic strategies as N
paper accounts** (dashboard tabs) + an **ML meta-model** that learns whether/how much to follow each
signal, with a feedback loop. Build as vertical slices, one phase per branch, merged to `main` only
on a green gate (`uv run pytest -q` + `uv run ruff check .`).

## Non-negotiable methodology (from spec + research)
- Paper-only. No real money, ever.
- No look-ahead: `position[t] = decide(data ≤ t-1)`, fill at t close. Fit ML only on data ≤ t.
- Costs + slippage always: flat 10 bps/round-trip on traded notional + sweep {0,5,10,20}.
- Total-return: returns from Adj Close (`auto_adjust`, `repair`, pinned, daily, Parquet snapshot);
  share counts / costs from raw Close.
- Walk-forward, never in-sample-only. Report OOS + after-cost. **Deflated Sharpe**, not raw Sharpe.
- Honest framing everywhere: process / education / risk — no alpha promise. Disclaimer on every surface.

## Architecture seam (the core new abstraction)
```
Strategy(Protocol):
    name: str
    def decide(self, as_of, market: MarketView, state: AccountState) -> list[TargetWeight]
```
- `TargetWeight(ticker, weight)` — target portfolio weights. DCA = growing weights as cash is added;
  Vol-Targeting = weight scaled by σ_target/σ̂; GEM/DAA = 100% on chosen asset; 60/40 = fixed.
- `MarketView` — multi-asset OHLCV access as-of a date, total-return-aware, look-ahead-safe
  (only returns data strictly before `as_of`).
- **Engine** turns target weights into trades (rebalance), applies costs, marks to market daily.
  **Backtest = engine over history; forward-paper = engine one step per scheduler run. Same code.**

---

## Phase A — Strategy seam + backtest engine + 2 strategies  [VERTICAL SLICE — DONE 2026-06-25]
Goal: one command backtests a strategy over the ETF basket and prints honest metrics.
**Outcome:** built `market.py` (look-ahead-safe `MarketView`), `strategies/` (base seam + 60/40 +
GEM + registry), `engine.py` (weight-based backtest, turnover costs), `metrics.py` (full ratio canon
+ Deflated Sharpe / PSR, in-house, no metrics dep), `data/etf_panel.py` (yfinance loader + CSV
snapshot), `scripts/run_backtest.py`. Added pandas/numpy as explicit deps. 29 new tests, gate green.
Live-verified over 2007-2026 (10 ETFs): 60/40 Sharpe 0.75 / MaxDD -32.6%, GEM Sharpe 0.56 / turnover
3.6x — the cost sweep shows GEM's edge eaten by turnover. Honest, plausible. Deviation: dropped
`empyrical` (own metrics) and made yfinance `repair` scipy-optional (scipy arrives in Phase E).
- [x] `etf_universe.py` — the 10-ETF basket as constants + a multi-asset OHLCV loader (yfinance,
      `auto_adjust=True`, `repair=True`, daily, Parquet snapshot under `data/prices/`). FakeProvider
      path for tests (deterministic synthetic price panels).
- [x] `market.py` — `MarketView` over a price panel: `prices_until(as_of)`, `returns_until`,
      `trailing_return(ticker, months)`, `realised_vol(ticker, window)`. Strictly `< as_of`.
- [x] `strategy.py` — `Strategy` Protocol + `TargetWeight`. Two strategies:
      `SixtyFortyStrategy` (fixed 60% SPY / 40% IEF), `DualMomentumStrategy` (GEM: 12m abs+rel
      momentum, SPY vs VEU, fallback IEF/BIL).
- [x] `engine.py` — backtest loop: monthly rebalance dates, `decide` on data ≤ t-1, rebalance at t
      close, flat-bps cost, daily mark-to-market → equity curve + trade log + turnover.
- [x] `metrics.py` — CAGR, ann. vol, Sharpe, Sortino, MaxDD, Calmar, turnover, Deflated Sharpe
      (own impl per López de Prado). Pin `empyrical-reloaded` as a checked backend where it helps.
- [x] `scripts/run_backtest.py --strategy {sixty_forty,gem} --costs-bps 10` → table of metrics +
      cost sweep {0,5,10,20}.
- [x] Tests: deterministic FakeProvider panel; assert no look-ahead (engine never reads ≥ t), known-input
      metric values, cost monotonicity (more bps → lower return). Gate green. Merge to `main`.

## Phase B — Remaining v1 strategies  [DONE 2026-06-25]
**Outcome:** added DCA (time-phased, state-free), Vol-Targeting (capped at 1.0), Permanent Portfolio,
and DAA (Keller canary, top-N diversified) — registry now serves 6. The User pair-edited the seam to
return typed `list[TargetWeight]` and dropped `AccountState` (YAGNI); all strategies state-free.
Live over 2007-2026: Permanent best risk-adjusted (Sharpe 0.92 / MaxDD -17.6%), DAA highest CAGR
(9.8%) but cost-sensitive (sweep 7.3→4.8). Multi-account *persistence* deferred — backtest-on-the-fly
+ cache serves the dashboard now; forward-paper persistence will be built with the feedback loop (F).

## Phase C — Dashboard tabs + equity chart + metrics/cost harness  [DONE 2026-06-25]
**Outcome:** `strategy_service.build_reports` + `/api/strategies` (app-local cache, graceful w/o
snapshot). Frontend: top-level nav (Strategien | Aktien-Screener, funnel extracted to FunnelView),
per-strategy tab with an in-house SVG equity curve vs 60/40, metric tiles w/ tooltips, current
allocation, cost-sweep bars, recent rebalances, and a compare tab. typecheck + vite build green,
live-verified (all endpoints 200).

## Phase B-orig — Multi-account persistence (superseded — see Phase F outcome)
**Superseded 2026-07-01:** this draft's design (`portfolio_storage.py` generalised with an
`accounts` table) was never built; Phase F shipped a different, simpler persistence path instead —
`forward_storage.py`'s `forward_accounts` table keyed by `strategy_name`, one row per strategy. The
strategies listed here (DCA/VolTarget/DAA/Permanent) were all built in Phase B. Superseding design
decision, not open work — left unchecked intentionally as a record of the road not taken.
- [ ] ~~Generalise `portfolio_storage.py`: `accounts(id, name, strategy, initial_capital, benchmark,
      created_at)` + `account_id` FK on portfolio/valuations/trades. Migrate the single account.~~
- [ ] ~~Each account: backtest to seed equity history, then forward-advanceable.~~
- [ ] ~~`scripts/run_paper.py` advances **all** accounts one step.~~ → `run_forward_paper.py` instead.

## Phase C-orig — Dashboard tabs (superseded — see the Phase C above, [DONE 2026-06-25])
**Superseded 2026-07-01:** early draft of the same phase; the shipped version above covers this
scope (API + tabs + equity chart + compare tab) — nothing left open here.

## Phase D+E — ML meta-model  [DONE 2026-06-25]
**Outcome:** built the `ml/` package — `labeling.py` (triple-barrier meta-labels), `features.py`
(regime features: vol/trend/breadth/drawdown/momentum, orthogonal to the primary signal),
`meta_model.py` (elastic-net logistic + purged+embargoed walk-forward, OOS exposure curve, 1-day lag
= no look-ahead). Wired into `strategy_service.build_ml_report` + `/api/ml` + an "ML-Meta" dashboard
tab (OOS equity vs SPY, hit-rate/exposure tiles, learned feature-importance bars). Added
scikit-learn + scipy (BSD). Live 2007-26: 69% OOS hit-rate, breadth+drawdown the top learned
features, MaxDD halved vs SPY (-23% vs -55%), Sharpe 0.72 vs 0.61 — honest risk reduction, no alpha.
**Deviation from plan:** used price-derived regime features (no FRED key needed → stays autonomous);
FRED enrichment (VIX/term-spread/HY-spread) is a documented future extension. The walk-forward's
per-fold re-training already realises the "periodic retraining" half of the feedback loop.

## Phase D-orig — FRED regime data (superseded — see Phase F's "Still open" list)
**Superseded 2026-07-01:** built later and differently — `ml/fred.py` uses a free public CSV (no
API key needed, so it stays autonomous) rather than a keyed provider; joins the search space when a
snapshot exists. `T10Y2Y`/`VIXCLS` etc. as originally scoped here were not all pulled in — only
`vix`/`term_spread` proved useful in the champion search. Nothing left open here.
- [ ] ~~`fred_provider.py` (free key via env, cached, look-ahead-safe; T10Y2Y/VIXCLS/BAMLH0A0HYM2/
      NFCI/STLFSI4/T10YIE/DGS10). FakeFred for tests.~~ → `ml/fred.py`, no-key CSV instead.
- [ ] ~~`features.py` — meta-features orthogonal to primary signal...~~ → done in Phase D+E's `features.py`.

## Phase E-orig — ML meta-model (superseded — see Phase D+E above, [DONE 2026-06-25])
**Superseded 2026-07-01:** early draft of the same phase; the shipped `ml/` package (labeling,
meta_model, purged walk-forward) plus Phase F's `ml/pbo.py` (CSCV/PBO) and `ml/search.py` (the
config search, which subsumes "ML-meta as its own account") cover this scope. Nothing left open here.
- [ ] ~~`labeling.py` — triple-barrier labels + meta-labels, sample-weight by uniqueness.~~ → done.
- [ ] ~~`meta_model.py` — Elastic-Net logistic baseline + CatBoost; `P(follow)` → position size.~~ → done.
- [ ] ~~`validation.py` — purged K-fold + embargo, Deflated Sharpe + PBO gate, trial counting.~~
      → `meta_model.purged_walk_forward` + `ml/pbo.py` + `ml/ledger.py`.
- [ ] ~~ML-meta as its own account...~~ → superseded by the Auto-Research champion search instead.

## Phase F — Continuous self-improving research loop  [DONE 2026-06-25]
**Outcome (Nico's "ML that keeps learning in the background, many dimensions, no overfitting"):**
built a continuous search loop instead of naive re-training (which on fixed data = overfitting). It
searches MetaConfig points (features × {elastic_net, random_forest} × lookback × horizon × barrier),
evaluates each OOS via purged walk-forward, and records to a SQLite ledger (`ml/ledger.py`, idempotent
per config). The **Deflated Sharpe hurdle is recomputed from all trials** → it *rises as the search
widens*, so luck can't survive — the overfitting budget is built in. Champion = highest current DSR.
`scripts/run_research.py` runs it forever (resumable cursor); `/api/research` + an "Auto-Research"
dashboard tab show champion, trial count, rising hurdle, leaderboard, and which dimensions win (live,
5s poll). Live 8-trial run: search already beat the default model (champion MaxDD -19.8% vs -23%).

### Still open (future sessions)
- [x] Per-bet attribution / "why was it wrong" self-analysis (Nico's earlier wish): log each OOS
      decision + regime context; surface the most instructive misses. DONE: `ml/attribution.py` +
      `BetRecord` regime context, wired into `/api/ml` and rendered in `AttributionSection` (MLPanel).
- [ ] Forward-paper multi-account persistence: accounts advance in real time (not just backtest).
      (Built: `forward_paper.py` + `/api/forward` + Live tab; needs real calendar days to show a curve.)
      FIXED 2026-07-02: `advance_account`'s decision used `MarketView(panel, today + 1 day)`, which
      reveals data through today inclusive — the backtest engine never lets `decide` see the
      rebalance day's own close (`MarketView(panel, date)` excludes `date`), so the forward account
      had a one-day look-ahead edge the backtest never had, breaking their comparability. Now
      `MarketView(panel, today)` — exact boundary parity with `engine.run_backtest`. 1 new test pins
      the exact boundary (decide sees `as_of == today` but data only through yesterday).
- [x] PBO (probability of backtest overfitting) over the ledger as a second overfitting diagnostic.
      DONE: `ml/pbo.py` (CSCV) + `scripts/run_pbo.py`, shown first-class in the Auto-Research tab.
      ADR 0002 (2026-06-26) frames DSR-vs-PBO and the honest high-PBO takeaway.
- [x] FRED regime features (VIX/term-spread/HY-spread) as a feature-space extension. DONE: `ml/fred.py`
      (free public CSV, no key) joins the search space when a snapshot exists — `vix` is in the
      current champion's feature set, `term_spread` recurs among top configs.
- [x] Optionally let the ML-Meta tab serve the live champion instead of the default config.
      DONE 2026-07-01: `build_ml_report` takes an optional `MetaConfig`; `/api/ml` passes the
      ledger's current champion (`ml/ledger.champion`) when one exists, else the fixed baseline.
- [x] CatBoost as a third learner. DONE: in the search-space `MODELS` tuple; the current champion is
      a CatBoost model.

## Needs Nico
- Git remote / first-push decision (repo is local-only; no push without explicit go).
- Any paid resource (none planned — all sources above are free, no card).
