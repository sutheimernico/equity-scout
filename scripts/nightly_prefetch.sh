#!/usr/bin/env bash
# Nightly universe prefetch: warms one segment of the quote cache so the weekly screen can
# rank the full universe from cache instead of dying on yfinance rate limits.
# Calls .venv/bin/python directly because cron's minimal PATH has no uv.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

exec "$REPO_DIR/.venv/bin/python" scripts/run_prefetch.py \
  --universe data/universe_combined.csv \
  --db equity_scout.db
