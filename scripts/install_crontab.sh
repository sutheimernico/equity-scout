#!/usr/bin/env bash
# One-shot, idempotent crontab installer for the copilot automation.
# Adds (a) the daily copilot chain at 18:00 Mon-Fri, (b) the receiver keepalive
# every 5 minutes, (c) the 30-min intraday chain (market-window guard lives inside
# the script), (d) the nightly training chain at 02:30 Tue-Sat (post-US-close) and
# (e) the nightly universe prefetch at 00:45 Mon-Sat (cache warm-up rotation) —
# each only if not already present. Existing entries (e.g. the forward-paper line)
# are preserved untouched.
# Run manually: ./scripts/install_crontab.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CHAIN_LINE="0 18 * * 1-5 ${REPO_DIR}/scripts/daily_copilot.sh >> ${REPO_DIR}/copilot.log 2>&1"
RECEIVER_LINE="*/5 * * * * flock -n /tmp/equity-scout-receiver.lock ${REPO_DIR}/scripts/receiver_keepalive.sh >> ${REPO_DIR}/receiver.log 2>&1"
INTRADAY_LINE="*/30 * * * 1-5 flock -n /tmp/equity-scout-intraday.lock ${REPO_DIR}/scripts/intraday_copilot.sh >> ${REPO_DIR}/intraday.log 2>&1"
NIGHTLY_LINE="30 2 * * 2-6 flock -n /tmp/equity-scout-nightly.lock ${REPO_DIR}/scripts/nightly_train.sh >> ${REPO_DIR}/train.log 2>&1"
PREFETCH_LINE="45 0 * * 1-6 flock -n /tmp/equity-scout-prefetch.lock ${REPO_DIR}/scripts/nightly_prefetch.sh >> ${REPO_DIR}/prefetch.log 2>&1"

current="$(crontab -l 2>/dev/null || true)"
added=0

for line in "$CHAIN_LINE" "$RECEIVER_LINE" "$INTRADAY_LINE" "$NIGHTLY_LINE" "$PREFETCH_LINE"; do
  if ! printf '%s\n' "$current" | grep -qF "$line"; then
    current="${current}"$'\n'"${line}"
    added=$((added + 1))
  fi
done

if [ "$added" -eq 0 ]; then
  echo "Crontab already up to date — nothing added."
  exit 0
fi

printf '%s\n' "$current" | sed '/^$/d' | crontab -
echo "Installed ${added} new cron line(s):"
crontab -l | grep -F "equity-scout"
