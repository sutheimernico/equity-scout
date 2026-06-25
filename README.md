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

# Refresh the combined universe snapshot (S&P 500 + curated global CSV)
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

## Honesty guardrails
Factor screens are well-studied but do not reliably beat the market. Free data (yfinance) is
unofficial and incomplete outside the US. LLM theses are context-bounded interpretation, never
price forecasts. Every surface carries the disclaimer.
