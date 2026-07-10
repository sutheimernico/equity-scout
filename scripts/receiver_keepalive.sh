#!/usr/bin/env bash
# Receiver keepalive: run under `flock -n` from cron every few minutes. If the
# receiver already holds the lock this exits immediately; after a WSL restart the
# next cron fire brings it back. Without Telegram config it is a quiet no-op —
# an unconfigured receiver is not an error (same rule as run_notify/digest).
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if [ -z "${COPILOT_TG_BOT_TOKEN:-}" ] || [ -z "${COPILOT_TG_CHAT_ID:-}" ]; then
  exit 0
fi

exec "$REPO_DIR/.venv/bin/python" scripts/run_receiver.py
