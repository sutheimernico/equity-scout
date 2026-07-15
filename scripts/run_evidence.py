"""Evidence CLI: collect congress / 13F / news-theme / insider / voice / 8-K events
-> store -> ledger.

Usage:
    python scripts/run_evidence.py [--db equity_scout.db] [--universe data/universe_combined.csv]

Each collector degrades independently (CollectorResult status); one dead source never
kills the run. Only NEWLY inserted events are ledger-logged (predict-then-resolve,
horizon 60d) — a re-collected fact can never inflate the sample. The 13F, Form 4
insider and 8-K collectors all stay politely `unconfigured` without EDGAR_USER_AGENT
in the environment.

After the ledger step, watchlist news headlines + the 8-K events just collected are
also run through the deterministic beat/miss/guidance/earnings-filed classifier
(evidence/event_classifier.py) and stored in `classified_events`
(evidence/event_storage.py) with an honest published_at/seen_at pair (Strang B3) —
that table is separate from `evidence_events`/the ledger, and this script does not
itself measure latency (Strang B4).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH
from equity_scout.data.news import YFinanceNews
from equity_scout.evidence.base import STATUS_OK, CollectorResult
from equity_scout.evidence.congress import fetch_congress_trades
from equity_scout.evidence.edgar import collect_13f
from equity_scout.evidence.edgar_8k import collect_8k
from equity_scout.evidence.event_classifier import build_classified_events
from equity_scout.evidence.event_storage import save_classified_events
from equity_scout.evidence.form4 import collect_form4
from equity_scout.evidence.ledger import log_evidence
from equity_scout.evidence.news_themes import collect_news_themes
from equity_scout.evidence.storage import record_events
from equity_scout.evidence.voices import collect_voices
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.tracked_tickers import tracked_tickers
from equity_scout.universe import load_universe


def ledgerable_events(events: list) -> list:
    """Voice context mentions (`kind="context"`) and bearish voice calls
    (`kind="call_bearish"`) are stored and displayed but must never enter the
    predict-then-resolve ledger: a mention has no direction to resolve, and resolving a
    short call as a long would invert its meaning (evidence/voices.py docstring).
    Events without a `kind` (every other source) pass through unchanged."""
    return [e for e in events if e.details.get("kind") in (None, "call")]


def run_evidence(
    db_path: str,
    collectors: list[Callable[[], CollectorResult]],
    *,
    now: str,
) -> dict:
    """Run every collector, store its events, ledger-log the newly inserted ones.

    Returns per-source status lines plus the totals; statuses other than "ok" are
    reported, never raised — the caller (cron) must always reach the next source.
    """
    lines: list[str] = []
    new_total = 0
    ledgered_total = 0
    for collect in collectors:
        result = collect()
        new_events = record_events(db_path, result.events, now=now) if result.events else []
        ledgered = (
            log_evidence(db_path, ledgerable_events(new_events), now=now)
            if new_events
            else 0
        )
        new_total += len(new_events)
        ledgered_total += ledgered
        status_note = "" if result.status == STATUS_OK else f" [{result.status}]"
        lines.append(
            f"{result.source}{status_note}: {len(new_events)} neue Ereignisse"
            f" ({result.detail})"
        )
    return {"lines": lines, "new_events": new_total, "ledgered": ledgered_total}


def _watchlist_news(db_path: str) -> dict[str, list[dict]]:
    """Fresh yfinance headlines (title/publisher/published/link) per watchlist ticker —
    one fetch shared by the news-theme matcher and the beat/miss/guidance classifier
    (Strang B3), so neither hits yfinance twice for the same ticker.

    No watchlist -> {} (the theme radar still detects market-wide themes; it just
    cannot attach any to tickers, and there is nothing to classify)."""
    watchlist = load_latest_watchlist(db_path)
    if watchlist is None:
        return {}
    provider = YFinanceNews(limit=5)
    return {
        entry["ticker"]: provider.news_for(entry["ticker"])
        for entry in watchlist.get("entries", [])
    }


def _titles_only(news_by_ticker: dict[str, list[dict]]) -> dict[str, list[str]]:
    """The news-theme matcher only needs titles; the classifier needs the full items."""
    return {
        ticker: [item.get("title", "") for item in items]
        for ticker, items in news_by_ticker.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument(
        "--fast", action="store_true",
        help="intraday mode: only the fast sources (congress, news themes, voices,"
        " 8-K); 13F/Form 4 stay daily — filings do not change intraday and EDGAR"
        " etiquette forbids hammering it every 30 minutes",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    universe = [(i.ticker, i.name) for i in load_universe(args.universe)]
    news_by_ticker = _watchlist_news(args.db)
    ticker_headlines = _titles_only(news_by_ticker)
    # Same watchlist tickers _watchlist_news already loaded — Form 4 is a per-issuer
    # lookup, so it follows the watchlist's "actively tracked only" scope rather than
    # the full universe (see evidence/form4.py's module docstring).
    watchlist_tickers = list(ticker_headlines)
    # 8-K is per-issuer like Form 4, but scoped to the broader tracked-tickers union
    # (watchlist + main paper portfolio + both arena lanes, see tracked_tickers.py) —
    # positions already held deserve near-realtime disclosure evidence too, not just
    # watchlist candidates.
    eightk_tickers = sorted(tracked_tickers(args.db))
    # Called eagerly (once) so its events can also feed the beat/miss/guidance
    # classifier below without a second EDGAR round-trip; collect_8k never raises
    # (every failure degrades to a CollectorResult status), so this is as safe as the
    # lazy lambda it replaces.
    eightk_result = collect_8k(now=now, env=dict(os.environ), tickers=eightk_tickers)

    collectors: list[Callable[[], CollectorResult]] = [
        lambda: fetch_congress_trades(now=now),
        lambda: collect_news_themes(now=now, ticker_headlines=ticker_headlines),
        lambda: collect_voices(now=now, universe=universe),
        lambda: eightk_result,
    ]
    if not args.fast:
        collectors += [
            lambda: collect_13f(now=now, env=dict(os.environ), universe=universe),
            lambda: collect_form4(
                now=now, env=dict(os.environ), watchlist_tickers=watchlist_tickers
            ),
        ]
    result = run_evidence(args.db, collectors, now=now)
    for line in result["lines"]:
        print(line)
    print(
        f"Neu gespeichert: {result['new_events']} Ereignisse,"
        f" davon im Ledger: {result['ledgered']}."
    )

    # Strang B3: deterministic beat/miss/guidance classification of watchlist news
    # headlines + the 8-K events just collected above, with an honest published_at/
    # seen_at pair for later latency measurement (Strang B4 — not done here).
    classified = build_classified_events(
        news_by_ticker=news_by_ticker, eightk_events=eightk_result.events
    )
    new_classified = save_classified_events(args.db, classified, seen_at=now)
    print(f"Klassifizierte Events (Beat/Miss/Guidance): {len(new_classified)} neu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
