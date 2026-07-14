# equity-scout

Local, free research harness with two parts, switchable from the dashboard top nav:

1. **Strategien** — N systematic strategies as own paper accounts over a 10-ETF basket (DCA, 60/40,
   Permanent Portfolio, Vol-Targeting, Dual-Momentum/GEM, Defensive Asset Allocation), each backtested
   over ~19 years **after costs** vs 60/40, plus an **ML meta-model** (triple-barrier meta-labeling,
   purged walk-forward) that learns *whether to follow* the trend signal from the market regime,
   plus a **continuous research loop** that searches model configurations in the background and gets
   better by widening the search — with a Deflated-Sharpe hurdle that rises with every trial to block
   overfitting (it cannot improve by re-fitting the same data; only by honest, OOS-validated search).
2. **Aktien-Screener** — the original quant factor screen over a global stock universe → risk buckets
   → LLM thesis → drilldown.

The strategies also run **forward** as live paper accounts (Live tab — a true out-of-sample track that
builds over real time), the ML tab carries **per-bet self-analysis** (where the model was wrong, in
which regime) and a second overfitting check (**CSCV-PBO**), and an **Assistent** tab answers questions
about the current numbers via a local **Ollama** model (no data leaves the machine).

**Research assistant — not investment advice, no edge promise.** Every result is after-cost and
out-of-sample; the honest takeaway is process/risk, not alpha (see `docs/research/`).

![Strategies dashboard — six systematics measured honestly against 60/40](docs/img/strategies.png)

![ML meta-model — should you follow the signal at all? OOS vs holding SPY](docs/img/ml-meta.png)

![Stock screener — global factor funnel into risk buckets, no ML, no advice](docs/img/screener.png)

The dashboard needs a locally running backend (FastAPI + SQLite + yfinance) — there is no hosted
demo. Start it with the quickstart below.

Docs: strategy/ML plan `docs/superpowers/plans/2026-06-24-multi-strategy-v2.md`,
research `docs/research/2026-06-24-strategy-ml-data-research.md`,
funnel design `docs/superpowers/specs/2026-06-24-equity-scout-design.md`.

## Quickstart (after `uv sync`)

```bash
# Strategies: backtest all 6 over the ETF basket (first run fetches the price panel; --refresh re-fetches)
uv run python scripts/run_backtest.py --refresh   # prints metrics + cost sweep {0,5,10,20} bps

# Continuous ML research loop in the background (resumable; the Auto-Research dashboard tab is live)
nohup uv run python scripts/run_research.py > research.log 2>&1 &

# Offline deterministic run (fake provider)
uv run python scripts/run_scout.py --provider fake --db equity_scout.db

# Refresh the combined universe snapshot (~7.5k tickers: every US-listed common stock incl.
# ADRs, plus STOXX 600, Nikkei 225, Hang Seng, CSI 300, KOSPI 200, NIFTY 100, TSX Composite,
# ASX 200, B3 and the curated CSV — see data/universe_combined.PROVENANCE.md)
uv run python scripts/refresh_universe.py

# Live run over the combined universe (yfinance, free; cached)
uv run python scripts/run_scout.py --provider yfinance --universe data/universe_combined.csv --db equity_scout.db

# Advance the paper portfolio against the latest picks (demo money, buy-and-hold; PAPER ONLY)
uv run python scripts/run_paper.py --db equity_scout.db --bucket balanced --threshold 0.70

# Advance the forward paper accounts one step (daily/cron; idempotent) → "Live (Forward)" tab
uv run python scripts/run_forward_paper.py --refresh

# Probability of Backtest Overfitting over the top configs (slow, occasional) → Auto-Research tab
uv run python scripts/run_pbo.py

# Local assistant ("Assistent" tab): run Ollama + pull a model (configurable via OLLAMA_MODEL)
ollama serve & ollama pull llama3.2

# Build the React dashboard once, then serve it
cd frontend && npm install && npm run build && cd ..
uv run python scripts/run_api.py --db equity_scout.db   # http://127.0.0.1:8000
```

The dashboard shows the risk buckets with a per-pick score-transparency drilldown
(percentile x weight = contribution) and the paper portfolio's value vs. a benchmark.
Scheduling a recurring run: see `docs/scheduling.md`. Factor definitions: `docs/factors.md`.

## Trading copilot (radar → pitch → one-tap decision)

On top of the screener, the copilot watches funnel finalists for genuinely attractive entry
prices and turns them into decision pitches (spec:
`docs/superpowers/specs/2026-07-04-trading-copilot-design.md`):

```bash
# 1. Radar: entry sub-signals + watchlist with entry zones (needs a prior run_scout run)
uv run python scripts/run_radar.py --db equity_scout.db --json-out watchlist.json

# 2. Notify: watchlist → inbox pitches (+ Telegram send if configured; --dry-run = inbox only)
uv run python scripts/run_notify.py --db equity_scout.db --dry-run

# 3. Receiver: long-polls Telegram for [Kaufen]/[Ablehnen]/[Später] button decisions
uv run python scripts/run_receiver.py --db equity_scout.db

# 4. Daily digest (prints to stdout when SMTP is not configured)
uv run python scripts/run_digest.py --db equity_scout.db

# 5. Arena: advance both paper lanes one step (nico = approved pitches, autopilot = score-autonomous)
uv run python scripts/run_lanes.py --db equity_scout.db   # daily/cron; idempotent per UTC day

# 6. Train: price-derived backfill → purged walk-forward → register/promote the champion model
uv run python scripts/run_train_entry.py --db equity_scout.db --tickers EXE,EQT,VICI,CF,WDC
#    (no --tickers → latest watchlist tickers, else a small fallback universe; --model, --start)

# 7. Score: the champion scores the current watchlist and LOGS each live prediction to the ledger
uv run python scripts/run_score_watchlist.py --db equity_scout.db   # the 'predict' half of the loop

# 8. Resolve: fill the realized outcome of every logged prediction whose 20-day horizon has elapsed
uv run python scripts/run_resolve_predictions.py --db equity_scout.db
```

Two paper lanes trade the same signals side by side with identical sizing, fills and exit
rules (profit target / stop loss / max holding period), each tracked against buy-and-hold SPY —
"Du vs. Autopilot vs. Markt". Lane "nico" only buys pitches you approved; lane "autopilot"
buys autonomously above the score threshold. PAPER ONLY — no real orders.

The entry-quality model scores each watchlist entry 0–100 = P(it beats SPY over ~20 trading days),
across three separate stages so the "the model improves" claim stays a queryable fact, not a
promise:

- **train** (`run_train_entry.py`) builds a strictly price-derived historical backfill (no
  fundamentals — yfinance has no history, so a fundamentals backfill would be look-ahead), scores
  it out-of-sample with a purged, date-grouped walk-forward, and promotes a challenger only on a
  strictly better OOS AUC;
- **score** (`run_score_watchlist.py`) has the current champion score today's watchlist and appends
  every live score to an immutable prediction ledger *before* the outcome is known;
- **resolve** (`run_resolve_predictions.py`) fills each prediction's realized outcome against real
  forward prices once its horizon has elapsed — never a back-filled guess.

The score RANKS entry attractiveness — it is a calibrated probability, not a price forecast and not
advice.

Dashboard endpoints: `GET /api/radar`, `GET /api/inbox`, `POST /api/inbox/{id}/decision`,
`GET /api/arena`, `GET /api/model` (registry, champion metrics, resolved-prediction stats),
`GET /api/evidence` (events, alerts, per-source hit-rates, person scores).

## External evidence + person track records

Five free external sources annotate pitches and can raise separately-labelled alerts —
they NEVER change the entry composite or selection rules:

```bash
# Collect congress trades / 13F fund moves / news themes / Form 4 insider buys / voices → store + ledger
uv run python scripts/run_evidence.py --db equity_scout.db

# Resolve due evidence rows against real forward prices vs SPY (60d horizon)
uv run python scripts/run_resolve_evidence.py --db equity_scout.db

# Measure person track records (weekly; backfills each active filer's full history)
uv run python scripts/run_person_scores.py --db equity_scout.db
```

- **US congress trades** (kadoa-org/congress-trading-monitor mirror, MIT): purchases only.
  Members may file up to **45 days** after trading. §105(c) STOCK Act restricts commercial
  use — fine for this private local tool, re-check before any publication.
- **13F filings** of ~8 tracked famous funds (SEC EDGAR): quarter-over-quarter new/increased
  positions, up to **135 days** stale. Needs `EDGAR_USER_AGENT` (SEC requires a contact);
  stays politely `unconfigured` without it.
- **News themes** (Google News RSS + MarketWatch + Fed press): deterministic cross-source
  bigram clusters; themes alone never alert (weakest, most-priced-in source).
- **Form 4 corporate-insider purchases** (SEC EDGAR, scoped to the current watchlist tickers):
  open-market buys only (transaction code P + acquired) by directors/officers/10%-owners of
  the companies you are actually watching — the fastest source, but insiders may still file up
  to **2 business days** after trading, so it is still a lag, never an early signal. Needs
  `EDGAR_USER_AGENT`; stays politely `unconfigured` without it. A single insider buying is
  routine noise; **3 or more distinct insiders** buying independently inside the alert window is
  the robust cluster signal (Cohen/Malloy/Pomorski) and raises an alert.
- **Voices** (Google News RSS + Bing News RSS person queries, free, undocumented feeds): what
  the tracked famous investors (the managers behind the 13F funds — Buffett, Burry, Ackman, …)
  **say in public**. These are mentions feeds, so the honest boundary is deterministic: a
  headline only becomes a **measurable call** when the speaker's name precedes a direction
  phrase from a closed list AND exactly one universe company resolves from the title — bullish
  calls enter ledger + person track record, bearish calls are shown and alerted but stay out of
  the statistics until signed resolution exists, everything else is context display only.
  A measurable call by a tracked person alerts alone (press headline, no filing).

Every collected event is logged to an append-only ledger BEFORE its outcome is knowable and
resolved later against real forward returns vs SPY — "does congress-following actually
work?" is a query (`/api/evidence`, digest section), not an opinion.

**Person track records:** every disclosed buyer (politician; funds and insiders as their
filings accumulate) is measured with our own methodology — T0 = filing date (the day a reader
could know), abnormal return vs SPY over 1M/3M horizons, **no score below 5 resolvable calls**,
recency-weighted (540d half-life). Measured records annotate pitches/alerts, and a single
buyer with a strong record (≥ +2 % weighted @3M) may alert alone — always labelled
"Historie, keine Prognose". A disclosed trade is a trade, not a recommendation (tax,
liquidity and diversification confound it) — the caveat rides on every surface.

**Alert escalation:** a ticker's alerts share a 14-day cooldown, but a cluster whose distinct
buyer count (across all four sources) grows past the last SENT alert breaks through the
cooldown — a 2-buyer alert must never silence the 4-buyer cluster that follows a week later.
The alert text marks the escalation.

## Automation (cron)

`scripts/daily_copilot.sh` runs the whole chain unattended (Mondays: screener + person
scores first): radar → evidence → notify → score → resolve ×2 → lanes → digest — every
step degrades independently into `copilot.log`. `scripts/receiver_keepalive.sh` keeps the
Telegram receiver alive under `flock`. Install both cron lines once with
`./scripts/install_crontab.sh`; details + WSL caveat in `docs/scheduling.md`.

**Dashboard.** The React dashboard leads with the four copilot surfaces — **Arena** (Du vs.
Autopilot vs. Markt, the default view), **Radar** (watchlist entry zones), **Inbox** (one-tap
buy/pass/later pitches), **Modell** (champion metrics + resolved-prediction honesty) — followed by
the research views (Strategien / Machine Learning / Aktien-Screener / Assistent), all in one dark
"trading-terminal" identity (near-black blue-violet base, phosphor-green signal, mono numerals).
Build once and serve it from the API: `cd frontend && npm run build && cd ..`, then
`uv run python scripts/run_api.py --db equity_scout.db` serves the built dashboard at
`localhost:8000`.

Environment variables (all optional — without them the pipeline degrades honestly to
inbox-only / stdout; set them in your local `.env`, never commit values):

| Variable | Purpose |
|---|---|
| `COPILOT_TG_BOT_TOKEN` | Telegram bot token (@BotFather) for pitch messages |
| `COPILOT_TG_CHAT_ID` | your numeric Telegram chat id (sender security gate + fallback for both streams) |
| `COPILOT_TG_CHAT_ID_INTRADAY` | optional: chat for the 15-min trading stream (pitches + evidence alerts) |
| `COPILOT_TG_CHAT_ID_DAILY` | optional: chat for the daily digest (day summary + opportunities) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | SMTP account for the daily digest |
| `DIGEST_TO` | digest recipient address |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | local LLM for pitch texts (existing assistant settings) |
| `EDGAR_USER_AGENT` | `"name (email)"` contact the SEC requires; enables the 13F + Form 4 insider collectors |

## Honesty guardrails
Factor screens are well-studied but do not reliably beat the market. Free data (yfinance) is
unofficial and incomplete outside the US. LLM theses are context-bounded interpretation, never
price forecasts. Every surface carries the disclaimer.
