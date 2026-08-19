#!/usr/bin/env bash
# The catalyst radar's minute cadence (v16, 2026-08-19): ignition scan -> ignition lane.
#
# One script for both because they are strictly sequential — the lane can only act on
# signals the scan has already written, and running them from two cron lines would race on
# the same minute. The news sweep is deliberately NOT here: it runs around the clock on its
# own cadence, while these two only make sense inside the market window (their own guards
# return silently outside it, so the extra firings cost nothing).
#
# Ordering note: the scan writes and alerts even if the lane then declines every signal.
# Seeing must never depend on our willingness to trade.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

# No python-dotenv in this repo — the shell sources .env, same as every other chain here.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Wall-clock cap under a 1-minute cadence: a hang must cost one slot, not the session.
# 50s leaves the next firing a clean slot; the scan itself measured ~3 s over 4 calls.
timeout "${EQUITY_SCOUT_SCAN_TIMEOUT:-50s}" "$PY" scripts/run_catalyst_scan.py
timeout "${EQUITY_SCOUT_IGNITION_TIMEOUT:-50s}" "$PY" scripts/run_ignition_lane.py
