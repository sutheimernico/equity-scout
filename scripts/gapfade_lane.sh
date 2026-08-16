#!/usr/bin/env bash
# The gap-fade lane alone, every 5 minutes inside its morning window (lane `gapfade`,
# 2026-08-17). Own script, lock and log for the same reasons as session_lane.sh.
#
# The cron window (14:00-16:55 local) deliberately covers 8:00-10:55 ET in BOTH central
# European DST regimes — the runner's own ET gate (09:00-09:28 for signals, later runs
# absorb the auction fills) decides what actually happens; the extra cron firings are
# silent no-ops. The closing-auction fill (16:00 ET = evening local) is settled by the
# nightly chain's st_gapfade_settle step, not by this cron.
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

# Wall-clock cap under the 5-minute cadence: a hang must cost one slot, not the morning.
exec timeout "${EQUITY_SCOUT_GAPFADE_TIMEOUT:-240s}" "$PY" scripts/run_shortterm.py --lane gapfade
