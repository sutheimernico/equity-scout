#!/usr/bin/env bash
# Welle 3: Kombinationstiefe. Wartet auf das Ende der ersten Kette (Tiefe 1 + News), dann:
#   3a) Tiefe 2 (251 Bedingungen) über das ganze Universum   — gemessen ~2,2 h
#   3b) Tiefe 3 (1733 Bedingungen) über 12 Leitinstrumente   — gemessen ~2,6 h
# Tiefe 4 (8516 Bedingungen) läuft NICHT heute: ~21 h selbst auf 12 Titeln. Sie gehört in eine
# eigene Nacht ODER, methodisch besser, nur auf die Kombinationen, die in Tiefe 3 Substanz zeigen.
# Getrennte Checkpoints pro Welle, weil die Wiederaufnahme sonst Ticker als fertig sähe.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
if [ -f .env ]; then set -a; . ./.env; set +a; fi
LOG="night_matrix.log"
LEADERS="SPY QQQ AAPL NVDA GLD USO TLT UUP XLE VXX IWM MSFT"
while ! grep -q "===== Nachtkette Ende" "$LOG" 2>/dev/null; do sleep 60; done
echo "[$(date -Is)] ===== Welle 3 Start =====" >> "$LOG"
# Every step runs under a memory ceiling (scripts/mem_guard.sh): the 2026-08-19 run was
# shot by the kernel OOM-killer at 10.1 GiB in a 15.8 GiB VM and took the VM with it,
# leaving a 0-byte log. Missing guard => run uncapped rather than not at all.
MEM_GUARD="scripts/mem_guard.sh"
[ -x "$MEM_GUARD" ] || MEM_GUARD=""
step() {
  echo "[$(date -Is)] START $1" >> "$LOG"; shift
  if ${MEM_GUARD:+"$MEM_GUARD"} "$@" >> "$LOG" 2>&1; then echo "[$(date -Is)] OK" >> "$LOG"
  else echo "[$(date -Is)] FAILED (exit $?) — weiter" >> "$LOG"; fi
}
# CELLS-ONLY wie Welle 1: die Report-Phase (Pooling, Plateaus, Hold-out) läuft erst nach der
# Pooling-Härtung — das Hold-out wird nicht auf aufgeblähte t-Werte ausgegeben (2026-08-18).
step depth2 uv run python scripts/run_signal_matrix.py --pairs --depth 2 --phase cells \
  --checkpoint data/matrix_cells_d2.jsonl
step depth3 uv run python scripts/run_signal_matrix.py --pairs --depth 3 --phase cells \
  --tickers $LEADERS --checkpoint data/matrix_cells_d3.jsonl
echo "[$(date -Is)] ===== Welle 3 Ende =====" >> "$LOG"
