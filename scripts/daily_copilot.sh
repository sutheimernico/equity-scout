#!/usr/bin/env bash
# Daily copilot chain: (Mondays: screener first) -> radar -> evidence -> notify ->
# score watchlist -> resolve predictions -> resolve evidence -> lanes -> digest.
#
# Design rules:
# - Every step degrades independently: a failed step is logged and the chain
#   CONTINUES — one dead source/API must never silence the pitches or the ledger.
# - Uses .venv/bin/python directly (NOT `uv run`): cron's minimal PATH has no uv,
#   and the long-running forward-paper cron line already proves this pattern.
# - .env is sourced when present (Telegram/EDGAR/SMTP config); without it every
#   consumer degrades politely (inbox-only pitches, unconfigured 13F, stdout digest).
# - All output appends to copilot.log next to the repo (see docs/scheduling.md).
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PY="$REPO_DIR/.venv/bin/python"
LOG="$REPO_DIR/copilot.log"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

step() {
  local name="$1"
  shift
  echo "[$(date -Is)] START ${name}" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then
    echo "[$(date -Is)] OK ${name}" >> "$LOG"
  else
    local rc=$?
    echo "[$(date -Is)] FAILED ${name} (exit ${rc}) — continuing" >> "$LOG"
  fi
}

echo "[$(date -Is)] ===== daily_copilot start =====" >> "$LOG"

# Mondays: refresh the screener BEFORE the daily chain so the radar sees fresh
# finalists, and re-measure person track records (45/135d disclosure lag — weekly
# is plenty; needs one yfinance panel download).
if [ "$(date +%u)" = "1" ]; then
  step scout ./scripts/scheduled_run.sh
  step person_scores "$PY" scripts/run_person_scores.py
fi

step radar               "$PY" scripts/run_radar.py
step evidence            "$PY" scripts/run_evidence.py
# --min-pitches 5: the daily delivery pitches several names (topped up by composite),
# not only strict in-zone hits (Nico 2026-07-15).
step notify              "$PY" scripts/run_notify.py --min-pitches 5
step score_watchlist     "$PY" scripts/run_score_watchlist.py
step resolve_predictions "$PY" scripts/run_resolve_predictions.py
step resolve_evidence    "$PY" scripts/run_resolve_evidence.py
step lanes               "$PY" scripts/run_lanes.py
step digest              "$PY" scripts/run_digest.py

echo "[$(date -Is)] ===== daily_copilot end =====" >> "$LOG"
