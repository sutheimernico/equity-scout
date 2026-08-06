#!/usr/bin/env bash
# One-shot precondition runner for the session-lane Alpaca rewrite.
#
# The freshness half of scripts/verify_alpaca_paper.py can only be measured while the US
# market is open, which is awkward to hit by hand. This wrapper is driven by cron every
# weekday inside the session and STOPS ITSELF once a run has passed: the marker file makes
# every later trigger a silent no-op, so the order probes are placed once, not daily.
#
# Exit codes from the Python script: 0 = all checked assumptions hold (marker written),
# 2 = not measurable yet — market closed, or the session is younger than the density window
# needs (no marker, try again next slot), 1 = a real failure (no marker — the run must be
# looked at, so it retries and stays visible in the log).
#
# Remove "$STATE_DIR/alpaca_verified" to arm it again.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO_DIR/alpaca_verify.log"
STATE_DIR="$REPO_DIR/.state"
MARKER="$STATE_DIR/alpaca_verified"
LOCK="$STATE_DIR/alpaca_verify.lock"
mkdir -p "$STATE_DIR"

[ -f "$MARKER" ] && exit 0  # already verified — quiet by design

exec 9>>"$LOCK"
flock -n 9 || exit 0  # a previous slot is still running

cd "$REPO_DIR" || exit 1
# Same convention as the other chains: no python-dotenv in this repo, the shell sources
# .env. Without this the script reports missing keys even though they are on disk.
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Captured rather than streamed straight to the log: the Telegram message quotes the actual
# measurement, so it has to be held rather than only appended.
OUTPUT="$(.venv/bin/python scripts/verify_alpaca_paper.py --require-open --place-orders 2>&1)"
STATUS=$?

{
  echo "===== verify_alpaca start $(date -Is) (trigger: ${1:-cron}) ====="
  printf '%s\n' "$OUTPUT"
} >> "$LOG" 2>&1

# A closed-market skip stays silent on purpose: it happens on most slots and a notification
# per skip would train Nico to ignore the one message that matters.
case "$STATUS" in
  0)
    date -Is > "$MARKER"
    echo "===== PASS — marker written, this job disarms itself =====" >> "$LOG"
    printf '%s' "$OUTPUT" | .venv/bin/python scripts/notify_alpaca_verify.py \
      --status pass >> "$LOG" 2>&1
    ;;
  2)
    echo "===== not measurable yet, retrying next slot =====" >> "$LOG"
    ;;
  *)
    echo "===== FAILED (exit $STATUS) — no marker, will retry =====" >> "$LOG"
    printf '%s' "$OUTPUT" | .venv/bin/python scripts/notify_alpaca_verify.py \
      --status fail >> "$LOG" 2>&1
    ;;
esac
