#!/usr/bin/env bash
# SessionStart hook: brief the assistant on the v15 rollout state (armed 2026-08-06).
#
# Nico's requirement (2026-08-06): the next session must know "was Sache ist" without
# being told — Wave 1 landed, the first real resolutions are date-gated, P1/P2 are
# blocked on the session-lane strand, P2a is the executable next step.
#
# Same lifecycle rule as session_start_status.sh: this is scaffolding for ONE rollout,
# not a permanent status board. Remove the hook (and this script) once P1/P2 are
# underway and the Wave-1 checkpoint has been confirmed green.
set -u

REPO_DIR="/home/nicosutheimer/private/equity-scout"
PY="$REPO_DIR/.venv/bin/python"
DB="$REPO_DIR/equity_scout.db"
[ -x "$PY" ] && [ -f "$DB" ] || exit 0

exec "$PY" - "$DB" <<'PYEOF'
import sqlite3
import sys
from datetime import date

try:
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    total, resolved = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(resolved_at IS NOT NULL), 0) FROM entry_predictions"
    ).fetchone()
    con.close()
except Exception:
    sys.exit(0)  # DB locked/absent: stay silent rather than mislead

today = date.today().isoformat()
if resolved > 0:
    checkpoint = f"✅ Lern-Loop liefert: {resolved}/{total} Predictions resolved."
elif today >= "2026-08-12":
    checkpoint = (
        f"⚠️ CHECKPOINT VERLETZT: {today}, immer noch 0/{total} resolved — Wave-1-Plan "
        "wieder öffnen (plans/2026-08-05-v15-wave1-resolve-honesty.md), Diagnose war lückenhaft."
    )
else:
    checkpoint = f"Erste Auflösungen ab 2026-08-11 erwartet (0/{total} resolved ist bis dahin normal)."

print(
    "[equity-scout v15] Wave 1 (Resolve Honesty) DONE 2026-08-06 — Spec: "
    "docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md\n"
    f"{checkpoint}\n"
    "Nächster freier Schritt: P2a-Backfill ausführen "
    "(plans/2026-08-06-v15-p2a-historical-backfill.md, kein File-Overlap).\n"
    "Blockiert: P1 Depot-Routing + P2 Evidence-Lanes bis Session-Lane-Plan-Outcome "
    "geschlossen UND Nico das Alpaca-Konto PA3AKCY23RCD resettet hat.\n"
    "Koordination: st_session.py / alpaca_* / run_shortterm.py / PLAN.md / frontend/ "
    "gehören dem parallelen Strang — Commits nur mit expliziten Pfaden."
)
PYEOF
