#!/usr/bin/env bash
# Nightly model training + research batch (plan v6 P5): after US close, retrain every
# entry-model preset for every family (long "entry", short "entry_short", triple-barrier
# "entry_tb") — the hardened registry gate alone decides champion promotions, per family —
# then run a bounded research-loop batch (own DSR-hurdle ledger), then advance the forward
# paper accounts so the ML bots trade on the freshest champions. A daily learning-curve
# snapshot (Strang C, task C1) is written right after training, so the champion's n_train and
# the rolling live hit-rate/Rank-IC are captured freshest — one persisted point per calendar
# day, visible in the dashboard even on nights the champion does not flip.
#
# The Auto-Depot (vision v10) advances LAST, after forward_paper has refreshed the price
# snapshots and rolled every sleeve to the fresh close: the meta-allocator reads the sleeves'
# forward valuations, and running here (post-US-close) keeps its fills on real closing prices
# — an 18:00 Berlin slot would trade an intraday stand. The daily digest only READS its DB.
#
# Same contract as daily_copilot.sh: steps degrade independently, .venv python (cron has no
# uv), .env sourced when present, everything appends to train.log.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PY="$REPO_DIR/.venv/bin/python"
LOG="$REPO_DIR/train.log"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

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

echo "[$(date -Is)] ===== nightly_train start =====" >> "$LOG"
step train_entry       "$PY" scripts/run_train_entry.py
step learning_snapshot "$PY" scripts/run_learning_snapshot.py
step research_batch    "$PY" scripts/run_research.py --trials 25
step forward_paper     "$PY" scripts/run_forward_paper.py --refresh
step autotrader        "$PY" scripts/run_autotrader.py
step st_swing          "$PY" scripts/run_shortterm.py --lane swing
# session lane overnight sweep: outside the market window this flattens anything the
# settled-bar delay let slip past the in-session force-flat (never holds overnight)
step st_session_sweep  "$PY" scripts/run_shortterm.py --lane session
echo "[$(date -Is)] ===== nightly_train end =====" >> "$LOG"
