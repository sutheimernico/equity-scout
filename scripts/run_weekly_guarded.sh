#!/usr/bin/env bash
# Single arbitration point for ALL weekly full-scout triggers (cron, systemd timer,
# manual). Same contract as run_nightly_guarded.sh, keyed on the ISO week instead of
# the day: the full-universe screen (scheduled_run.sh) refreshes the run snapshot the
# watchlist ranks from, and 2026-08-06 showed what happens without a scheduler — the
# last run silently aged three weeks while every downstream chain kept polishing it.
# Per-week marker + flock; a redundant trigger (cron AND a Persistent systemd catch-up
# in one week) runs the screen once. Triggers pass their name as $1 for the log line.
# Test seams: EQUITY_SCOUT_WEEKLY_CHAIN overrides the chain command,
# EQUITY_SCOUT_WEEKLY_STATE the state dir, EQUITY_SCOUT_WEEKLY_LOG the log.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${EQUITY_SCOUT_WEEKLY_LOG:-$REPO_DIR/scout_full.log}"
STATE_DIR="${EQUITY_SCOUT_WEEKLY_STATE:-$REPO_DIR/.state}"
MARKER="$STATE_DIR/weekly_last_run"
LOCK="$STATE_DIR/weekly.lock"
CHAIN="${EQUITY_SCOUT_WEEKLY_CHAIN:-$REPO_DIR/scripts/scheduled_run.sh}"
# Cockpit "Trotzdem starten" (2026-08-09): marker bypass only, never the flock.
FORCE="${EQUITY_SCOUT_FORCE:-0}"
mkdir -p "$STATE_DIR"

exec 9>>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] weekly-guarded: another run holds the lock (held by: $(cat "$LOCK" 2>/dev/null || echo unknown)) — skipping (trigger: ${1:-unspecified})" >> "$LOG"
  exit 0
fi

# Lock acquired: record who holds it (separate truncating write — FD 9 stays the
# flock handle) so a stuck multi-hour screen is diagnosable, not just detectable.
printf '%s pid=%s trigger=%s\n' "$(date -Is)" "$$" "${1:-unspecified}" > "$LOCK"

# ISO year-week (%G-W%V): the pair is what makes the year boundary safe — week 01
# belongs to the ISO year that owns it, so late-December/early-January triggers can
# never alias onto the same marker value.
THIS_WEEK="$(date +%G-W%V)"
if [ "$FORCE" = "1" ]; then
  echo "[$(date -Is)] weekly-guarded: FORCED run (trigger: ${1:-unspecified}) — marker bypassed" >> "$LOG"
elif [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$THIS_WEEK" ]; then
  exit 0  # already ran this week — quiet skip; redundant triggers are by design
fi

echo "[$(date -Is)] weekly-guarded: starting full scout (trigger: ${1:-unspecified})" >> "$LOG"
"$CHAIN" >> "$LOG" 2>&1
rc=$?
echo "[$(date -Is)] weekly-guarded: full scout finished (rc=$rc)" >> "$LOG"

# scheduled_run.sh is set -e and CAN fail (rate limits, network) — the week must not
# be marked done then, so the remaining weekly triggers retry.
if [ "$rc" -eq 0 ]; then
  echo "$THIS_WEEK" > "$MARKER"
else
  echo "[$(date -Is)] weekly-guarded: full scout FAILED (rc=$rc) — week NOT marked, next trigger will retry" >> "$LOG"
fi
