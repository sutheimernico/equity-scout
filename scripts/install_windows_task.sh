#!/usr/bin/env bash
# v9/v10.1: registers the Windows Task Scheduler tasks that start WSL and run the
# guarded chains — equity-scout-daily (18:00 Mon-Fri) and equity-scout-nightly
# (02:40 Tue-Sat; wakes the auto-depot/training chain even when WSL is down) and
# equity-scout-session (every 10 min 14:20-22:20 Mon-Fri; wakes the box for the US session so
# the session lane's MINUTE cron inside WSL can fire at all).
# All three carry WakeToRun since 2026-08-10 — daily and nightly were registered without it,
# so their slots silently depended on the machine already being awake. StartWhenAvailable
# only catches up after a wake and was not a substitute.
# NEEDS NICO: run this script once yourself — task registration on the Windows
# side is deliberately not automated.
# schtasks reads the XML from the Windows filesystem, so it is staged into the
# user's temp dir first. UTF-8 XML is tried first; some Windows builds insist on
# UTF-16 — the fallback converts and retries.
# Remove a task with: schtasks.exe /delete /tn <name> /f
set -eu
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIN_TMP="/mnt/c/Users/NicoSutheimer/AppData/Local/Temp"

install_task() {
  local name="$1"
  local xml_src="$REPO_DIR/scripts/windows/${name}.xml"
  cp "$xml_src" "$WIN_TMP/${name}.xml"
  if ! schtasks.exe /create /tn "$name" /xml "C:\\Users\\NicoSutheimer\\AppData\\Local\\Temp\\${name}.xml" /f; then
    # Some Windows builds insist on UTF-16 task XML: rewrite declaration + re-encode.
    python3 - "$xml_src" "$WIN_TMP/${name}.xml" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read().replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
open(sys.argv[2], "wb").write(text.encode("utf-16"))
PY
    schtasks.exe /create /tn "$name" /xml "C:\\Users\\NicoSutheimer\\AppData\\Local\\Temp\\${name}.xml" /f
  fi
  schtasks.exe /query /tn "$name" /fo LIST
  rm -f "$WIN_TMP/${name}.xml"
}

install_task equity-scout-daily
install_task equity-scout-nightly
# The session lane's minute cron can only fire while WSL is up — this is the only layer that
# can wake the machine before the opening bell (added 2026-08-06 with the per-minute cadence).
install_task equity-scout-session
