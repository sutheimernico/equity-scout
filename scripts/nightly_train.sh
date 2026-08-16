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
# The Auto-Depot (vision v10) advances LAST, after forward_paper AND the arena lanes
# (st_swing, st_session_sweep) have booked today's valuations: for promoted ARENA_<lane>
# sleeves the meta-allocator reads each lane's shortterm.db equity series as its price
# series (run_autotrader.py), so the lane step must run before the depot step within the
# SAME chain run — otherwise the depot's window still ends on yesterday's last lane mark
# at both ends and books a 0% move, permanently losing that day's real P&L. Running here
# (post-US-close) also keeps fills on real closing prices — an 18:00 Berlin slot would
# trade an intraday stand. The daily digest only READS its DB.
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

# Per-step wall-clock cap — same defect as daily_copilot.sh (measured there 2026-08-10: a
# hanging step ate the whole 1-hour task budget and silently killed every later step). This
# chain gets 2 hours from its Windows task and its steps are genuinely heavy (model training,
# the depot advance), so the cap is wider. The depot advance is the LAST step and the one that
# must not be starved by a slow trainer ahead of it.
STEP_TIMEOUT="${EQUITY_SCOUT_STEP_TIMEOUT:-25m}"

step() {
  local name="$1"
  shift
  echo "[$(date -Is)] START ${name}" >> "$LOG"
  if timeout "$STEP_TIMEOUT" "$@" >> "$LOG" 2>&1; then
    echo "[$(date -Is)] OK ${name}" >> "$LOG"
  else
    local rc=$?
    if [ "$rc" -eq 124 ]; then
      echo "[$(date -Is)] TIMEOUT ${name} (nach ${STEP_TIMEOUT}) — continuing" >> "$LOG"
    else
      echo "[$(date -Is)] FAILED ${name} (exit ${rc}) — continuing" >> "$LOG"
    fi
  fi
}

echo "[$(date -Is)] ===== nightly_train start =====" >> "$LOG"
# Measured 2026-08-11 after the training universe became the fixed 503-name index snapshot
# (was: the current watchlist, ~30 names): ~94 s panel download + ~65 s per preset x 12 presets
# = ~15 min, against this chain's 25-min step cap. It ran in ~60 s on the old universe, so the
# budget is no longer negligible — check this line before adding presets or families.
step train_entry       "$PY" scripts/run_train_entry.py
step learning_snapshot "$PY" scripts/run_learning_snapshot.py
step research_batch    "$PY" scripts/run_research.py --trials 25
# v14: strategy-parameter search — own ledger pool, cheap backtests, wraps when exhausted
step strategy_research "$PY" scripts/run_strategy_research.py --trials 25
step forward_paper     "$PY" scripts/run_forward_paper.py --refresh
step st_swing          "$PY" scripts/run_shortterm.py --lane swing
# session lane overnight sweep: outside the market window this flattens anything the
# settled-bar delay let slip past the in-session force-flat (never holds overnight)
step st_session_sweep  "$PY" scripts/run_shortterm.py --lane session
# The review reads the books AFTER both lane steps, so "what changed tonight" includes
# tonight. Read-only: it changes no rule and promotes nothing (2026-08-16).
step lane_review       "$PY" scripts/run_lane_review.py
# Parameter search + automatic adoption behind its hurdle (T12, Nico 2026-08-16). Runs AFTER
# the review because the review is what motivates it, and it prints its verdict either way.
step lane_tuning       "$PY" scripts/run_lane_tuning.py
step autotrader        "$PY" scripts/run_autotrader.py
echo "[$(date -Is)] ===== nightly_train end =====" >> "$LOG"
