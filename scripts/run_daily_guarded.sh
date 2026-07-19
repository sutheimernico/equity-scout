#!/usr/bin/env bash
# v9: single arbitration point for ALL daily-chain triggers (cron, systemd timer,
# Windows Task Scheduler). Weekday guard + per-day marker + flock — a caught-up or
# duplicate slot can never run the chain twice on one day. Triggers pass their name
# as $1 for the log line. EQUITY_SCOUT_CHAIN overrides the chain command (tests).
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO_DIR/copilot.log"
STATE_DIR="$REPO_DIR/.state"
MARKER="$STATE_DIR/daily_last_run"
LOCK="$STATE_DIR/daily.lock"
CHAIN="${EQUITY_SCOUT_CHAIN:-$REPO_DIR/scripts/daily_copilot.sh}"
mkdir -p "$STATE_DIR"

# Weekdays only: a Saturday WSL start must not catch up Friday's missed slot.
if [ "$(date +%u)" -gt 5 ]; then
  exit 0
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] guarded: another daily run holds the lock — skipping (trigger: ${1:-unspecified})" >> "$LOG"
  exit 0
fi

TODAY="$(date +%F)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi

echo "[$(date -Is)] guarded: starting daily chain (trigger: ${1:-unspecified})" >> "$LOG"
"$CHAIN"
echo "$TODAY" > "$MARKER"
