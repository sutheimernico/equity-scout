"""CLI: one pass of the catalyst radar's ignition scan (v16, layer 1).

Runs every minute inside the US market window. Four network calls per pass, regardless of
how many stocks exist: movers, most-actives, snapshots for the candidates, quotes for the
candidates. The asset list is fetched once per day and cached — it changes on
corporate-action timescales, not by the minute.

This script TRADES NOTHING. It sees, records and alerts. The ignition lane
(`run_shortterm.py --lane ignition`) is what acts on what this finds, and it is a separate
process on purpose: seeing must not depend on our willingness to trade, and an alert about
a move we deliberately skip is still worth having.

Usage:
    uv run python scripts/run_catalyst_scan.py [--catalyst-db catalysts.db]
        [--dry-run] [--no-alert] [--top 50] [--min-move 0.07]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from equity_scout.alpaca_screener import (
    AlpacaScreenerError,
    SCREENER_TOP,
    fetch_assets,
    fetch_most_actives,
    fetch_movers,
    fetch_quotes,
    fetch_snapshots,
)
from equity_scout.catalyst_scan import (
    MIN_MOVE,
    alertable,
    candidate_symbols,
    pick_ignitions,
)
from equity_scout.catalyst_storage import (
    DEFAULT_CATALYST_DB_PATH,
    init_catalyst_db,
    last_alert_at,
    load_signals,
    mark_alerted,
    record_rejections,
    record_signals,
    set_state,
    stats,
)
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.market_hours import within_market_window
from equity_scout.state_storage import record_heartbeat
from equity_scout.telegram_client import (
    TelegramError,
    escape_html,
    load_telegram_config,
    send_message,
)

ASSET_CACHE_PATH = Path(".state/alpaca_assets.json")
ALERT_MIN_SCORE = 0.45
ALERT_COOLDOWN_HOURS = 6.0


def load_asset_cache(*, today: str) -> dict[str, dict] | None:
    """Cached asset list if it was written today, else None.

    ~14k rows and 1.6 s per fetch. Re-fetching that every minute would be the single most
    wasteful thing in the whole radar.
    """
    if not ASSET_CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(ASSET_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("fetched_on") != today:
        return None
    return payload.get("assets") or None


def save_asset_cache(assets: dict[str, dict], *, today: str) -> None:
    ASSET_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSET_CACHE_PATH.write_text(json.dumps({"fetched_on": today, "assets": assets}))


def format_alert(signal: dict) -> str:
    direction = "springt" if signal["change_pct"] > 0 else "stürzt"
    return (
        f"🚨 <b>{escape_html(signal['ticker'])}</b> {direction} "
        f"<b>{signal['change_pct']:+.1%}</b>\n"
        f"{escape_html(signal['detail'])}\n"
        f"Kurs {signal['ref_price']:.2f} $ · Signalgüte {signal['score']:.2f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalyst-db", default=DEFAULT_CATALYST_DB_PATH)
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help="main DB — heartbeat only; the watchdog reads it there")
    parser.add_argument("--top", type=int, default=SCREENER_TOP)
    parser.add_argument("--min-move", type=float, default=MIN_MOVE)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be recorded, write nothing")
    parser.add_argument("--no-alert", action="store_true",
                        help="record signals but send no Telegram message")
    parser.add_argument("--force", action="store_true",
                        help="run outside the market window (for smoke tests)")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if not args.force and not within_market_window(now):
        return 0  # silent no-op: the cron fires more often than the market is open

    try:
        gainers, losers = fetch_movers(args.top)
        most_actives = fetch_most_actives(args.top)
        candidates = candidate_symbols(gainers, losers)
        if not candidates:
            print("Keine Kandidaten vom Screener — Markt still oder Endpunkt leer.")
            return 0
        snapshots = fetch_snapshots(candidates)
        quotes = fetch_quotes(candidates)
        today = now.date().isoformat()
        assets = load_asset_cache(today=today)
        if assets is None:
            assets = fetch_assets()
            if not args.dry_run:
                save_asset_cache(assets, today=today)
    except AlpacaScreenerError as exc:
        # Loud, not silent: a swallowed data error looks exactly like a quiet market, and a
        # radar that fails quietly is worse than no radar.
        print(f"Datenfehler im Katalysator-Scan: {exc}", file=sys.stderr)
        return 1

    signals, rejections = pick_ignitions(
        gainers, losers, most_actives, snapshots, quotes, assets,
        now=now, min_move=args.min_move,
    )

    print(f"{len(candidates)} Kandidaten geprüft -> {len(signals)} Signale, "
          f"{len(rejections)} abgelehnt")
    for signal in signals:
        print(f"  {signal['ticker']:6s} {signal['change_pct']:+7.1%} "
              f"vol {signal['volume_ratio']:5.1f}x  spread {signal['spread_bp']:6.0f}bp  "
              f"score {signal['score']:.2f}  {signal['detail'][:60]}")

    if args.dry_run:
        by_reason: dict[str, int] = {}
        for rej in rejections:
            by_reason[rej["reason"]] = by_reason.get(rej["reason"], 0) + 1
        print(f"Ablehnungsgründe: {by_reason}")
        print("--dry-run: nichts geschrieben.")
        return 0

    init_catalyst_db(args.catalyst_db)
    written = record_signals(args.catalyst_db, signals)
    record_rejections(args.catalyst_db, rejections)
    set_state(args.catalyst_db, "last_scan_at", now.isoformat(timespec="seconds"))
    # Heartbeat goes to the MAIN db: that is where run_watchdog.py looks for it.
    record_heartbeat(args.db, "catalyst_scan", now=now.isoformat(timespec="seconds"))
    print(f"{written} neue Signale gespeichert "
          f"({len(signals) - written} bereits bekannt).")

    if args.no_alert or not written:
        return 0

    fresh = [s for s in load_signals(args.catalyst_db, since=now.date().isoformat(),
                                     unalerted_only=True)
             if s["dedup_key"] in {sig["dedup_key"] for sig in signals}]
    last_by_ticker = {s["ticker"]: last_alert_at(args.catalyst_db, s["ticker"])
                      for s in fresh}
    to_alert = alertable(
        fresh, {k: v for k, v in last_by_ticker.items() if v},
        now=now, min_score=ALERT_MIN_SCORE, cooldown_hours=ALERT_COOLDOWN_HOURS,
    )
    if not to_alert:
        return 0

    config = load_telegram_config(dict(os.environ))
    if config is None:
        print("Telegram nicht konfiguriert — Signale gespeichert, kein Push.")
        return 0
    sent_ids: list[int] = []
    for signal in to_alert:
        try:
            send_message(config["token"], config["intraday_chat_id"],
                         format_alert(signal), parse_mode="HTML")
            sent_ids.append(signal["id"])
        except TelegramError as exc:
            # The signal stays unalerted so the next pass retries it — the book is the
            # source of truth, the push is best-effort.
            print(f"Telegram-Fehler für {signal['ticker']}: {exc}", file=sys.stderr)
    mark_alerted(args.catalyst_db, sent_ids, now=now.isoformat(timespec="seconds"))
    print(f"{len(sent_ids)} Alarme gesendet.")

    summary = stats(args.catalyst_db, since=now.date().isoformat())
    print(f"Heute: {summary['total']} Signale, Quellen {summary['by_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
