#!/usr/bin/env bash
# Keeps the session lane's minute cron alive through the US session (Nico 2026-08-06: "meine
# Vision ist, dass der halt die ganze Zeit läuft").
#
# Called every 10 minutes by the Windows task `equity-scout-session`, whose only real jobs are
# to WAKE the machine before the opening bell and to start WSL if it is down — the minute cron
# inside WSL cannot fire while WSL is not running, and no local schedule can fix that from the
# inside. This script is what that task runs.
#
# It also SELF-HEALS the one failure the task cannot: WSL up but cron dead. Then the lane would
# silently stop while everything looks fine, which is the failure class that already cost this
# project two days in July. One direct run per keepalive tick is a 10-minute cadence instead of
# one minute — degraded, but not dead, and it says so in the log.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
LOG="$REPO_DIR/keepalive.log"

stamp() { date -Is; }

if pgrep -x cron >/dev/null 2>&1; then
  # Healthy: the minute cron owns the lane, nothing to do. Logged once per tick so a silent
  # session.log can be told apart from a machine that was simply asleep.
  echo "[$(stamp)] ok — cron laeuft, Minuten-Takt aktiv" >> "$LOG"
  exit 0
fi

echo "[$(stamp)] WARN cron laeuft NICHT — Session-Lane einmal direkt angestossen (10-Min-Notbetrieb)" \
  >> "$LOG"
flock -n /tmp/equity-scout-session.lock "$REPO_DIR/scripts/session_lane.sh" \
  >> "$REPO_DIR/session.log" 2>&1
