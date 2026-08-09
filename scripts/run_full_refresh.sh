#!/usr/bin/env bash
# Cockpit "Alles neu laden" (2026-08-09): the three scheduler chains in dependency
# order — full scout first (it refreshes the run snapshot the watchlist ranks from), then
# the daily chain, then the nightly training/depot advance.
#
# This wrapper adds no arbitration beyond its own lock: each phase is an existing guarded
# wrapper that keeps its own flock and marker. EQUITY_SCOUT_FORCE reaches them by env
# inheritance — the cockpit always sets it for this button, because an unforced full
# refresh would silently skip whichever phase already ran today and the button would
# look broken.
#
# Every phase is a step() so the cockpit can read the phase from this one log; the
# per-phase detail stays in scout_full.log / copilot.log / train.log.
# Test seams: EQUITY_SCOUT_FULL_LOG, EQUITY_SCOUT_FULL_STATE.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${EQUITY_SCOUT_FULL_LOG:-$REPO_DIR/full_refresh.log}"
STATE_DIR="${EQUITY_SCOUT_FULL_STATE:-$REPO_DIR/.state}"
LOCK="$STATE_DIR/full_refresh.lock"
TRIGGER="${1:-unspecified}"
mkdir -p "$STATE_DIR"

exec 9>>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] full_refresh: another full refresh holds the lock (held by: $(cat "$LOCK" 2>/dev/null || echo unknown)) — skipping (trigger: $TRIGGER)" >> "$LOG"
  exit 0
fi
printf '%s pid=%s trigger=%s\n' "$(date -Is)" "$$" "$TRIGGER" > "$LOCK"

# Same contract as daily_copilot.sh: a failing phase is logged and the chain continues,
# so one rate-limited scout cannot cost the daily and nightly refresh behind it.
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

echo "[$(date -Is)] ===== full_refresh start ===== (trigger: $TRIGGER)" >> "$LOG"
step scout   "$REPO_DIR/scripts/run_weekly_guarded.sh"  "$TRIGGER"
step daily   "$REPO_DIR/scripts/run_daily_guarded.sh"   "$TRIGGER"
step nightly "$REPO_DIR/scripts/run_nightly_guarded.sh" "$TRIGGER"
echo "[$(date -Is)] ===== full_refresh end =====" >> "$LOG"
