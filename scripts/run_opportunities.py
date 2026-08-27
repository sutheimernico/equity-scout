"""CLI: heutige Kaufpläne -> Chancen-Meldung aufs Handy (2026-08-27).

    uv run python scripts/run_opportunities.py [--db equity_scout.db] [--max 3]
        [--min-score 45] [--cooldown-days 7] [--no-llm] [--dry-run]

Der Job, den Nico morgens spüren soll: „ich will frühzeitig bei Möglichkeiten und Chancen
benachrichtigt werden, mit Zusammenfassungen von KI, warum ich jetzt das kaufen sollte."

Ablauf: Kaufpläne bauen (dieselbe Quelle wie die Kaufplan-Ansicht) -> auswählen, was die
Qualitätsschwelle schafft und außerhalb des Cooldowns liegt -> Laientext bauen (Regeln,
optional durchs lokale LLM geschliffen) -> speichern -> über alle Kanäle melden.

Zwei Dinge, die dieser Job bewusst NICHT tut:
- Er meldet nichts, wenn nichts qualifiziert. Eine tägliche Pflichtmeldung wäre in Wochen
  ohne Kandidaten eine Aufforderung, schlechte Titel zu kaufen (v8-Regel „kein Müll").
- Er ordnet nicht per Modell. Die Rangfolge kommt aus dem Score, damit sie erklärbar
  bleibt; das LLM formuliert nur.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from equity_scout.channels import Alert, deliver  # noqa: E402
from equity_scout.constants import DEFAULT_DB_PATH, SHORT_DISCLAIMER  # noqa: E402
from equity_scout.kaufplan_service import build_buy_plans  # noqa: E402
from equity_scout.opportunity import (  # noqa: E402
    COOLDOWN_DAYS,
    MAX_PER_RUN,
    MIN_SCORE,
    build_opportunity,
    polish,
    select_opportunities,
)
from equity_scout.opportunity_storage import (  # noqa: E402
    last_notified_at,
    record_opportunity,
)
from equity_scout.telegram_client import escape_html  # noqa: E402


def _llm_asker():  # noqa: ANN202
    """(prompt, system) -> Antworttext, über das lokale Ollama. None, wenn abgeschaltet."""
    from equity_scout.chat import ask_ollama

    def ask(prompt: str, system: str) -> str:
        # ask_ollama nimmt (Frage, Kontext) und klebt den Kontext an den System-Prompt —
        # genau die Trennung, die hier gebraucht wird: Regeln in den Kontext, Aufgabe in
        # die Frage.
        return ask_ollama(prompt, system)

    return ask


def build_telegram_html(opportunity: dict) -> str:
    """Die lange Fassung. Telegram bleibt der Kanal, auf dem der ganze Gedanke Platz hat."""
    lines = [
        f"💡 <b>{escape_html(opportunity['headline'])}</b>",
        "",
        escape_html(opportunity["verdict"] or ""),
        "",
        "<b>Warum jetzt</b>",
    ]
    lines += [f"• {escape_html(line)}" for line in opportunity["why_now"]]
    lines += [
        "",
        f"<b>Was dagegen spricht</b>\n{escape_html(opportunity['risk'])}",
        "",
        f"<b>Der Plan</b>\n{escape_html(opportunity['plan_line'] or '—')}",
    ]
    if opportunity.get("track_record"):
        lines += ["", f"<i>{escape_html(opportunity['track_record'])}</i>"]
    lines += ["", f"<i>{SHORT_DISCLAIMER}</i>"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--max", type=int, default=MAX_PER_RUN)
    parser.add_argument("--min-score", type=int, default=MIN_SCORE)
    parser.add_argument("--cooldown-days", type=int, default=COOLDOWN_DAYS)
    parser.add_argument("--no-llm", action="store_true", help="nur Regeltext, kein Ollama")
    parser.add_argument("--plan-limit", type=int, default=12,
                        help="wie viele Watchlist-Titel überhaupt geprüft werden")
    parser.add_argument("--dry-run", action="store_true",
                        help="bauen und ausgeben, aber nichts senden und nichts speichern")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = build_buy_plans(args.db, limit=args.plan_limit)
    plans = [plan.to_dict() for plan in result["plans"]]
    if not plans:
        print(f"Chancen: keine Kaufpläne — {result.get('note') or 'Watchlist leer'}.")
        return 0

    chosen = select_opportunities(
        plans,
        last_notified=lambda ticker: last_notified_at(args.db, ticker),
        today=now,
        min_score=args.min_score,
        cooldown_days=args.cooldown_days,
        max_count=args.max,
    )
    if not chosen:
        ready = sum(1 for p in plans if (p.get("entry") or {}).get("stance") == "kaufbereit")
        print(
            f"Chancen: nichts zu melden ({len(plans)} Pläne geprüft, {ready} kaufbereit, "
            f"keiner über Score {args.min_score} und außerhalb des {args.cooldown_days}-Tage-"
            "Fensters). Keine Meldung ist ehrlicher als eine schwache."
        )
        return 0

    ask = None if args.no_llm else _llm_asker()
    sent = 0
    for plan in chosen:
        opportunity = polish(build_opportunity(plan), ask=ask).to_dict()
        if args.dry_run:
            print(json.dumps(opportunity, ensure_ascii=False, indent=2))
            continue
        report = deliver(
            Alert(
                title=opportunity["headline"],
                body=opportunity["one_liner"],
                url=f"/?view=alarme&ticker={opportunity['ticker']}",
                # Ein Ticker = eine Zeile auf dem Sperrbildschirm, auch wenn er zweimal käme.
                tag=f"chance-{opportunity['ticker']}",
                emoji_tags=["bulb"],
                telegram_html=build_telegram_html(opportunity),
            ),
            db_path=args.db,
        )
        record_opportunity(args.db, opportunity, notified_at=now, channels=report)
        sent += 1
        print(
            f"Chance gemeldet: {opportunity['ticker']} "
            f"(Score {opportunity['score']}, Text {opportunity['explained_by']})"
        )
    if args.dry_run:
        print(f"Trockenlauf: {len(chosen)} Chancen gebaut, nichts gesendet.")
    else:
        print(f"Chancen: {sent} gemeldet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
