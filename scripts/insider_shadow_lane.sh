#!/usr/bin/env bash
# The insider-cluster SHADOW lane (v15 P2), once per weekday evening AFTER the daily
# chain has collected fresh Form 4 filings (scripts/daily_copilot.sh, 18:00).
#
# Why it is its OWN script and cron line rather than a step in daily_copilot.sh:
# - Ownership. A parallel session owns the intraday/session chain; this lane must be
#   addable and removable without touching a shared chain script.
# - Blast radius. The lane only ever INSERTs ledger rows; it must never be able to delay
#   or fail the pitch delivery, and a broken pitch step must never skip the lane.
# - Cadence. Filings arrive daily, resolution runs in the daily chain anyway — one run
#   per weekday is the whole requirement.
#
# The lane is idempotent (UNIQUE ledger key + one-open-prediction-per-ticker skip), so a
# missed evening costs nothing: the next run registers the same cluster.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

# No python-dotenv in this repo — the shell sources .env, same as every other chain here.
# Without EDGAR_USER_AGENT the lane reports `unconfigured` instead of "no clusters".
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

exec "$PY" scripts/run_insider_shadow.py
