# equity-scout

Local, free global stock funnel. Quant factor screen over a global universe → risk buckets →
LLM thesis for the finalists → dashboard. **Research assistant — not investment advice, no edge promise.**

See `docs/superpowers/specs/2026-06-24-equity-scout-design.md` (design) and
`docs/superpowers/plans/2026-06-24-vertical-slice-v1.md` (v1 plan).

## Quickstart (after `uv sync`)

```bash
# Offline deterministic run (fake provider)
uv run python scripts/run_scout.py --provider fake --db equity_scout.db

# Live run over the v1 universe (yfinance, free)
uv run python scripts/run_scout.py --provider yfinance --universe data/universe_v1.csv --db equity_scout.db

# Serve the dashboard
uv run python scripts/run_api.py --db equity_scout.db   # http://127.0.0.1:8000
```

## Honesty guardrails
Factor screens are well-studied but do not reliably beat the market. Free data (yfinance) is
unofficial and incomplete outside the US. LLM theses are context-bounded interpretation, never
price forecasts. Every surface carries the disclaimer.
