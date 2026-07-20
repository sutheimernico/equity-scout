#!/usr/bin/env bash
# v10.1: single arbitration point for ALL nightly-chain triggers (cron, systemd timer,
# Windows Task Scheduler) — the always-on layer that keeps the Auto-Depot advancing even
# when the box slept through the 02:30 slot. Per-day marker + flock, same contract as
# run_daily_guarded.sh, with one deliberate difference: NO weekend skip. The Saturday
# slot books Friday's close — a Sunday WSL start after a missed Saturday must catch it
# up (the depot advance is idempotent per panel date, so a redundant run books nothing).
# Triggers pass their name as $1 for the log line.
# Test seams: EQUITY_SCOUT_NIGHTLY_CHAIN overrides the chain command,
# EQUITY_SCOUT_NIGHTLY_STATE overrides the state dir, EQUITY_SCOUT_NIGHTLY_LOG the log.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${EQUITY_SCOUT_NIGHTLY_LOG:-$REPO_DIR/train.log}"
STATE_DIR="${EQUITY_SCOUT_NIGHTLY_STATE:-$REPO_DIR/.state}"
MARKER="$STATE_DIR/nightly_last_run"
LOCK="$STATE_DIR/nightly.lock"
CHAIN="${EQUITY_SCOUT_NIGHTLY_CHAIN:-$REPO_DIR/scripts/nightly_train.sh}"
mkdir -p "$STATE_DIR"

exec 9>>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] nightly-guarded: another run holds the lock (held by: $(cat "$LOCK" 2>/dev/null || echo unknown)) — skipping (trigger: ${1:-unspecified})" >> "$LOG"
  exit 0
fi

# Lock acquired: record who holds it (separate truncating write — FD 9 stays the
# flock handle) so a stuck run is diagnosable from train.log alone.
printf '%s pid=%s trigger=%s\n' "$(date -Is)" "$$" "${1:-unspecified}" > "$LOCK"

TODAY="$(date +%F)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi

echo "[$(date -Is)] nightly-guarded: starting nightly chain (trigger: ${1:-unspecified})" >> "$LOG"
"$CHAIN"
rc=$?
echo "[$(date -Is)] nightly-guarded: chain finished (rc=$rc)" >> "$LOG"

# nightly_train.sh degrades internally per step and always exits 0; a non-zero rc means
# the chain itself never ran — leave the day unmarked so the next trigger retries.
if [ "$rc" -eq 0 ]; then
  echo "$TODAY" > "$MARKER"
else
  echo "[$(date -Is)] nightly-guarded: chain FAILED (rc=$rc) — day NOT marked, next trigger will retry" >> "$LOG"
fi
