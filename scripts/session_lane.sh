#!/usr/bin/env bash
# The session lane alone, once per minute inside the US market window (vision v11 lane
# `session`, real-time Alpaca path since 2026-08-06).
#
# Why it is its OWN script and log rather than a step in intraday_copilot.sh:
# - Cadence. The lane trades 1-minute bars; running it on the copilot's 15-minute cron threw
#   away 14 of every 15 minutes of the latency this rewrite bought (design decision 7).
# - Isolation. Its own lock file means a slow radar or evidence fetch can never delay an
#   entry, and a hanging lane can never delay the copilot.
# - Readability. `intraday.log` mixes four steps; a minute cron would bury them.
#
# `flock -n` in the cron line SKIPS a minute rather than queueing it: a run that overruns its
# minute is dropped, never stacked. run_session's own market-window guard exits before any
# network call outside the session, so the other ~1,380 minutes of the day cost nothing.
#
# A run that decides nothing prints nothing (session_report_due) — at 390 runs a day the log
# is only readable if silence is the default.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1
PY="$REPO_DIR/.venv/bin/python"

# No python-dotenv in this repo — the shell sources .env, same as every other chain here.
# Without the Alpaca keys run_session degrades to the delayed yfinance path and says so.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Wall-clock cap, shorter than the cron cadence it runs on (2026-08-11). `flock -n` already
# stops runs from stacking, but that same lock is what makes a HANG dangerous here: while one
# run holds it, every following minute is skipped, so a single stuck network call would take
# the lane silently offline for as long as the process lives. Capping at 55s means the worst
# case costs one minute instead of a session. 124 (timeout's own code) is left as-is: the cron
# line has no error branch, and the next minute simply tries again.
exec timeout "${EQUITY_SCOUT_SESSION_TIMEOUT:-55s}" "$PY" scripts/run_shortterm.py --lane session
