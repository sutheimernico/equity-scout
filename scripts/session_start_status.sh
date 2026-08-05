#!/usr/bin/env bash
# SessionStart hook: surface the result of the unattended Alpaca precondition check.
#
# Nico's requirement (2026-08-05): "ich möchte gar nicht sagen müssen, ob das funktioniert
# hat" — the assistant must know the state of the automated job without being told. The
# check runs on cron and disarms itself, so its outcome would otherwise only exist in a log
# nobody opens.
#
# Deliberately SILENT while there is nothing to report. This fires on every session start in
# ~/private, including sessions about entirely different projects, so a line that says "still
# waiting" every day would be pure noise and would get filtered out mentally — exactly what
# must not happen to the one line that matters.
#
# Remove the hook once the session-lane rewrite is done; it is scaffolding for one migration,
# not a permanent status board.
set -u

REPO_DIR="/home/nicosutheimer/private/equity-scout"
MARKER="$REPO_DIR/.state/alpaca_verified"
LOG="$REPO_DIR/alpaca_verify.log"

if [ -f "$MARKER" ]; then
    echo "[equity-scout] Alpaca-Vorbedingung BESTANDEN am $(cat "$MARKER" 2>/dev/null) —" \
         "Session-Lane: Tasks 6–9 (Broker verdrahten, Minutentakt) sind frei." \
         "Messwerte: $LOG"
    exit 0
fi

# No marker: either it never ran (silence is correct) or it ran and failed (must be said).
if [ -f "$LOG" ] && grep -q "^===== FAILED" "$LOG"; then
    echo "[equity-scout] Alpaca-Vorbedingung FEHLGESCHLAGEN — Session-Lane bleibt blockiert." \
         "Letzter Fehler: $(grep -A1 "^===== FAILED" "$LOG" | tail -1 | cut -c1-160)." \
         "Voll: $LOG"
fi
