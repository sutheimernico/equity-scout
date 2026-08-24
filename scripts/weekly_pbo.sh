#!/usr/bin/env bash
# Probability of Backtest Overfitting over the research ledger's best configs — once a week.
#
# Why this exists as a cron line (2026-08-24): `run_pbo.py` had never been wired into any
# chain. The ledger's stored PBO was 0.7714, computed 2026-06-26 over 13 configs, while the
# ledger grew to 4,600 trials. So the one number that says "is this search finding skill or
# luck" was two months stale, and the Auto-Research tab was showing it as if it were current.
#
# Why weekly and not nightly: one walk-forward per config (`run_pbo.py`'s own docstring says
# "run it occasionally, not in the loop"). Sunday 04:00 — after the last nightly of the week
# (Tue–Sat 02:30) has added its trials, before the Monday full-universe scout at 05:30.
#
# Why its own script rather than a step in scheduled_run.sh: that file ends in `exec`, and
# PBO failing must never fail the weekly scout. Same ownership/blast-radius reasoning as
# insider_shadow_lane.sh.
#
# A missed week costs nothing — the next run reads the same ledger.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

# No python-dotenv in this repo — the shell sources .env, same as every other chain here.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "[$(date -Is)] ===== weekly PBO ====="
exec "$PY" scripts/run_pbo.py
