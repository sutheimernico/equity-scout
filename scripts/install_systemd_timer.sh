#!/usr/bin/env bash
# v9: installs the persistent daily timer (catch-up layer — fires a missed 18:05
# slot at the next WSL start). v10.1 adds the nightly timer the same way (02:35
# Tue-Sat, catches up the auto-depot/training chain). Idempotent: cp +
# daemon-reload + enable are all safe to re-run; re-running also applies unit
# edits via try-restart (enable --now alone does not restart an already-active
# timer, so edits would otherwise sit unapplied until the next natural stop).
# Linger is best-effort: without it the timers still work for every interactively
# started WSL session (the only kind this box has).
set -eu
UNIT_DIR="$HOME/.config/systemd/user"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$UNIT_DIR"
for unit in equity-scout-daily equity-scout-nightly; do
  cp "$REPO_DIR/scripts/systemd/${unit}.service" "$UNIT_DIR/"
  cp "$REPO_DIR/scripts/systemd/${unit}.timer" "$UNIT_DIR/"
done
systemctl --user daemon-reload
for unit in equity-scout-daily equity-scout-nightly; do
  systemctl --user try-restart "${unit}.timer" 2>/dev/null || true
  systemctl --user enable --now "${unit}.timer"
done
loginctl enable-linger "$USER" 2>/dev/null \
  || echo "Hinweis: enable-linger nicht möglich (ok — Timer läuft in jeder interaktiven WSL-Session)."
systemctl --user list-timers 'equity-scout-*' --no-pager
