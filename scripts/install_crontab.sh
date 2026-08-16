#!/usr/bin/env bash
# One-shot, idempotent, LINE-MANAGING crontab installer for the copilot automation.
# Manages (a) the daily copilot chain at 18:00 Mon-Fri, (b) the receiver keepalive
# every 5 minutes, (c) the 15-min intraday chain (market-window guard lives inside
# the script; 15 not 10 because yfinance prices are ~15 min delayed anyway),
# (d) the nightly training chain at 02:30 Tue-Sat (post-US-close; v10.1: via the
# guarded wrapper — flock + per-day marker live inside run_nightly_guarded.sh so
# cron, systemd catch-up and Windows task arbitrate cleanly) and (e) the nightly
# universe prefetch at 00:45 Mon-Sat (cache warm-up rotation).
# Any existing line referencing a managed script is REPLACED by its canonical form
# (so cadence changes don't leave the old schedule running in parallel); unmanaged
# entries (e.g. the forward-paper line) are preserved untouched.
# Run manually: ./scripts/install_crontab.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CHAIN_LINE="0 18 * * 1-5 ${REPO_DIR}/scripts/run_daily_guarded.sh cron >> ${REPO_DIR}/copilot.log 2>&1"
RECEIVER_LINE="*/5 * * * * flock -n /tmp/equity-scout-receiver.lock ${REPO_DIR}/scripts/receiver_keepalive.sh >> ${REPO_DIR}/receiver.log 2>&1"
INTRADAY_LINE="*/15 * * * 1-5 flock -n /tmp/equity-scout-intraday.lock ${REPO_DIR}/scripts/intraday_copilot.sh >> ${REPO_DIR}/intraday.log 2>&1"
NIGHTLY_LINE="30 2 * * 2-6 ${REPO_DIR}/scripts/run_nightly_guarded.sh cron >> ${REPO_DIR}/train.log 2>&1"
PREFETCH_LINE="45 0 * * 1-6 flock -n /tmp/equity-scout-prefetch.lock ${REPO_DIR}/scripts/nightly_prefetch.sh >> ${REPO_DIR}/prefetch.log 2>&1"
# v11 crypto lane: Kraken data is real-time and the market never closes — every 15 min
# around the clock; idempotent per completed bar, so overlaps/catch-ups book nothing twice.
CRYPTO_LINE="*/15 * * * * flock -n /tmp/equity-scout-crypto.lock sh -c 'cd ${REPO_DIR} && { .venv/bin/python scripts/run_shortterm.py --lane crypto ; .venv/bin/python scripts/run_watchdog.py ; }' >> ${REPO_DIR}/shortterm.log 2>&1"
# gapfade lane (2026-08-17): every 5 minutes in a window that covers 09:00-09:28 ET in
# both DST regimes; the runner's internal ET gate does the actual timing, so the other
# firings are silent no-ops. Closing-auction fills settle in the nightly chain.
GAPFADE_LINE="*/5 14-16 * * 1-5 flock -n /tmp/equity-scout-gapfade.lock ${REPO_DIR}/scripts/gapfade_lane.sh >> ${REPO_DIR}/shortterm.log 2>&1"
# v11 session lane: PAUSED 2026-08-17. Its ORB entry rule is refuted intraday (1,684
# breakouts, t = -2.68) AND with overnight holding in all three arms
# (docs/research/2026-08-17-orb-overnight-backtest.md) — a paused lane is one cron line
# away from running again; session_lane.sh stays in MANAGED_SCRIPTS so this installer
# REMOVES any leftover per-minute line. The nightly st_session_sweep keeps flattening
# stragglers, and the book stays fully readable in the cockpit.

MANAGED_SCRIPTS="daily_copilot.sh run_daily_guarded.sh receiver_keepalive.sh intraday_copilot.sh nightly_train.sh run_nightly_guarded.sh nightly_prefetch.sh run_shortterm.py run_watchdog.py session_lane.sh gapfade_lane.sh"

current="$(crontab -l 2>/dev/null || true)"
before="$current"

# Drop every line referencing a managed script, then re-add the canonical lines.
# Matched WITHOUT a leading slash: the crypto line invokes its script relatively after a `cd`
# ("cd <repo> && .venv/bin/python scripts/run_shortterm.py"), so a "/scripts/..." pattern
# missed it and every re-run appended a second copy of that line (seen 2026-08-06).
for script in $MANAGED_SCRIPTS; do
  current="$(printf '%s\n' "$current" | grep -vF "scripts/${script}" || true)"
done
for line in "$CHAIN_LINE" "$RECEIVER_LINE" "$INTRADAY_LINE" "$NIGHTLY_LINE" "$PREFETCH_LINE" "$CRYPTO_LINE" "$GAPFADE_LINE"; do
  current="${current}"$'\n'"${line}"
done

if [ "$(printf '%s\n' "$current" | sed '/^$/d' | sort)" = "$(printf '%s\n' "$before" | sed '/^$/d' | sort)" ]; then
  echo "Crontab already up to date — nothing changed."
  exit 0
fi

printf '%s\n' "$current" | sed '/^$/d' | crontab -
echo "Crontab updated. Managed equity-scout lines now:"
crontab -l | grep -F "equity-scout"
