#!/usr/bin/env bash
# Driver for P2a history resolution runs (Task 7+; rerunnable for future refreshes).
# Loops run_history_resolve until a full pass writes nothing and nothing failed,
# then refreshes the report. Log: history_resolve.log (repo root, gitignored).
set -u
cd "$(dirname "$0")/.."
LOG=history_resolve.log
echo "=== drive_history_resolve start $(date -Is) ===" >> "$LOG"
for i in $(seq 1 30); do
  echo "--- pass $i $(date -Is) ---" >> "$LOG"
  out=$(uv run python scripts/run_history_resolve.py --apply --max-missing-share 1.0 --max-rechecks 50 2>&1)
  echo "$out" >> "$LOG"
  # Converged: nothing written/refused AND no failed fetches left to retry.
  if echo "$out" | grep -q "geschrieben: 0, abgelehnt: 0" \
     && echo "$out" | grep -q "Fetch fehlgeschlagen: 0"; then
    echo "=== converged after pass $i $(date -Is) ===" >> "$LOG"
    break
  fi
  sleep 30
done
uv run python scripts/run_history_report.py >> "$LOG" 2>&1
echo "=== driver done $(date -Is) ===" >> "$LOG"
