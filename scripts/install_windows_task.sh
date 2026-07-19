#!/usr/bin/env bash
# v9: registers the Windows Task Scheduler task that starts WSL at 18:00 weekdays
# and runs the guarded chain. NEEDS NICO: run this script once yourself — task
# registration on the Windows side is deliberately not automated.
# schtasks reads the XML from the Windows filesystem, so it is staged into the
# user's temp dir first. UTF-8 XML is tried first; some Windows builds insist on
# UTF-16 — the fallback converts and retries.
# Remove the task with: schtasks.exe /delete /tn equity-scout-daily /f
set -eu
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIN_TMP="/mnt/c/Users/NicoSutheimer/AppData/Local/Temp"
XML_SRC="$REPO_DIR/scripts/windows/equity-scout-daily.xml"
cp "$XML_SRC" "$WIN_TMP/equity-scout-daily.xml"
if ! schtasks.exe /create /tn "equity-scout-daily" /xml 'C:\Users\NicoSutheimer\AppData\Local\Temp\equity-scout-daily.xml' /f; then
  # Some Windows builds insist on UTF-16 task XML: rewrite declaration + re-encode.
  python3 - "$XML_SRC" "$WIN_TMP/equity-scout-daily.xml" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read().replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
open(sys.argv[2], "wb").write(text.encode("utf-16"))
PY
  schtasks.exe /create /tn "equity-scout-daily" /xml 'C:\Users\NicoSutheimer\AppData\Local\Temp\equity-scout-daily.xml' /f
fi
schtasks.exe /query /tn "equity-scout-daily" /fo LIST
rm -f "$WIN_TMP/equity-scout-daily.xml"
