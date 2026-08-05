"""Telegram notification for the one-shot Alpaca precondition check.

Nico asked to be told actively rather than to remember to read `alpaca_verify.log`. The
check runs hourly inside the US session and disarms itself on the first pass, so this fires
AT MOST ONCE per outcome — a closed-market skip (exit 2) is silent by design, otherwise the
job would send five "nothing yet" messages every weekday.

Reads the verification output on stdin, so the message quotes what actually happened
instead of re-deriving it.
"""
from __future__ import annotations

import argparse
import os
import sys

from equity_scout.telegram_client import escape_html, load_telegram_config, send_message

MAX_QUOTE_LINES = 14


def freshness_lines(output: str) -> list[str]:
    """The per-ticker age lines of the 1-minute block — the numbers this whole check exists
    to produce. Falls back to an empty list if the format changed, in which case the caller
    still sends a message rather than silently nothing."""
    lines = output.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if "1-Minuten-Bars" in ln)
    except StopIteration:
        return []
    out = []
    for line in lines[start + 1:]:
        if not line.startswith("    "):
            break
        out.append(line.strip())
    return out


def build_message(*, passed: bool, output: str) -> str:
    """The Telegram body. HTML parse mode, so every interpolated part is escaped."""
    if passed:
        head = (
            "✅ <b>Alpaca-Frische-Test bestanden</b>\n"
            "Die Session-Lane kann auf Echtzeit umgebaut werden — "
            "Tasks 6–9 sind damit frei."
        )
    else:
        head = (
            "❌ <b>Alpaca-Frische-Test fehlgeschlagen</b>\n"
            "Der Umbau bleibt blockiert. Der Plan sieht dafür den Rückfall vor: "
            "gröbere Trigger-Auflösung statt 1 Minute."
        )
    detail = freshness_lines(output) or output.strip().splitlines()[-MAX_QUOTE_LINES:]
    quoted = escape_html("\n".join(detail[:MAX_QUOTE_LINES]))
    return f"{head}\n\n<pre>{quoted}</pre>"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", choices=("pass", "fail"), required=True)
    args = parser.parse_args()

    config = load_telegram_config(dict(os.environ))  # house idiom, cf. run_digest.py
    if config is None:
        print("Telegram nicht konfiguriert — keine Meldung gesendet.", file=sys.stderr)
        return 0  # not an error: the log still has everything

    send_message(
        config["token"],
        config["chat_id"],
        build_message(passed=args.status == "pass", output=sys.stdin.read()),
        parse_mode="HTML",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
