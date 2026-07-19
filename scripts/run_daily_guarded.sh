#!/usr/bin/env bash
# v9: single arbitration point for ALL daily-chain triggers (cron, systemd timer,
# Windows Task Scheduler). Weekday guard + per-day marker + flock — a caught-up or
# duplicate slot can never run the chain twice on one day. Triggers pass their name
# as $1 for the log line. EQUITY_SCOUT_CHAIN overrides the chain command (tests).
# A hung chain process holds the flock indefinitely, so later same-day triggers
# skip by design — the holder records its acquire time/PID/trigger in the lock
# file (appended fd, separate truncating write) so a stuck run is identifiable
# from copilot.log alone.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO_DIR/copilot.log"
STATE_DIR="$REPO_DIR/.state"
MARKER="$STATE_DIR/daily_last_run"
LOCK="$STATE_DIR/daily.lock"
CHAIN="${EQUITY_SCOUT_CHAIN:-$REPO_DIR/scripts/daily_copilot.sh}"
mkdir -p "$STATE_DIR"

# Weekdays only: a Saturday WSL start must not catch up Friday's missed slot.
# A persistent systemd catch-up firing on a weekend (e.g. WSL start on Saturday
# after a missed Friday) still stamps systemd's own timestamp file, permanently
# consuming that Friday catch-up — that's intended (weekends are never made up),
# but it must be diagnosable from copilot.log instead of vanishing silently.
if [ "$(date +%u)" -gt 5 ]; then
  echo "[$(date -Is)] guarded: weekend trigger (${1:-unspecified}) — skipped by design, missed weekday slots are not made up on weekends" >> "$LOG"
  exit 0
fi

exec 9>>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] guarded: another daily run holds the lock (held by: $(cat "$LOCK" 2>/dev/null || echo unknown)) — skipping (trigger: ${1:-unspecified})" >> "$LOG"
  exit 0
fi

# Lock acquired: record who holds it (separate truncating write — FD 9 stays the
# flock handle and is unaffected) so a stuck run is diagnosable, not just detectable.
printf '%s pid=%s trigger=%s\n' "$(date -Is)" "$$" "${1:-unspecified}" > "$LOCK"

TODAY="$(date +%F)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi

echo "[$(date -Is)] guarded: starting daily chain (trigger: ${1:-unspecified})" >> "$LOG"
"$CHAIN"
rc=$?
echo "[$(date -Is)] guarded: chain finished (rc=$rc)" >> "$LOG"

# daily_copilot.sh degrades internally per step and always exits 0; a non-zero rc
# here means the chain itself never got to run (exec error etc.) — the day must
# not be marked done so the remaining daily triggers can retry.
if [ "$rc" -eq 0 ]; then
  echo "$TODAY" > "$MARKER"
else
  echo "[$(date -Is)] guarded: chain FAILED (rc=$rc) — day NOT marked, next trigger will retry" >> "$LOG"
fi
