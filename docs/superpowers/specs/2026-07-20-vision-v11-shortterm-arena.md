# Vision v11 — Kurzfrist-Arena: three short-term paper lanes, honestly raced

**Date:** 2026-07-20 · **Status:** approved for autopilot build (Nico: "alles davon umsetzen
und dann jeweils tracken und schauen was sich am ende mehr rentiert")

## What this is

Three independent short-term paper-trading lanes, each with its own 10,000 USD, its own
track record, and ONE comparison surface ("Kurzfrist-Arena") that shows which — if any —
survives its costs. The system's stance stays: this is a measurement harness. Retail
short-term alpha is research-backed unlikely; the arena's job is to show the truth either
way, not to promise it. Every lane is long-only in v1 (short selling needs borrow/margin
realism we don't have — backlog), every fill charges fees+slippage, every surface carries
the DISCLAIMER.

## The three lanes (fixed lane keys: `swing`, `session`, `crypto`)

### 1. `swing` — Event-Swing-Trader (US equities, 1–5 days)
- Signals from the EXISTING v7 event engine: `classified_events` rows (earnings beat /
  positive guidance) seen since the previous run and before today's close.
- Entry: buy at today's adjusted close (the repo's look-ahead-safe daily convention);
  size 10 % of lane equity per trade, max 8 open positions, never re-enter a ticker
  already held.
- Exit at daily close: profit target +5 %, stop −3 %, max holding 5 trading days.
- Runs in the nightly chain (after the auto-depot step). Benchmark: SPY.

### 2. `session` — Intraday-Session-Trader (US equities, 15-min bars, delayed data)
- Universe: 12 liquid megacaps/ETFs (SPY, QQQ, AAPL, MSFT, NVDA, AMZN, META, GOOGL,
  TSLA, AMD, AVGO, NFLX).
- Data: yfinance 15-minute bars, which are ~15 min DELAYED. Honesty model: only bars whose
  END is ≥ 20 min in the past are usable ("settled"); a signal on bar N fills at the OPEN
  of bar N+1 — both already observed, so the ledger runs on the bar timeline, slightly
  behind wall-clock, and can never use a price before it was knowable. 5 bps slippage/side.
- Strategy v1: Opening-Range-Breakout — first 30 min high/low; break above ORH (with the
  range as risk unit) → long. Stop = entry − 0.5×range, target = entry + 1×range,
  **force-flat at session end** (never holds overnight).
- Runs as a step in the existing */15 `intraday_copilot.sh` (market-window guarded).
  Benchmark: SPY. Expectation stated openly: after costs this likely loses — showing that
  cleanly is the point.

### 3. `crypto` — Crypto-Daytrader (real-time data, 24/7)
- The one market with FREE real-time data: Kraken public REST `/0/public/OHLC` (keyless).
  Pairs: BTC/USD, ETH/USD, SOL/USD, XRP/USD; 15-minute bars, no delay model needed.
- Strategy v1: Donchian breakout (Turtle-style): entry on a 20-bar-high breakout, exit on
  a 10-bar-low break or a −2 % stop. One position per pair, 25 % of lane equity each.
  10 bps slippage/side (crypto spreads).
- Runs via its own cron line every 15 min around the clock (installer-managed, flock),
  idempotent per bar (last-processed marker per pair). Benchmark: BTC buy-and-hold —
  beating cash is easy in a bull market; beating BTC is the honest bar.

## Shared plumbing

- **`shortterm_book.py`** (pure): a lightweight share-based book per lane — cash,
  positions (qty, entry price/time), `buy`/`sell` at an explicit price with fee+slippage
  bps, mark-to-market, valuation vs benchmark, and per-trade REALIZED P&L (win-rate and
  cost totals are first-class — "was rentiert sich" needs them). Deliberately NOT
  `portfolio.py` (that is coupled to Instruments/dividends/screener flow).
- **`shortterm_storage.py`**: one `shortterm.db`, lane-keyed tables mirroring the house
  idiom — `st_books(lane PK, data JSON)`, `st_valuations(lane, created_at, …,
  UNIQUE(lane, created_at))`, `st_trades(lane, executed_at, ticker, side, qty, price,
  fees, realized_pnl, reason, UNIQUE(lane, ticker, executed_at, side))`,
  `st_state(lane, key, value)` for per-lane markers.
- **`scripts/run_shortterm.py --lane swing|session|crypto`** — one runner, three lanes.
- **Surfaces:** `/api/shortterm` (per lane: equity curve, open positions, recent trades,
  stats: total return, max drawdown, n trades, win rate, fees paid); DepotsView tab
  "Kurzfrist-Arena" (comparison table + curves + open positions + honesty note); digest
  block "⚡ Kurzfrist-Arena" (one line per lane: return since start, trades today).
- Valuations are daily snapshots (the intraday lanes additionally value on each run;
  UNIQUE(lane, created_at) keeps one row per timestamp).

## Honesty rules (non-negotiable)
- Delayed data never fills at a price older than the signal (session lane's settled-bar
  gate). No overnight holds in `session`. No shorts anywhere in v1. All costs explicit.
  Lane benchmarks chosen adversarially (crypto vs BTC, not vs cash). The arena view says
  in plain German that the expected after-cost result for day-trading lanes is negative
  and that the arena exists to measure, not to promise.

## Gate
`uv run pytest -q` + `uv run ruff check .` per task; FE tasks also typecheck+build. All
engines pure and offline-tested; network (yfinance intraday, Kraken) behind provider seams
faked in tests.
