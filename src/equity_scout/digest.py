"""Daily e-mail digest of the decision inbox.

Rendering is pure; sending goes through an injectable smtp_factory (defaults to
smtplib.SMTP_SSL) so tests never open sockets. Config is fail-safe like the
telegram client: missing/malformed env -> None + stderr hint, never a crash.
"""
from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage

_STATUS_ICON = {"open": "📬 offen", "buy": "✅ gekauft-Entscheidung",
                "pass": "❌ abgelehnt", "later": "⏸ später"}


def load_smtp_config(env: dict) -> dict | None:
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO")
    if any(not env.get(key) for key in required):
        return None
    try:
        port = int(env["SMTP_PORT"])
    except ValueError:
        print("SMTP_PORT is not an integer — digest disabled.", file=sys.stderr)
        return None
    return {
        "host": env["SMTP_HOST"], "port": port, "user": env["SMTP_USER"],
        "password": env["SMTP_PASSWORD"], "to": env["DIGEST_TO"],
    }


def build_digest(pitches: list[dict], *, date_label: str) -> str:
    """German plain-text digest: open pitches first, then recent decisions."""
    lines = [f"Copilot-Digest {date_label}", ""]
    open_pitches = [p for p in pitches if p["status"] == "open"]
    decided = [p for p in pitches if p["status"] != "open"]
    if not open_pitches:
        lines.append("Aktuell keine offenen Pitches.")
    else:
        lines.append(f"Offene Pitches ({len(open_pitches)}):")
        for p in open_pitches:
            lines.append(
                f"  📬 offen — {p['ticker']} · Score {round(p['composite'] * 100)}/100"
                f" · Kurs {p['price']:.2f} · seit {p['created_at'][:10]}"
            )
    if decided:
        lines.append("")
        lines.append("Entschieden:")
        for p in decided:
            icon = _STATUS_ICON.get(p["status"], p["status"])
            lines.append(f"  {icon} — {p['ticker']} · am {(p['decided_at'] or '')[:10]}")
    lines += ["", "Keine Anlageberatung."]
    return "\n".join(lines)


def send_digest(config: dict, subject: str, body: str, smtp_factory=smtplib.SMTP_SSL) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["user"]
    msg["To"] = config["to"]
    msg.set_content(body)
    with smtp_factory(config["host"], config["port"]) as smtp:
        smtp.login(config["user"], config["password"])
        smtp.send_message(msg)
