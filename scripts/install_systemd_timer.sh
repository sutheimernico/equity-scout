#!/usr/bin/env bash
# v9: installs the persistent daily timer (catch-up layer — fires a missed 18:05
# slot at the next WSL start). Idempotent: cp + daemon-reload + enable are all safe
# to re-run. Linger is best-effort: without it the timer still works for every
# interactively started WSL session (the only kind this box has).
set -eu
UNIT_DIR="$HOME/.config/systemd/user"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$UNIT_DIR"
cp "$REPO_DIR/scripts/systemd/equity-scout-daily.service" "$UNIT_DIR/"
cp "$REPO_DIR/scripts/systemd/equity-scout-daily.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now equity-scout-daily.timer
loginctl enable-linger "$USER" 2>/dev/null \
  || echo "Hinweis: enable-linger nicht möglich (ok — Timer läuft in jeder interaktiven WSL-Session)."
systemctl --user list-timers equity-scout-daily.timer --no-pager
