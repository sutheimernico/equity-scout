# Trading Copilot — Design Spec

**Date:** 2026-07-04
**Status:** approved in dialogue (Nico, 2026-07-04); blanket go for autonomous implementation as long as no monetary cost is incurred
**Builds on:** equity-scout (funnel, dashboard, ML research loop, forward paper tracking), signal-trader-demo (Alpaca integration, honest-harness practices), tap-approve (Telegram inline-button approval pattern)

## 1. Vision

equity-scout evolves from a research funnel into a personal trading copilot:

1. It continuously watches a vetted universe of stocks and detects **good entry
   prices** for fundamentally strong names.
2. It notifies Nico **only when an entry is genuinely attractive** — short pitch
   on the phone, one-tap decision.
3. Two paper portfolios run side by side: **Lane A ("Nico")** trades only what
   Nico approves; **Lane B ("Autopilot")** trades the same signals autonomously.
4. A continuously retrained ML model scores entries; its quality is **provable**
   (prediction ledger, walk-forward evaluation), not claimed.
5. A completely redesigned dashboard presents all of it as a public showpiece.

The wow factor is engineering discipline: a system that demonstrably runs
unattended, measures itself honestly, and looks the part. No alpha claims.
Framing stays "research assistant, not advice".

## 2. Goals

- Tiered market radar (daily / hourly / real-time) with per-stock entry levels.
- Explainable composite entry signal (three transparent sub-signals + ML layer).
- Online-learning MLOps loop: nightly walk-forward retraining, champion/challenger
  promotion, model registry, drift monitoring, immutable prediction ledger.
- Notification + decision inbox: Telegram (primary, one-tap), dashboard inbox,
  daily e-mail digest.
- Two-lane paper execution with fair, like-for-like comparison vs. a market
  benchmark ("Nico vs. Autopilot vs. Market").
- Dashboard redesign: distinctive trading-terminal visual identity, screenshot-
  worthy for the portfolio site.
- Public proof of autonomy: scheduled GitHub Actions runs, visible history.

## 3. Non-goals

- Real-money trading (v1). Documented gate: earliest after 6 months of forward
  track record against pre-defined criteria, and then as Nico's manual decision.
  The bot never receives real-money credentials.
- Intraday day-trading / tick scalping, options, crypto.
- Paid data sources or paid infrastructure of any kind (hard constraint:
  free tiers only — yfinance, SEC EDGAR, Alpaca paper/IEX, local Ollama).

## 4. Architecture (hybrid runtime)

### 4.1 Tiered radar

| Tier | Cadence | Where | Scope |
|---|---|---|---|
| Deep scan | daily, after US close | GitHub Actions | full funnel → finalist watchlist + entry levels per stock |
| Watchlist check | hourly, US market hours | GitHub Actions | watchlist only: price vs. entry zone |
| Live watcher | streaming | local process | Alpaca IEX websocket, only tickers near their trigger |

The funnel narrows the universe so each tier is cheap: the closer a stock is to
its entry level, the closer the system looks.

### 4.2 Runtime split

- **GitHub Actions (public repo):** deep scan, watchlist checks, notification
  dispatch (Telegram sendMessage, e-mail digest), nightly ML retraining job,
  artifact commit-back (watchlist, signals, aggregated performance JSON).
  Secrets (Telegram token, Alpaca keys, SMTP) live in GitHub Secrets.
- **Local (laptop):** Telegram long-polling receiver for decision callbacks
  (tap-approve pattern), order execution for both lanes, live watcher,
  Ollama pitch generation. Local state in SQLite (gitignored).

If the laptop is off, notifications still go out (Actions-side); decisions
queue in Telegram until the local receiver polls. Missed real-time triggers
degrade gracefully to the hourly tier.

## 5. Entry signal & ML

### 5.1 Sub-signals (transparent, rule-based)

- **Dip-Quality** — meaningful pullback in a fundamentally strong stock without
  fundamental deterioration (funnel factors unchanged or improved).
- **Value-Gap** — price notably below fair-value estimate from valuation
  multiples relative to history and peers.
- **Momentum** — trend/breakout filter to avoid catching falling knives.

Each sub-signal produces a score and a human-readable reason string. Style
attribution is preserved end-to-end (signal → decision → trade → performance),
so reports always show which style earns the results.

### 5.2 ML layer

- Combines sub-signals + market context into an **Entry-Quality-Score (0–100)**.
- Target: probability that the stock beats the benchmark over the primary
  horizon (4 weeks; 12-week secondary) from this entry.
- **Honest online learning:** nightly walk-forward retraining; challenger
  replaces champion only on better out-of-sample performance; versioned model
  registry with metrics; drift monitoring on features and calibration.
- **Immutable prediction ledger:** every score is logged at prediction time and
  resolved against reality later. "The model improves" must be a queryable
  fact, not a claim. Reuses the existing overfitting-guarded research-loop
  discipline (research_ledger).

## 6. Notifications & decision inbox

- Notify only above a score threshold, with per-ticker cooldown (no spam).
- **Telegram (primary):** short pitch — what the company is, why now, score
  breakdown by style, key risks — with inline buttons **[Buy] [Pass] [Later]**.
  Pitch text generated by local Ollama from computed numbers; existing
  guardrail holds: the LLM interprets, never forecasts or ranks.
- **Dashboard inbox:** all pitches (open/decided) with full detail.
- **E-mail:** daily digest (SMTP via free provider; Needs-Nico input).
- Decision capture: local long-polling process (adapted from tap-approve).

## 7. Two-lane execution & forward tracking

- **Lane A "Nico":** orders only what Nico approved. **Lane B "Autopilot":**
  orders autonomously above the score threshold. Identical position-sizing and
  exit rules so the comparison is fair.
- Exits in v1 are deliberately simple and rule-based: target / stop / max
  holding period.
- Both lanes tracked in isolated SQLite ledgers against a benchmark ETF (SPY).
  Execution adapter abstracts the broker; default plan: Autopilot lane on
  Alpaca paper (the "demo account"), Nico lane on the internal simulated
  broker with the identical fill model (next-open + slippage). If Alpaca
  supports a second isolated paper account, both lanes go live on Alpaca —
  implementation decides, fairness of fills is the invariant.
- Dashboard shows equity curves (Nico vs. Autopilot vs. Market), hit rates,
  per-style attribution, and open positions.

## 8. Dashboard redesign

The current dashboard is functionally fine but visually boring. v2 becomes a
showpiece with a distinctive trading-terminal identity (dark, data-dense,
restrained motion; sibling aesthetic to the portfolio's "Kinetic Terminal"
language so Nico's personal brand stays coherent). Core surfaces:

1. **Radar** — watchlist with entry zones and live proximity.
2. **Inbox** — pitches and decisions.
3. **Arena** — Nico vs. Autopilot vs. Market (the headline view).
4. **Model** — registry, champion/challenger history, calibration, drift.

Public deployment shows aggregated/anonymized data only. Design quality gets
its own verification pass (visual review is Nico's call, per standing rule).

## 9. Data, privacy, security

- Public repo artifacts: watchlist, signals, aggregated performance JSON.
  Never: personal decisions, full ledgers, credentials.
- Local SQLite (gitignored): decisions, lane ledgers, prediction ledger copy.
- Repo hygiene fixed as part of this work: existing `*.log` / `*.db` files in
  the repo root get removed from tracking and gitignored (public-repo cleanup).
- Secrets only in GitHub Secrets / local `.env` (never read or printed).

## 10. Testing & honesty gates

- Gate stays `pytest` green + `ruff` clean; all new logic ships with tests
  (signals against fixtures, lanes against a mock broker, notification
  formatting, ledger invariants).
- Honesty rules inherited from signal-trader-demo: transaction costs and
  slippage in every backtest, survivorship-bias handling, no fabricated
  metrics ever; prediction ledger is append-only.

## 11. Needs Nico (cannot be done autonomously)

- Telegram bot token + chat_id from @BotFather (also unblocks tap-approve).
- SMTP credentials for the e-mail digest (free provider of Nico's choice).
- GitHub Secrets entry for the above + Alpaca paper keys.
- Visual sign-off on the dashboard redesign.

## 12. Open decisions deferred to the implementation plan

- Exact entry-zone derivation per stock (rule family + parameters).
- Alpaca second-paper-account feasibility (see §7).
- E-mail digest provider.
- Whether the hourly tier reuses the deep-scan artifact or recomputes deltas.
