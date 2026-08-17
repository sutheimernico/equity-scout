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
step() {
  echo "[$(date -Is)] START $1" >> "$LOG"; shift
  if "$@" >> "$LOG" 2>&1; then echo "[$(date -Is)] OK" >> "$LOG"
  else echo "[$(date -Is)] FAILED (exit $?) — weiter" >> "$LOG"; fi
}
step depth2 uv run python scripts/run_signal_matrix.py --pairs --depth 2 \
  --checkpoint data/matrix_cells_d2.jsonl \
  --out "docs/research/$(date +%F)-signal-matrix-depth2.md"
step depth3 uv run python scripts/run_signal_matrix.py --pairs --depth 3 \
  --tickers $LEADERS --checkpoint data/matrix_cells_d3.jsonl \
  --out "docs/research/$(date +%F)-signal-matrix-depth3.md"
echo "[$(date -Is)] ===== Welle 3 Ende =====" >> "$LOG"
