#!/usr/bin/env python3
"""Generate the phone cockpit's AI texts + 1-year price series for the top watchlist
stocks and cache them in SQLite.

Runs in the 18:00 chain, never in an HTTP request: a warm local LLM call costs ~5.6 s
and a cold one ~27 s (measured 2026-08-05), so /api/briefs only ever reads what this
script wrote. Every step degrades on its own — a dead news feed, a missing Ollama or a
rate-limited yfinance each store an honest null for that field and the run continues.

Scope: the top --limit stocks by briefs.rank_entries, i.e. exactly the rows the phone
card shows. Generating all 30 watchlist names would cost ~6 minutes of inference and 30
keyless RSS requests for cards nobody scrolls to.

No sys.path anchoring here (unlike run_notify.py): that dance is only needed for
`from scripts.<sibling> import ...`, and this script imports nothing but the installed
`equity_scout` package (editable install, see pyproject).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from equity_scout.briefs import rank_entries
from equity_scout.charts import fetch_year_closes
from equity_scout.chat import OLLAMA_MODEL, ChatError, ask_ollama
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.fundamentals import fetch_fundamentals_cached
from equity_scout.insights import (
    BUSINESS_MAX_CHARS,
    BUSINESS_QUESTION,
    NEWS_MAX_CHARS,
    NEWS_QUESTION,
    clean_llm_text,
    downsample_closes,
    fact_context,
    news_context,
)
from equity_scout.insights_storage import save_insight, save_price_series
from equity_scout.press import fetch_press_lines
from equity_scout.radar_storage import load_latest_watchlist

# Headlines per stock fed to the summariser. Five is enough for "what is going on here"
# and keeps the prompt short enough that a 7B model stays on topic.
_HEADLINE_LIMIT = 5


def _ask(question: str, context: str, *, max_chars: int) -> str | None:
    """One LLM call, cleaned. Any Ollama failure is a null, never an exception."""
    try:
        return clean_llm_text(ask_ollama(question, context), max_chars=max_chars)
    except ChatError as exc:
        print(f"    LLM nicht verfügbar: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--limit", type=int, default=12,
        help="how many top-ranked watchlist stocks to generate for (default 12)",
    )
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db)
    entries = rank_entries((watchlist or {}).get("entries", []))[: args.limit]
    if not entries:
        print("Keine Watchlist — nichts zu erzeugen. (Lief der Radar?)")
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"Erzeuge Steckbrief-Texte für {len(entries)} Titel (Modell {OLLAMA_MODEL})")

    for entry in entries:
        ticker, name = entry["ticker"], entry["name"]
        print(f"  {ticker} — {name}")

        # Sector/industry come from the same cached .info payload the card already uses,
        # so this costs no extra yfinance call on a warm cache.
        fundamentals = fetch_fundamentals_cached(ticker)
        business = _ask(
            BUSINESS_QUESTION,
            fact_context(
                ticker=ticker, name=name,
                sector=fundamentals.sector, industry=fundamentals.industry,
                price=entry["price"], currency=fundamentals.currency,
            ),
            max_chars=BUSINESS_MAX_CHARS,
        )

        # fetch_press_lines swallows its own failures and returns [] — a dead feed means
        # "no headlines", and no summary is generated for an empty list.
        headlines = fetch_press_lines(name, limit=_HEADLINE_LIMIT, width=140)
        news_summary = (
            _ask(NEWS_QUESTION, news_context(headlines), max_chars=NEWS_MAX_CHARS)
            if headlines
            else None
        )

        save_insight(
            args.db, ticker=ticker, generated_at=now, business=business,
            news_summary=news_summary, headlines=headlines, model=OLLAMA_MODEL,
        )

        try:
            dates, closes = fetch_year_closes(ticker)
            series = downsample_closes(dates, closes)
            save_price_series(
                args.db, ticker=ticker, as_of=now,
                first_date=series["first_date"], last_date=series["last_date"],
                closes=series["closes"],
            )
        except Exception as exc:  # noqa: BLE001 - yfinance is rate-limited and flaky
            print(f"    kein Kursverlauf: {type(exc).__name__}: {exc}", file=sys.stderr)

    print("Fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
