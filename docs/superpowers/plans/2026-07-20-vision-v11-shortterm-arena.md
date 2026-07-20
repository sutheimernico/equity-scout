# Plan: Vision v11 — Kurzfrist-Arena (swing / session / crypto)

**Spec:** `docs/superpowers/specs/2026-07-20-vision-v11-shortterm-arena.md` · **Branch:** `autopilot/work`
**Gate per task:** `uv run pytest -q` + `uv run ruff check .` (FE also typecheck+build) · Conventional Commits.

## Wave A — shared plumbing (pure + storage)

- [ ] **A1 book** — `src/equity_scout/shortterm_book.py`: `LaneBook` (cash, positions
  {ticker: qty, entry_price, opened_at}), `buy(book, ticker, price, ts, *, fraction,
  fee_bps, slippage_bps)`, `sell(book, ticker, price, ts, reason)` → (book, TradeFill with
  realized_pnl), `mark_to_market(book, prices)`, `valuation(book, prices, benchmark_price,
  ts)`, `stats(trades)` (win rate, fees, n). Tests: buy/sell round trip w/ costs, realized
  pnl sign, valuation vs benchmark, insufficient cash no-op.
- [ ] **A2 storage** — `src/equity_scout/shortterm_storage.py`: `shortterm.db`, tables per
  spec (st_books JSON blob per lane, st_valuations, st_trades, st_state KV per lane), all
  INSERT OR IGNORE on natural keys. Tests: round trip, idempotent double-insert, per-lane
  isolation.

## Wave B — swing lane (nightly, events → 1–5 day holds)

- [ ] **B1 engine** — `src/equity_scout/st_swing.py`: `pick_entries(events, book, today)`
  (beat/positive-guidance events since last run, not already held, cap 8 positions),
  `check_exits(book, prices, today)` (+5 % / −3 % / 5 trading days). Pure, tests with
  canned events/prices incl. re-entry block and max-holding.
- [ ] **B2 runner lane** — `scripts/run_shortterm.py --lane swing`: load main-db events +
  daily closes (ETF/ML panel reuse or per-ticker quote), exits then entries at today's
  close, persist book+valuation+trades. Nightly step `st_swing` in `nightly_train.sh`
  after `autotrader`. Test: end-to-end with fakes.

## Wave C — session lane (intraday 15m, delayed-data honesty)

- [ ] **C1 bars provider** — `src/equity_scout/intraday_bars.py`: yfinance 15m bars for the
  12-ticker universe, `settled_bars(now)` gate (bar end ≥ 20 min past), pure cleaning; seam
  faked in tests.
- [ ] **C2 engine** — `src/equity_scout/st_session.py`: opening range (first 30 min),
  breakout entry at next settled bar open, stop/target/force-flat exits, per-day state
  (or_high/low, last processed bar) via st_state. Pure, tests: ORB math, fill-at-next-open,
  flat at session end, idempotent bar processing.
- [ ] **C3 chain step** — `run_shortterm.py --lane session` + step in `intraday_copilot.sh`
  (inside the market-window guard). Test: end-to-end with faked bars.

## Wave D — crypto lane (real-time, 24/7)

- [ ] **D1 provider** — `src/equity_scout/kraken_data.py`: public OHLC endpoint (keyless),
  15m bars for BTC/ETH/SOL/XRP-USD, stdlib urllib like telegram_client, honest None on
  failure. Tests fake the transport.
- [ ] **D2 engine** — `src/equity_scout/st_crypto.py`: Donchian 20-high entry / 10-low or
  −2 % stop exit, one position per pair, 25 % equity each, idempotent per bar via st_state
  marker. Pure, tests with synthetic bar series (breakout, stop, no-repeat on same bar).
- [ ] **D3 cron** — `run_shortterm.py --lane crypto` + installer-managed crontab line
  `*/15 * * * *` with flock. BTC buy-and-hold benchmark captured at first run.

## Wave E — surfaces

- [ ] **E1 API** — `/api/shortterm`: per lane equity curve, open positions, last 20 trades,
  stats (return, max drawdown, win rate, n trades, fees). Tests: seeded + empty.
- [ ] **E2 frontend** — DepotsView 6th tab "Kurzfrist-Arena": comparison table (3 lanes ×
  return/maxDD/win-rate/trades/fees), equity curves, open positions, honesty Explain
  (delay model, long-only, negative expectation stated). Gate: typecheck+build.
- [ ] **E3 digest** — "⚡ Kurzfrist-Arena" block: one line per lane (return since start,
  trades today); absent while no lane has data. Tests.

## Wave F — closure

- [ ] **F1 docs** — README section, scheduling.md (new crypto cron line), PLAN.md phase
  entry with honest framing.
- [ ] **F2 live smoke + outcome** — run all three lanes once for real (crypto + swing will
  trade/skip honestly; session outside market hours books nothing), verify DB/API/digest,
  fill outcome below. Full gate green.

## Outcome

_(filled after F2)_
