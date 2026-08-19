#!/usr/bin/env bash
# The market-wide news sweep (v16, 2026-08-19), every minute around the clock.
#
# Around the clock on purpose: approvals, merger agreements and trial readouts are published
# outside market hours far more often than inside them, and the wire is where we learn it
# first. The sweep's cursor makes a missed run harmless — the next one catches up.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

exec timeout "${EQUITY_SCOUT_NEWS_TIMEOUT:-50s}" "$PY" scripts/run_news_sweep.py
