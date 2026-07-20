#!/usr/bin/env bash
# v12 M3: stage the LAN dashboard service. It is only ENABLED when DASH_TOKEN
# exists in .env — generating and setting the token is Nico's call (the service
# would fail closed anyway, this just avoids a pointless restart loop).
set -eu
UNIT_DIR="$HOME/.config/systemd/user"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$UNIT_DIR"
cp "$REPO_DIR/scripts/systemd/equity-scout-dash.service" "$UNIT_DIR/"
systemctl --user daemon-reload
if grep -q '^DASH_TOKEN=..*' "$REPO_DIR/.env" 2>/dev/null; then
  systemctl --user try-restart equity-scout-dash.service 2>/dev/null || true
  systemctl --user enable --now equity-scout-dash.service
  echo "Dash-Service läuft: http://$(hostname -I | awk '{print $1}'):8420/?token=<DASH_TOKEN>"
else
  echo "Unit installiert, aber NICHT aktiviert: kein DASH_TOKEN in .env."
  echo "Setzen (z.B.):  echo \"DASH_TOKEN=\$(openssl rand -hex 16)\" >> .env"
  echo "Dann:           ./scripts/install_dash_service.sh"
fi
