#!/usr/bin/env bash
# One night, four steps, in the only order that works: news must be on disk BEFORE the matrix
# runs, because `after_news` is one of the matrix's conditions. Each step is skipped when its
# output already exists, so re-running the chain continues instead of restarting.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
if [ -f .env ]; then set -a; . ./.env; set +a; fi
LOG="night_matrix.log"
step() {
  echo "[$(date -Is)] START $1" >> "$LOG"
  shift
  if "$@" >> "$LOG" 2>&1; then echo "[$(date -Is)] OK" >> "$LOG"
  else echo "[$(date -Is)] FAILED (exit $?) — weiter mit dem nächsten Schritt" >> "$LOG"; fi
}
echo "[$(date -Is)] ===== Nachtkette Start =====" >> "$LOG"
# 1. wait for the bar download that is already running
while pgrep -f fetch_minute_history >/dev/null 2>&1; do sleep 60; done
echo "[$(date -Is)] Bars fertig: $(ls data/minutes | wc -l) Ticker-Jahre" >> "$LOG"
step news_fetch      uv run python scripts/run_news_latency.py --phase fetch
step signal_matrix   uv run python scripts/run_signal_matrix.py --pairs
step news_latency    uv run python scripts/run_news_latency.py --phase measure
echo "[$(date -Is)] ===== Nachtkette Ende =====" >> "$LOG"
