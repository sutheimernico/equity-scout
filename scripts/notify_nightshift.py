#!/usr/bin/env python
"""Schickt Nico die Kurzfassung der Nachtschicht plus den Link ins Cockpit.

    .venv/bin/python scripts/notify_nightshift.py --dry-run   # nur drucken
    .venv/bin/python scripts/notify_nightshift.py             # senden (stumm)

Stumm mit Absicht: die Nachricht entsteht nachts, während er schläft. Sie soll morgens
da sein, nicht klingeln.

Der Link trägt den `DASH_TOKEN` — dieselbe bewusste Abwägung wie im Copilot-Digest
(digest.py): ohne ihn landet ein Handy mit abgelaufenem Cookie auf einem 401, dafür liegt
der Token in der Telegram-Historie. Der Token steht darum auf Nicos Rotationsliste.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from equity_scout.buy_plan import stance_for  # noqa: E402
from equity_scout.radar_storage import load_latest_watchlist  # noqa: E402
from equity_scout.suggestion_storage import load_latest_review  # noqa: E402
from equity_scout.telegram_client import (  # noqa: E402
    escape_html,
    load_telegram_config,
    send_message,
)

DB_PATH = str(Path(__file__).resolve().parents[1] / "equity_scout.db")


def _link(dash_url: str | None, token: str | None, view: str, text: str) -> str:
    if not dash_url:
        return escape_html(text)
    target = f"{dash_url.rstrip('/')}/?view={view}"
    if token:
        target += f"&token={token}"
    return f'<b><a href="{escape_html(target)}">{escape_html(text)}</a></b>'


def build_message(
    *,
    watchlist: dict | None,
    review: dict | None,
    dash_url: str | None,
    dash_token: str | None,
) -> str:
    """Die Nachricht. Der Befund steht VOR dem Link — ein Link allein beantwortet nichts."""
    entries = (watchlist or {}).get("entries", [])
    ready = sum(
        1 for e in entries
        if stance_for(
            in_zone=e["in_zone"], price=e["price"],
            zone_low=e["entry_zone_low"], zone_high=e["entry_zone_high"],
        ) == "kaufbereit"
    )

    lines = ["<b>Nachtschicht am Autotrader</b>", ""]
    lines.append(
        "Neu: eine <b>Kaufplan-Ansicht</b> — pro Aktie Kauflimit, Tranchen, Kursziel, "
        "Stop, Geschäftsmodell, News und gemeldete Käufe auf einer Karte."
    )
    lines.append("")

    if entries:
        lines.append(
            f"📋 <b>{ready} von {len(entries)}</b> Titeln stehen im Stützbereich."
            + ("" if ready else " Heute also: nichts kaufen — das ist ein Befund, kein Fehler.")
        )

    if review is not None:
        for summary in review.get("summaries", []):
            if summary.get("source") == "rank" and summary.get("horizon_days") == 20:
                mean = summary.get("mean_excess_pct")
                n = summary.get("n_independent")
                if mean is not None:
                    lines.append(
                        f"📊 Bilanz der bisherigen Vorschläge: <b>{mean:+.1f} Prozentpunkte</b> "
                        f"gegen den Heimatindex über {n} unabhängige Fälle, 20 Handelstage. "
                        f"Statistisch nicht von Zufall zu unterscheiden."
                    )
                break

    lines.append("")
    lines.append(_link(dash_url, dash_token, "aktien", "→ Kaufplan öffnen"))
    lines.append(_link(dash_url, dash_token, "ergebnisse", "→ Ganze Auswertung"))
    lines.append("")
    lines.append(
        "<i>Zwei Sachen, die du wissen solltest: die Liste ist voll mit Titeln, die ein "
        "deutsches Depot kaum handelt (Indien, Hongkong) — die Karte markiert das jetzt. "
        "Und die deutschen Schlagzeilen sind maschinell übersetzt und erfinden gelegentlich "
        "etwas; das Original steht deshalb immer daneben.</i>"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text = build_message(
        watchlist=load_latest_watchlist(args.db),
        review=load_latest_review(args.db),
        dash_url=os.environ.get("DASH_URL"),
        dash_token=os.environ.get("DASH_TOKEN"),
    )
    if args.dry_run:
        print(text)
        return 0

    config = load_telegram_config(dict(os.environ))
    if config is None:
        print("Kein Telegram konfiguriert (COPILOT_TG_BOT_TOKEN / _CHAT_ID fehlen).")
        return 1
    message_id = send_message(
        config["token"], config["chat_id"], text, parse_mode="HTML", silent=True,
    )
    print(f"Gesendet (message_id={message_id}, stumm).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
