#!/usr/bin/env bash
# Daily copilot chain: (Mondays: screener first) -> radar -> earnings -> evidence ->
# notify -> score watchlist -> resolve predictions -> resolve evidence -> resolve events ->
# lanes -> digest -> insights.
#
# Delivery first, cosmetics last: everything that pitches, books or resolves runs before
# `insights`, which only fills a display cache and is by far the slowest step.
#
# Design rules:
# - Every step degrades independently: a failed step is logged and the chain
#   CONTINUES — one dead source/API must never silence the pitches or the ledger.
# - Uses .venv/bin/python directly (NOT `uv run`): cron's minimal PATH has no uv,
#   and the long-running forward-paper cron line already proves this pattern.
# - .env is sourced when present (Telegram/EDGAR/SMTP config); without it every
#   consumer degrades politely (inbox-only pitches, unconfigured 13F, stdout digest).
# - All output appends to copilot.log next to the repo (see docs/scheduling.md).
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PY="$REPO_DIR/.venv/bin/python"
LOG="$REPO_DIR/copilot.log"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Per-step wall-clock cap. The chain already degrades per step ("FAILED … — continuing"), but
# a step that HANGS was unbounded, and the whole chain runs inside a 1-hour Windows Task
# limit. Measured 2026-08-10: `insights` crawled under heavy CPU load, the Task Scheduler
# killed the chain at 19:00 with 0xC000013A, and everything after it — evidence, fscore, the
# resolvers and NOTIFY — never ran. No log line, no day marker: a silent loss of the day's
# delivery caused by a cosmetic step. Measured again 2026-08-11: it is not "slow under load",
# it costs ~90 s x 30 titles by design — hence its own cap at the end of the chain, below.
# 12 min leaves room for the whole chain inside the hour; override per run if ever needed.
STEP_TIMEOUT="${EQUITY_SCOUT_STEP_TIMEOUT:-12m}"

step() {
  local name="$1"
  shift
  echo "[$(date -Is)] START ${name}" >> "$LOG"
  if timeout "$STEP_TIMEOUT" "$@" >> "$LOG" 2>&1; then
    echo "[$(date -Is)] OK ${name}" >> "$LOG"
  else
    local rc=$?
    if [ "$rc" -eq 124 ]; then
      # 124 is timeout(1)'s own code — named separately so the log distinguishes "too slow"
      # from "broken", which need different fixes.
      echo "[$(date -Is)] TIMEOUT ${name} (nach ${STEP_TIMEOUT}) — continuing" >> "$LOG"
    else
      echo "[$(date -Is)] FAILED ${name} (exit ${rc}) — continuing" >> "$LOG"
    fi
  fi
}

echo "[$(date -Is)] ===== daily_copilot start =====" >> "$LOG"

# Mondays: refresh the screener BEFORE the daily chain so the radar sees fresh
# finalists, and re-measure person track records (45/135d disclosure lag — weekly
# is plenty; needs one yfinance panel download).
if [ "$(date +%u)" = "1" ]; then
  step scout ./scripts/scheduled_run.sh
  step person_scores "$PY" scripts/run_person_scores.py
fi

step radar               "$PY" scripts/run_radar.py
step earnings            "$PY" scripts/run_earnings.py
step evidence            "$PY" scripts/run_evidence.py
# Piotroski F-Scores for the fresh watchlist (EDGAR companyfacts; unconfigured
# without EDGAR_USER_AGENT). Before notify so today's pitches carry today's scores.
step fscore              "$PY" scripts/run_fscore.py
# --min-pitches 5: the daily delivery pitches several names (topped up by composite),
# not only strict in-zone hits (Nico 2026-07-15).
step notify              "$PY" scripts/run_notify.py --min-pitches 5
step score_watchlist     "$PY" scripts/run_score_watchlist.py
step resolve_predictions "$PY" scripts/run_resolve_predictions.py
step resolve_evidence    "$PY" scripts/run_resolve_evidence.py
# Event-reaction study (Strang B4): 1d/5d windows only (1h is not measurable on
# daily closes) — 1x/day is plenty, so this is not in intraday_copilot.sh's 15-min chain.
step resolve_events      "$PY" scripts/run_resolve_events.py
step lanes               "$PY" scripts/run_lanes.py
step digest              "$PY" scripts/run_digest.py

# Phone-card AI texts + 1y sparkline series. LAST on purpose, and with a wider cap than the
# rest of the chain — measured 2026-08-11: ~90 s per title over 30 titles (`--limit` caps
# only the watchlist head, screener picks are appended) means ~45 min, and as the second step
# it made the other ten wait 12 minutes for a cosmetic cache. Nothing in the chain reads its
# output — only /api/briefs does — so a cap that fires here costs no delivery, and the script
# renews oldest-text-first so a cut-short run still moves the tail forward. Needs Ollama up
# (scripts/install_ollama_service.sh); without it the texts store as honest nulls.
# The whole chain lives inside a 1-hour Windows Task limit, so this is not the full ~45 min.
STEP_TIMEOUT="${EQUITY_SCOUT_INSIGHTS_TIMEOUT:-35m}"
step insights            "$PY" scripts/run_insights.py --limit 12

echo "[$(date -Is)] ===== daily_copilot end =====" >> "$LOG"
