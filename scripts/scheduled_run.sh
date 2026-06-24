#!/usr/bin/env bash
# Scheduled equity-scout run: full yfinance run over the combined universe with budget-capped LLM
# theses, writing a snapshot to the production DB. Local & free; intended for cron / systemd timer.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

exec uv run python scripts/run_scout.py \
  --provider yfinance \
  --universe data/universe_combined.csv \
  --db equity_scout.db \
  --use-llm --llm-top-n 3 \
  --max-workers 6
