#!/usr/bin/env bash
# Local Ollama as a systemd --user service.
#
# Why a service and not "start it when needed": the 18:00 chain generates the phone
# cockpit's AI texts (scripts/run_insights.py). A cold model load costs ~27 s, a warm
# call ~5.6 s (measured 2026-08-05), so the chain wants the server already up.
#
# Cost note: purely local inference. Ollama unloads an idle model after OLLAMA_KEEP_ALIVE,
# so the resting cost is the daemon, not the 4.7 GB of weights.
set -euo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
BIN="$(command -v ollama)"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/ollama.service" <<EOF
[Unit]
Description=Ollama local LLM server
After=network.target

[Service]
Type=simple
ExecStart=${BIN} serve
Restart=on-failure
RestartSec=5
# Keep one model resident across the chain's ~12 stocks instead of reloading per call.
Environment=OLLAMA_KEEP_ALIVE=15m

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ollama.service
systemctl --user --no-pager status ollama.service | head -5
