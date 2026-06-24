# equity-scout

Local, free global stock funnel. Quant factor screen over a global universe → risk buckets →
LLM thesis for the finalists → dashboard. **Research assistant — not investment advice, no edge promise.**

See `docs/superpowers/specs/2026-06-24-equity-scout-design.md` (design) and
`docs/superpowers/plans/2026-06-24-vertical-slice-v1.md` (v1 plan).

## Quickstart (after `uv sync`)

```bash
# Offline deterministic run (fake provider)
uv run python scripts/run_scout.py --provider fake --db equity_scout.db

# Refresh the combined universe snapshot (S&P 500 + curated global CSV)
uv run python scripts/refresh_universe.py

# Live run over the combined universe (yfinance, free; cached)
uv run python scripts/run_scout.py --provider yfinance --universe data/universe_combined.csv --db equity_scout.db

# Advance the paper portfolio against the latest picks (demo money, buy-and-hold; PAPER ONLY)
uv run python scripts/run_paper.py --db equity_scout.db --bucket balanced --threshold 0.70

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
