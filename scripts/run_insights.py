#!/usr/bin/env python3
"""Generate the phone cockpit's AI texts + 1-year price series for the top watchlist
stocks and cache them in SQLite.

Runs LAST in the daily chain, never in an HTTP request: /api/briefs only ever reads what
this script wrote. Every step degrades on its own — a dead news feed, a missing Ollama or
a rate-limited yfinance each store an honest null for that field and the run continues.

Scope, measured 2026-08-11 (the docstring used to under-report both numbers): `--limit`
caps the WATCHLIST head only; every screener pick that is not already in it is appended
UNCAPPED, so `--limit 12` really processed 30 titles. Each title costs up to THREE LLM
calls — business, news summary, headline translation — not two. Real cost is **~90 s per
title**, so a 30-title run needs ~45 min, which is why this step runs last and carries a
wider cap than the rest of the chain.

Titles are processed oldest-text-first (`order_by_staleness`): a run stopped by its cap
renews what waited longest instead of the same head of the ranking every day. Nothing is
lost when a run is cut short — `save_insight` upserts, so the previous text stands until
its title comes round again.

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
    HEADLINES_QUESTION,
    NEWS_MAX_CHARS,
    NEWS_QUESTION,
    clean_llm_text,
    downsample_closes,
    fact_context,
    news_context,
    order_by_staleness,
    split_bullets,
)
from equity_scout.insights_storage import load_insights, save_insight, save_price_series
from equity_scout.press import fetch_press_lines
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.storage import load_latest_run

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
        help="how many top-ranked WATCHLIST stocks to include (default 12). Screener picks "
             "are appended on top of this, so the real title count is higher — the run "
             "prints it.",
    )
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db)
    entries = rank_entries((watchlist or {}).get("entries", []))[: args.limit]

    # The screener's top picks ride along (Nico 2026-08-07: the Screener cards need the
    # same summarised news and own chart as the Heute list). Dedupe against the watchlist
    # — the two sets overlap heavily, so this usually adds well under 30 LLM rounds.
    items: list[dict] = [
        {"ticker": e["ticker"], "name": e["name"], "price": e["price"]} for e in entries
    ]
    seen = {item["ticker"] for item in items}
    run = load_latest_run(args.db)
    for picks in (run.buckets if run is not None else {}).values():
        for pick in picks:
            instrument = pick.instrument
            if instrument.ticker in seen:
                continue
            seen.add(instrument.ticker)
            # No price on a run pick — the business context simply omits the price line.
            items.append({"ticker": instrument.ticker, "name": instrument.name, "price": None})

    if not items:
        print("Keine Watchlist und kein Screener-Lauf — nichts zu erzeugen.")
        return 0

    # Oldest text first. At ~90 s per title this run is routinely stopped by the chain's
    # step cap, and a fixed order meant the tail was never reached at all.
    stored = load_insights(args.db)
    items = order_by_staleness(items, {t: row["generated_at"] for t, row in stored.items()})

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"Erzeuge Steckbrief-Texte für {len(items)} Titel (Modell {OLLAMA_MODEL})")
    print(f"  älteste zuerst; {sum(1 for i in items if i['ticker'] not in stored)} ohne Text")

    for entry in items:
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

        # One short German line per headline. The English wire titles stay stored as the
        # source of record, but the card shows these — "Yamato Holdings Stock Faces Profit
        # Strain Behind A Premium P E" is not something to read on a phone at breakfast.
        headlines_de: list[str] = []
        if headlines:
            try:
                raw = ask_ollama(HEADLINES_QUESTION, news_context(headlines))
                headlines_de = split_bullets(raw, len(headlines))
            except ChatError as exc:
                print(f"    Schlagzeilen nicht übersetzt: {exc}", file=sys.stderr)

        save_insight(
            args.db, ticker=ticker, generated_at=now, business=business,
            news_summary=news_summary, headlines=headlines, model=OLLAMA_MODEL,
            headlines_de=headlines_de,
        )

        try:
            dates, closes = fetch_year_closes(ticker)
            series = downsample_closes(dates, closes)
            save_price_series(
                args.db, ticker=ticker, as_of=now,
                first_date=series["first_date"], last_date=series["last_date"],
                closes=series["closes"], dates=series["dates"],
            )
        except Exception as exc:  # noqa: BLE001 - yfinance is rate-limited and flaky
            print(f"    kein Kursverlauf: {type(exc).__name__}: {exc}", file=sys.stderr)

    print("Fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
