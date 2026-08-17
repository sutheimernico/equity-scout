#!/usr/bin/env bash
# One night, three steps, in the only order that works: news must be on disk BEFORE the matrix
# runs, because `after_news` is one of the matrix's conditions. Each step is skipped when its
# output already exists, so re-running the chain continues instead of restarting.
#
# Deliberately CELLS-ONLY: the report phase (pooling, plateaus, opening the hold-out) does NOT
# run tonight. The pooled t-statistic still assumes ticker independence (2026-08-18 review
# finding) — opening the hold-out before that is hardened would spend it on inflated numbers.
# Tomorrow: harden pooling, then run `--phase report` once, deliberately.
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
echo "[$(date -Is)] ===== Nachtkette Start (cells-only, Hold-out bleibt zu) =====" >> "$LOG"
# 1. wait for the bar download that is already running. The pattern matches the PYTHON process
# (".py" suffix): a plain `pgrep -f fetch_minute_history` once matched a helper shell that
# carried the string in its own command line and deadlocked the whole night (2026-08-17).
while pgrep -f "fetch_minute_history\.py" >/dev/null 2>&1; do sleep 60; done
echo "[$(date -Is)] Bars fertig: $(ls data/minutes | wc -l) Ticker-Jahre" >> "$LOG"
step news_fetch      uv run python scripts/run_news_latency.py --phase fetch
step signal_matrix   uv run python scripts/run_signal_matrix.py --pairs --phase cells
step news_latency    uv run python scripts/run_news_latency.py --phase measure
echo "[$(date -Is)] ===== Nachtkette Ende =====" >> "$LOG"
