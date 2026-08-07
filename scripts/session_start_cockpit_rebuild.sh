#!/usr/bin/env bash
# SessionStart hook: standing order (Nico, 2026-08-07) — rebuild the phone cockpit to the
# mockup-v2 structure WITHOUT asking for further confirmation. The go was given in chat
# ("hast freie Macht … einfach einbaust"). Silences itself once the plan doc records DONE.
PLAN="$HOME/private/equity-scout/docs/superpowers/plans/2026-08-07-cockpit-rebuild-from-mockup-v2.md"
[ -f "$PLAN" ] || exit 0
grep -qi "^Outcome: DONE" "$PLAN" && exit 0

BUNDLE="$HOME/backups/equity-scout-pre-cockpit-rebuild-2026-08-07.bundle"
if [ -f "$BUNDLE" ]; then
  BK="vorhanden: ~/backups/equity-scout-pre-cockpit-rebuild-2026-08-07.bundle + git tag pre-cockpit-rebuild-2026-08-07"
else
  BK="FEHLT — vor Arbeitsbeginn neu ziehen: git tag + git bundle create --all"
fi

cat <<EOF
[equity-scout] STEHENDER AUFTRAG (Nicos Go 2026-08-07, KEINE weiteren Rückfragen):
Handy-Cockpit auf die Mockup-v2-Struktur umbauen.
  Plan:    docs/superpowers/plans/2026-08-07-cockpit-rebuild-from-mockup-v2.md
  Mockup:  docs/design/2026-08-07-phone-cockpit-mockup-v2.html (klickbare Referenz)
  Backup:  $BK
Regeln: nichts löschen, nur einsortieren (harte Anforderung); kleine atomare Commits auf
autopilot/work; Gates ruff+pytest, tsc+vitest+vite build; am Ende dist bauen, Dash-Service
neu starten, Nico per Telegram informieren (telegram_client, COPILOT_TG_*).
Nach Abschluss 'Outcome: DONE' als eigene Zeile in den Plan schreiben — dann schweigt dieser Hook.
EOF
