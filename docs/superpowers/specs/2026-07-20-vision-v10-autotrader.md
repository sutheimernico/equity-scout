# Vision v10 — Autotrader ("Auto-Depot"): meta-allocated, risk-managed paper depot

**Date:** 2026-07-20 · **Status:** approved for autopilot build (Nico direction: "bau den Autotrader, setz alles an die Vision")

## What this is

One automatically traded **paper** depot that combines every existing strategy lane into a single
book: the strategy sleeves (DCA, 60/40, Permanent, VolTarget, GEM, DAA, SectorRotation) plus the
ML entry bots (long, and short once a champion exists) are meta-weighted, aggregated look-through
to per-ticker target weights, transformed by a composable risk layer, and executed daily by the
existing look-ahead-safe close-fill engine conventions. Every trade, weight, and risk intervention
is persisted and surfaced (Telegram digest section, `/api/autodepot`, dashboard "Auto-Depot" tab).

**What this is NOT:** an edge promise. The iron project constraints stand unchanged — local & free,
**no real-money trading, no order routing — ever** (LOOP.md). The autotrader is the most honest
automatic depot buildable on free daily data; the deliverable is disciplined automation +
measurement, not predicted riches. Every surface carries the `DISCLAIMER`.

## Design (research-backed, sources in plan doc)

### 1. Meta-allocation (sleeve weights)
- Sleeves: `default_strategies()` **minus `EnsembleStrategy`** (it is itself a blend of the same
  strategies — double counting), plus `MLLongStrategy`/`MLShortStrategy` when `.ready`.
- Sleeve performance source: daily returns derived from `forward_valuations` equity series (the
  sleeves keep running as measurement instruments; the autotrader never re-simulates them).
- Weighting: **50 % equal-weight anchor + 50 % Sharpe-softmax** on a trailing walk-forward window
  (63 trading days), per-sleeve floor 5 % / cap 40 %, renormalised. Rationale: the 1/N literature
  (DeMiguel et al. 2009) says estimation error eats optimisation on short samples; the anchor is
  the shrinkage. Recomputed **monthly** (state KV gate), only from history strictly before the
  recompute date.
- Honest fallback: while sleeves have < 60 overlapping return observations, weights are pure
  equal-weight and are labelled as such ("Anker-Phase — zu wenig Forward-Historie für Tilt")
  everywhere they are shown. Same honesty pattern as `MLBot.ready`.

### 2. Risk layer (composable protections, freqtrade/LEAN pattern)
Applied IN ORDER to the aggregated target weights; each protection returns the transformed
weights plus an optional `risk_event` row (persisted, surfaced):
1. **ConcentrationCap** — |weight| per single ticker capped at 10 %; clipped mass becomes cash
   (never redistributed — same honesty as `_confidence_weights`).
2. **RegimeGate** — regime light red → gross exposure × 0.5. Yellow/green/unknown: no action
   (unknown must not punish — honesty rule).
3. **VolTarget** — target 12 % annualised; scale = min(1, target / realised 20d depot vol) from
   own valuation history; inactive (scale 1, labelled) until ≥ 21 valuation points. Never levers up.
4. **DrawdownBreaker** (stateful, hysteresis): drawdown from peak equity ≥ 10 % → exposure × 0.5;
   ≥ 20 % → fully to cash. Recovery one stage at a time after a 10-trading-day cooldown AND
   drawdown back below 8 % / 15 %. State lives in the account row.
Deliberately absent: Kelly sizing (needs 50–100 realised trades to estimate inputs — backlog until
the depot has that history).

### 3. Execution
- Same look-ahead-safe convention as `forward_paper.py`: decisions see strictly < today
  (`MarketView`), fills at today's adjusted close, mark-to-market by weight drift.
- Costs: `costs_bps = 10` on turnover (covers slippage ~2 bps/side + spread + the ~0.2 bps
  sell-side regulatory fees — itemising those would be false precision), borrow proxy
  1 bps/day on net short exposure, margin floor force-flat (reuse forward_paper constants).
- Shorts net across sleeves at the ticker level (long bot vs short bot on the same name nets —
  correct at depot level).
- Panel: column-wise join of the ETF panel and the ML-bots stock panel (+ SPY). No common-range
  trim (a young ticker must not truncate the ETF history).
- **Not built (documented backlog):** next-open fills. Would require a parallel OHLC data world;
  at daily cadence on liquid ETFs/large caps the realism delta is a few bps, already covered by
  the conservative cost assumption.

### 4. EUR reporting
Daily spot conversion at valuation time (`fx.eur_rate("USD")`), stored per valuation row
(`equity_eur`, `fx_rate`). Currency-translation P&L is reported as its own line, never mixed into
strategy return (MSCI: no risk-adjusted benefit to hedging USD for EUR investors — no hedge
simulation). FX fetch failure → `equity_eur = NULL`, never invented.

### 5. Persistence (`autotrader_storage.py`, house idiom: idempotent CREATE IF NOT EXISTS)
- `autotrader_account(id PK=1, data JSON)` — equity, weights, peak equity, breaker state,
  last_as_of, current sleeve weights.
- `autotrader_valuations(created_at UNIQUE, equity, total_return, benchmark_equity,
  benchmark_return, equity_eur, fx_rate, gross_exposure, drawdown)`
- `autotrader_trades(created_at, ticker, delta_weight, notional, cost, UNIQUE(ticker, created_at))`
  — trades are first-class rows: this IS the future broker seam (an adapter would consume exactly
  these), no speculative interface built.
- `autotrader_sleeve_weights(month, strategy_name, weight, sharpe, mode, UNIQUE(month, strategy_name))`
- `autotrader_risk_events(created_at, protection, action, detail)`
- Benchmark: SPY, initial capital 100 000 USD.

### 6. Surfaces
- **Digest section "🤖 Auto-Depot"** (before-digest step order!): equity € + $, day/total return
  vs SPY, gross exposure, today's trades (capped), risk interventions, weight mode
  (Anker-Phase vs Tilt).
- **`/api/autodepot`**: account summary, valuations, recent trades, sleeve weights, risk events.
- **Dashboard**: 5th tab "Auto-Depot" in `DepotsView` (equity curve vs benchmark, sleeve weights,
  trades, risk events). UI copy German.
- **Cron**: new step `autotrader` in `daily_copilot.sh` after `lanes`, **before `digest`**.
  Idempotent per date (forward_paper `last_as_of` pattern) — safe on re-runs.

### 7. Broker seam (documentation only — no code)
Facts for a later, Nico-decided integration recorded in README/docs: Alpaca paper API (free,
globally available, 200 req/min), Trading 212 public API beta (`demo.trading212.com` practice
endpoints, Invest/ISA only), IBKR paper account (same API paper/live, needs TWS/Gateway process).
Activating ANY of these requires Nico to change the LOOP.md iron constraint — the loop never does.

## Gate
`uv run pytest -q` green + `uv run ruff check .` clean per task; FE tasks additionally
`npm run typecheck` + `npm run build`. New logic ships with tests (pure engine/allocator/
protections fully offline; storage via tmp_path; no live network in tests).
