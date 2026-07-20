# Plan: Vision v11 — Kurzfrist-Arena (swing / session / crypto)

**Spec:** `docs/superpowers/specs/2026-07-20-vision-v11-shortterm-arena.md` · **Branch:** `autopilot/work`
**Gate per task:** `uv run pytest -q` + `uv run ruff check .` (FE also typecheck+build) · Conventional Commits.

## Wave A — shared plumbing (pure + storage)

- [x] **A1 book** — `src/equity_scout/shortterm_book.py`: `LaneBook` (cash, positions
  {ticker: qty, entry_price, opened_at}), `buy(book, ticker, price, ts, *, fraction,
  fee_bps, slippage_bps)`, `sell(book, ticker, price, ts, reason)` → (book, TradeFill with
  realized_pnl), `mark_to_market(book, prices)`, `valuation(book, prices, benchmark_price,
  ts)`, `stats(trades)` (win rate, fees, n). Tests: buy/sell round trip w/ costs, realized
  pnl sign, valuation vs benchmark, insufficient cash no-op.
- [x] **A2 storage** — `src/equity_scout/shortterm_storage.py`: `shortterm.db`, tables per
  spec (st_books JSON blob per lane, st_valuations, st_trades, st_state KV per lane), all
  INSERT OR IGNORE on natural keys. Tests: round trip, idempotent double-insert, per-lane
  isolation.

## Wave B — swing lane (nightly, events → 1–5 day holds)

- [x] **B1 engine** — `src/equity_scout/st_swing.py`: `pick_entries(events, book, today)`
  (beat/positive-guidance events since last run, not already held, cap 8 positions),
  `check_exits(book, prices, today)` (+5 % / −3 % / 5 trading days). Pure, tests with
  canned events/prices incl. re-entry block and max-holding.
- [x] **B2 runner lane** — `scripts/run_shortterm.py --lane swing`: load main-db events +
  daily closes (ETF/ML panel reuse or per-ticker quote), exits then entries at today's
  close, persist book+valuation+trades. Nightly step `st_swing` in `nightly_train.sh`
  after `autotrader`. Test: end-to-end with fakes.

## Wave C — session lane (intraday 15m, delayed-data honesty)

- [x] **C1 bars provider** — `src/equity_scout/intraday_bars.py`: yfinance 15m bars for the
  12-ticker universe, `settled_bars(now)` gate (bar end ≥ 20 min past), pure cleaning; seam
  faked in tests.
- [x] **C2 engine** — `src/equity_scout/st_session.py`: opening range (first 30 min),
  breakout entry at next settled bar open, stop/target/force-flat exits, per-day state
  (or_high/low, last processed bar) via st_state. Pure, tests: ORB math, fill-at-next-open,
  flat at session end, idempotent bar processing.
- [x] **C3 chain step** — `run_shortterm.py --lane session` + step in `intraday_copilot.sh`
  (inside the market-window guard). Test: end-to-end with faked bars.

## Wave D — crypto lane (real-time, 24/7)

- [x] **D1 provider** — `src/equity_scout/kraken_data.py`: public OHLC endpoint (keyless),
  15m bars for BTC/ETH/SOL/XRP-USD, stdlib urllib like telegram_client, honest None on
  failure. Tests fake the transport.
- [x] **D2 engine** — `src/equity_scout/st_crypto.py`: Donchian 20-high entry / 10-low or
  −2 % stop exit, one position per pair, 25 % equity each, idempotent per bar via st_state
  marker. Pure, tests with synthetic bar series (breakout, stop, no-repeat on same bar).
- [x] **D3 cron** — `run_shortterm.py --lane crypto` + installer-managed crontab line
  `*/15 * * * *` with flock. BTC buy-and-hold benchmark captured at first run.

## Wave E — surfaces

- [x] **E1 API** — `/api/shortterm`: per lane equity curve, open positions, last 20 trades,
  stats (return, max drawdown, win rate, n trades, fees). Tests: seeded + empty.
- [x] **E2 frontend** — DepotsView 6th tab "Kurzfrist-Arena": comparison table (3 lanes ×
  return/maxDD/win-rate/trades/fees), equity curves, open positions, honesty Explain
  (delay model, long-only, negative expectation stated). Gate: typecheck+build.
- [x] **E3 digest** — "⚡ Kurzfrist-Arena" block: one line per lane (return since start,
  trades today); absent while no lane has data. Tests.

## Wave F — closure

- [x] **F1 docs** — README section, scheduling.md (new crypto cron line), PLAN.md phase
  entry with honest framing.
- [x] **F2 live smoke + outcome** — run all three lanes once for real (crypto + swing will
  trade/skip honestly; session outside market hours books nothing), verify DB/API/digest,
  fill outcome below. Full gate green.

## Outcome

_(filled after F2)_
**All 15 tasks DONE 2026-07-20 (single session, waves A–F).** Gate: **1042 tests**
(1000 → 1042) + ruff + FE typecheck/build green.

**Live smoke (real, Monday 2026-07-20 evening):**
- `crypto` ran against Kraken REAL-TIME (keyless): BTC benchmark captured, no Donchian
  breakout on that bar — honestly 0 fills. Cron `*/15` installed and live.
- `swing` ran real: no fresh bullish events in the last 24 h — honestly 0 fills,
  valuation booked. Nightly step live.
- `session` processed the REAL Monday US session on delayed bars: 7 fills — MSFT ORB
  entry → target +10.77 USD realized, AMZN/AVGO stopped out, META entered late. That
  leftover open META position exposed a REAL gap (the 15:45 ET bar never settles before
  the intraday window closes) → fixed with the **overnight sweep** (outside the window,
  `--lane session` flattens leftovers at the last settled close; wired into
  nightly_train.sh). Sweep live-proven: META flattened at 645.54 (−5.58 realized),
  lane flat overnight. Also fixed en route: fetch_bars single-ticker MultiIndex columns.

**Deviations:** crypto fills at the signal bar's close + slippage (not "next bar open" —
with real-time data the just-closed bar IS the next observable price; documented in
st_crypto docstring). Session force-flat has two layers now (in-session last-bar rule +
overnight sweep) instead of one.

**Open:** first real comparison data accumulates from tonight's chains; backlog items
(shorts need borrow realism; Alpaca IEX real-time upgrade for the session lane) live in
PLAN.md.
