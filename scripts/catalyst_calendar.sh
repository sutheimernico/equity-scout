#!/usr/bin/env bash
# The forward-looking catalyst calendar (v16, 2026-08-19), once a day.
#
# Daily is the right cadence: trial completion dates and earnings dates move on the scale of
# days, never minutes. Runs before the US open so a catalyst due today is already in the
# signal book when the session starts.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

exec timeout "${EQUITY_SCOUT_CALENDAR_TIMEOUT:-600s}" "$PY" scripts/run_catalyst_calendar.py
