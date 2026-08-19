"""CLI: one pass of the market-wide news sweep (v16, layer 2).

Pulls Alpaca's news wire with NO symbol filter — that absence is the whole point. The
existing news path (`data/news.py`, `evidence/`) iterates over `tracked_tickers()`, which is
30-70 titles, and that is precisely why Moderna's Phase-3 readout never reached the system.
A feed without a ticker list cannot have a blind spot shaped like our watchlist.

Runs every minute, around the clock (the wire does not sleep, and overnight is when
approvals and merger agreements are published). Cursor-based: the sweep remembers the
newest article timestamp it has processed and re-reads a small overlap margin, so a missed
run catches up on the next pass instead of leaving a hole.

TRADES NOTHING. News signals are for SIGHT and for context. The ignition lane's entry
trigger is a verified PRICE move (layer 1), never a headline on its own — keyword rules
produce false positives (a CRO appointment read as a trial readout, seen 2026-08-19), and no
capital should move on an unconfirmed string match.

Usage:
    uv run python scripts/run_news_sweep.py [--catalyst-db catalysts.db]
        [--pages 4] [--dry-run] [--backfill-hours 6]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from equity_scout.alpaca_broker import auth_headers
from equity_scout.catalyst_news import (
    MIN_STRENGTH,
    build_news_signals,
    parse_wire,
)
from equity_scout.catalyst_storage import (
    DEFAULT_CATALYST_DB_PATH,
    get_state,
    init_catalyst_db,
    record_rejections,
    record_signals,
    set_state,
    stats,
)
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.state_storage import record_heartbeat

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
CURSOR_KEY = "news_sweep_cursor"
PAGE_LIMIT = 50
DEFAULT_PAGES = 4

# The cursor is rewound by this much on every run. The wire can publish an item with a
# created_at slightly behind one we have already read (multiple sources, clock skew), and the
# dedup key makes re-reading free — a gap, by contrast, is silent and permanent.
OVERLAP_MINUTES = 10


def fetch_wire(*, since: str, pages: int) -> list[dict]:
    """Wire items newer than `since`, oldest-first paging (network).

    Uses urllib rather than httpx to match the other keyless collectors in evidence/ — no
    new dependency for a plain GET.
    """
    articles: list[dict] = []
    token: str | None = None
    for _ in range(pages):
        params = {"limit": PAGE_LIMIT, "sort": "asc", "start": since}
        if token:
            params["page_token"] = token
        request = urllib.request.Request(
            f"{NEWS_URL}?{urllib.parse.urlencode(params)}", headers=auth_headers()
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
        page, token = parse_wire(payload)
        articles.extend(page)
        if not token:
            break
    return articles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalyst-db", default=DEFAULT_CATALYST_DB_PATH)
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="main DB — heartbeat only")
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    parser.add_argument("--min-strength", type=float, default=MIN_STRENGTH)
    parser.add_argument("--backfill-hours", type=float, default=None,
                        help="ignore the stored cursor and sweep this far back once")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    init_catalyst_db(args.catalyst_db)

    if args.backfill_hours is not None:
        since_dt = now - timedelta(hours=args.backfill_hours)
    else:
        cursor = get_state(args.catalyst_db, CURSOR_KEY)
        if cursor:
            since_dt = datetime.fromisoformat(cursor) - timedelta(minutes=OVERLAP_MINUTES)
        else:
            # First ever run: one hour, not one week. A cold start should not spend its first
            # pass paging through history it will re-read anyway on the next cadence.
            since_dt = now - timedelta(hours=1)
    since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        articles = fetch_wire(since=since, pages=args.pages)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"News-Wire nicht erreichbar: {exc}", file=sys.stderr)
        return 1

    signals, rejections = build_news_signals(
        articles, now=now, min_strength=args.min_strength,
    )
    print(f"{len(articles)} Meldungen seit {since} -> {len(signals)} Katalysator-Signale")
    for signal in signals[:15]:
        print(f"  {signal['ticker']:6s} {signal['score']:.2f}  {signal['detail'][:52]}  "
              f"| {(signal['headline'] or '')[:60]}")

    if args.dry_run:
        print("--dry-run: nichts geschrieben.")
        return 0

    written = record_signals(args.catalyst_db, signals)
    record_rejections(args.catalyst_db, rejections)

    # Advance the cursor only to the newest article we actually SAW. Using `now` would skip
    # anything published between the last page and this moment.
    newest = max((a["created_at"] for a in articles if a.get("created_at")), default=None)
    if newest:
        set_state(args.catalyst_db, CURSOR_KEY,
                  datetime.fromisoformat(newest.replace("Z", "+00:00")).isoformat())
    record_heartbeat(args.db, "news_sweep", now=now.isoformat(timespec="seconds"))

    print(f"{written} neue Signale gespeichert "
          f"({len(signals) - written} bereits bekannt).")
    if written:
        summary = stats(args.catalyst_db, since=now.date().isoformat())
        print(f"Heute: {summary['by_kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
