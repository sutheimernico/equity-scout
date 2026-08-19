#!/usr/bin/env bash
# v9: single arbitration point for ALL daily-chain triggers (cron, systemd timer,
# Windows Task Scheduler). Weekday guard + per-day marker + flock — a caught-up or
# duplicate slot can never run the chain twice on one day. Triggers pass their name
# as $1 for the log line. EQUITY_SCOUT_CHAIN overrides the chain command (tests).
# A hung chain process holds the flock indefinitely, so later same-day triggers
# skip by design — the holder records its acquire time/PID/trigger in the lock
# file (appended fd, separate truncating write) so a stuck run is identifiable
# from copilot.log alone.
# EQUITY_SCOUT_FORCE=1 is the cockpit's explicit "start it anyway" (2026-08-09).
# Test seams: EQUITY_SCOUT_DAILY_STATE overrides the state dir, EQUITY_SCOUT_DAILY_LOG
# the log.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${EQUITY_SCOUT_DAILY_LOG:-$REPO_DIR/copilot.log}"
STATE_DIR="${EQUITY_SCOUT_DAILY_STATE:-$REPO_DIR/.state}"
MARKER="$STATE_DIR/daily_last_run"
LOCK="$STATE_DIR/daily.lock"
CHAIN="${EQUITY_SCOUT_CHAIN:-$REPO_DIR/scripts/daily_copilot.sh}"
# Heavy steps run under a memory ceiling (scripts/mem_guard.sh): on 2026-08-19 a single
# matrix python3 hit 10.1 GiB in a 15.8 GiB VM and the kernel OOM-killer took the whole
# box down with it. A missing guard must never block the run, so the prefix collapses away.
MEM_GUARD="$REPO_DIR/scripts/mem_guard.sh"
[ -x "$MEM_GUARD" ] || MEM_GUARD=""
# The cockpit "Trotzdem starten" tap (2026-08-09): skips the marker and the weekend
# guard, never the flock — those two are policy, the lock is data integrity.
FORCE="${EQUITY_SCOUT_FORCE:-0}"
mkdir -p "$STATE_DIR"

# Weekdays only: a Saturday WSL start must not catch up Friday's missed slot.
# A persistent systemd catch-up firing on a weekend (e.g. WSL start on Saturday
# after a missed Friday) still stamps systemd's own timestamp file, permanently
# consuming that Friday catch-up — that's intended (weekends are never made up),
# but it must be diagnosable from copilot.log instead of vanishing silently.
if [ "$FORCE" != "1" ] && [ "$(date +%u)" -gt 5 ]; then
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
if [ "$FORCE" = "1" ]; then
  echo "[$(date -Is)] guarded: FORCED run (trigger: ${1:-unspecified}) — marker and weekend guard bypassed" >> "$LOG"
elif [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi

echo "[$(date -Is)] guarded: starting daily chain (trigger: ${1:-unspecified})" >> "$LOG"
${MEM_GUARD:+"$MEM_GUARD"} "$CHAIN"
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

# Propagate the chain's result (2026-08-09) — see run_weekly_guarded.sh for why: a skip
# still exits 0 above, only a chain that actually ran reports its own rc, and
# run_full_refresh.sh turns that into an honest FAILED phase in the cockpit.
exit "$rc"
