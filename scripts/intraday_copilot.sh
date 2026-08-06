#!/usr/bin/env bash
# 15-minute intraday copilot: radar entry-zone check + FAST evidence collectors
# (congress mirror, news themes, voices) + pitches/evidence alerts. INBOX-ONLY since
# the 2026-07-14 revision: Nico wants only the daily summary on his phone — the
# intraday timeline accumulates in the dashboard inbox; Telegram sending happens
# once a day in daily_copilot.sh (pitches with decision buttons + digest).
#
# Design rules (same contract as daily_copilot.sh):
# - Runs ONLY inside the approximate US market window (market_hours.py guard);
#   outside it the script exits 0 quietly — cron fires it blindly every 30 min.
# - SLOW/impolite-if-hammered sources stay in the daily/nightly chains: 13F + Form 4
#   (EDGAR etiquette, filings do not change intraday) and all model training.
# - Every step degrades independently; existing cooldowns/idempotency keys prevent
#   alert spam — running twice adds nothing.
# - yfinance prices are ~15 minutes delayed; the pitch text says so.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PY="$REPO_DIR/.venv/bin/python"
LOG="$REPO_DIR/intraday.log"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if ! "$PY" - << 'EOF'
import sys
from datetime import datetime, timezone
from equity_scout.market_hours import within_market_window

sys.exit(0 if within_market_window(datetime.now(timezone.utc)) else 3)
EOF
then
  exit 0  # outside the market window — nothing to do, not an error
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

echo "[$(date -Is)] ===== intraday_copilot start =====" >> "$LOG"
step radar    "$PY" scripts/run_radar.py
step evidence "$PY" scripts/run_evidence.py --fast
step notify   "$PY" scripts/run_notify.py --inbox-only
# The session lane LEFT this chain on 2026-08-06: it trades 1-minute bars and now runs from
# its own per-minute cron (scripts/session_lane.sh, own lock, own log). Running it here would
# have thrown away 14 of every 15 minutes of the latency the Alpaca rewrite bought, and a slow
# radar fetch would have delayed an entry.
echo "[$(date -Is)] ===== intraday_copilot end =====" >> "$LOG"
