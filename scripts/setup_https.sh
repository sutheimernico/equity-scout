#!/usr/bin/env bash
# HTTPS für das Cockpit — der eine Schritt, der Root braucht (2026-08-27).
#
#   sudo bash scripts/setup_https.sh
#
# Warum überhaupt: Web Push, Service Worker und die Installation als App verlangen alle
# eine HTTPS-Adresse. `http://100.99.224.50:8420` erfüllt das nicht, `https://<host>.ts.net`
# schon — Tailscale stellt dafür ein echtes Let's-Encrypt-Zertifikat aus, kostenlos, und
# die Adresse bleibt im Tailnet: nur Nicos eigene Geräte erreichen sie, das Internet nicht.
#
# Was passiert hier:
#   1. `tailscale set --operator` — damit der normale Benutzer danach ohne sudo an das
#      Zertifikat kommt (sonst müsste jeder spätere Handgriff wieder Root sein).
#   2. `tailscale serve` — HTTPS auf 443 vor den Dienst auf 127.0.0.1:8420.
#   3. PUBLIC_BASE_URL in .env — damit ein Tipp auf eine Benachrichtigung die richtige
#      Seite öffnet statt nur die Startseite.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:  sudo bash scripts/setup_https.sh" >&2
  exit 1
fi

REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo nicosutheimer)}"
PORT="${ES_PORT:-8420}"

echo "==> Operator setzen (danach braucht Tailscale hier kein sudo mehr)"
tailscale set "--operator=${REAL_USER}"


echo "==> Tailscale-SSH sicherstellen (Zugang vom Handy)"
tailscale set --ssh

DOMAIN="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "==> Adresse: https://${DOMAIN}"

echo "==> Zertifikat holen (beim ersten Mal dauert das ein paar Sekunden)"
# Wie bei serve hängt auch das an einem Schalter in der Admin-Konsole ("HTTPS Certificates").
# set -e würde hier sonst wortlos abbrechen, deshalb die eigene Meldung.
if ! CERT_OUT="$(tailscale cert "${DOMAIN}" 2>&1)"; then
  printf '%s\n' "$CERT_OUT" >&2
  echo >&2
  echo "STOPP: Das Zertifikat kam nicht. Meist fehlt der Schalter 'HTTPS Certificates':" >&2
  echo "  https://login.tailscale.com/admin/dns  (Abschnitt HTTPS Certificates -> Enable)" >&2
  echo "Danach dieses Skript einfach noch einmal starten." >&2
  exit 4
fi

echo "==> HTTPS vor den Dienst auf 127.0.0.1:${PORT} hängen"
# Serve muss EINMAL pro Tailnet in der Admin-Konsole freigeschaltet werden. Fehlt das,
# antwortet Tailscale mit einem Hinweis samt node-spezifischer URL - und mit Exit 0, also
# muss die Ausgabe geprüft werden, nicht der Rückgabewert (verifiziert am 2026-08-28).
SERVE_OUT="$(tailscale serve --bg --https=443 "http://127.0.0.1:${PORT}" 2>&1 || true)"
printf '%s\n' "$SERVE_OUT"
if printf '%s' "$SERVE_OUT" | grep -qi 'not enabled'; then
  echo
  echo "STOPP: Serve ist auf deinem Tailnet noch nicht freigeschaltet."
  echo "Das ist ein Klick im Browser, kein Befehl - Adresse steht direkt darüber."
  echo "Danach dieses Skript einfach noch einmal starten."
  exit 2
fi
if ! tailscale serve status 2>/dev/null | grep -q '127.0.0.1:'"${PORT}"; then
  echo "STOPP: Serve meldet keinen Eintrag auf 127.0.0.1:${PORT} - bitte Ausgabe oben prüfen." >&2
  exit 3
fi

ENV_FILE="${REPO_DIR}/.env"
if grep -q '^PUBLIC_BASE_URL=' "$ENV_FILE" 2>/dev/null; then
  sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://${DOMAIN}|" "$ENV_FILE"
else
  printf '\n# Öffentliche (Tailnet-)Adresse des Cockpits — Ziel der Benachrichtigungs-Links.\nPUBLIC_BASE_URL=https://%s\n' "${DOMAIN}" >> "$ENV_FILE"
fi
chown "${REAL_USER}:${REAL_USER}" "$ENV_FILE"

echo
echo "Fertig. Und jetzt:"
echo "  1. Dienst neu starten, damit er PUBLIC_BASE_URL sieht:"
echo "       sudo systemctl restart equity-scout-dash   (oder wie der Dienst bei dir heißt)"
echo "  2. Auf dem Handy https://${DOMAIN} öffnen (Tailscale muss an sein)."
echo "  3. Chrome-Menü -> 'App installieren'."
echo "  4. In der App: Mehr -> Benachrichtigungen -> einschalten."
echo
echo "Prüfen, ob die App-Verknüpfung steht:"
echo "  curl -s https://${DOMAIN}/.well-known/assetlinks.json"
