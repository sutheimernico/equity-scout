#!/usr/bin/env bash
# One-shot guided Telegram setup for the daily update chat.
# Asks for the bot token, discovers your chat id from the bot's pending updates,
# writes both into .env (replacing any previous COPILOT_TG_ lines, keeping the rest),
# and sends a test message. Safe to re-run any time.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PY="$REPO_DIR/.venv/bin/python"

echo "== equity-scout Telegram-Setup =="
echo
echo "Schritt 1: Falls du noch keinen Bot hast — in Telegram @BotFather öffnen,"
echo "  /newbot senden, Anweisungen folgen und den Token kopieren."
echo
read -r -p "Bot-Token hier einfügen: " TOKEN
if [ -z "$TOKEN" ]; then
  echo "Kein Token eingegeben — Abbruch."
  exit 1
fi

echo
echo "Schritt 2: Öffne in Telegram den Chat mit deinem Bot und schicke ihm"
echo "  IRGENDEINE Nachricht (z. B. 'hi') — sonst kann ich deine Chat-ID nicht sehen."
read -r -p "Danach hier Enter drücken ... " _

CHAT_ID="$("$PY" - "$TOKEN" <<'EOF'
import json
import sys
import urllib.request

token = sys.argv[1]
url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    with urllib.request.urlopen(url, timeout=30) as resp:
        updates = json.load(resp).get("result", [])
except Exception as exc:  # noqa: BLE001 - a setup script reports, it doesn't crash
    print(f"FEHLER: {exc}", file=sys.stderr)
    sys.exit(1)
chat_ids = [u["message"]["chat"]["id"] for u in updates if "message" in u]
print(chat_ids[-1] if chat_ids else "")
EOF
)"

if [ -z "$CHAT_ID" ]; then
  echo
  echo "Keine Nachricht gefunden. Bitte dem Bot zuerst eine Nachricht schicken"
  echo "und das Skript danach erneut ausführen: ./scripts/setup_telegram.sh"
  exit 1
fi

touch .env
grep -v '^COPILOT_TG_BOT_TOKEN=' .env | grep -v '^COPILOT_TG_CHAT_ID=' > .env.tmp || true
{
  printf 'COPILOT_TG_BOT_TOKEN=%s\n' "$TOKEN"
  printf 'COPILOT_TG_CHAT_ID=%s\n' "$CHAT_ID"
} >> .env.tmp
mv .env.tmp .env

"$PY" - "$TOKEN" "$CHAT_ID" <<'EOF'
import json
import sys
import urllib.request

token, chat_id = sys.argv[1], sys.argv[2]
payload = json.dumps({
    "chat_id": int(chat_id),
    "text": "equity-scout ✅ Telegram eingerichtet — hier kommt ab jetzt werktags um "
            "18:00 dein Daily-Update (Pitches mit Kauf-Buttons + Tages-Zusammenfassung).",
}).encode("utf-8")
request = urllib.request.Request(
    f"https://api.telegram.org/bot{token}/sendMessage",
    data=payload, headers={"Content-Type": "application/json"},
)
urllib.request.urlopen(request, timeout=30)
print("Testnachricht gesendet — schau auf dein Handy.")
EOF

echo
echo "Fertig. Chat-ID ${CHAT_ID} in .env eingetragen."
echo "Falls noch nicht geschehen: ./scripts/install_crontab.sh ausführen."
