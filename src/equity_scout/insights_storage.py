"""SQLite persistence for the phone card's AI texts and its 1-year price series.

Same style as radar_storage.py: raw sqlite3, JSON snapshot columns, idempotent init
called from every entry point so a read never faces a table that does not exist yet.

TWO tables, deliberately not one: an insight is an interpretation with no natural
expiry (a company's business model does not change overnight), a price series is a fact
that is stale the next trading day. Separate `generated_at` / `as_of` stamps let the UI
label each honestly instead of inheriting one shared, wrong freshness.

`ticker` is the primary key in both: the newest text/series replaces the previous one.
Nobody wants the version history of a derived sentence, and both are cheap to regenerate.
"""
from __future__ import annotations

import json
import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH


def init_insights_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS stock_insights (
                ticker TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                business TEXT,
                news_summary TEXT,
                headlines TEXT NOT NULL DEFAULT '[]',
                model TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS price_series (
                ticker TEXT PRIMARY KEY,
                as_of TEXT NOT NULL,
                first_date TEXT NOT NULL,
                last_date TEXT NOT NULL,
                closes TEXT NOT NULL,
                dates TEXT
            )"""
        )
        # `dates` arrived with the chart's month axis (2026-08-05). Same PRAGMA + ALTER
        # idiom as radar_storage/storage: a row written before it keeps NULL and loads as
        # an empty list, so the chart draws without month ticks instead of crashing.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(price_series)")]
        if "dates" not in cols:
            conn.execute("ALTER TABLE price_series ADD COLUMN dates TEXT")


def save_insight(
    db_path: str,
    *,
    ticker: str,
    generated_at: str,
    business: str | None,
    news_summary: str | None,
    headlines: list[str],
    model: str | None,
) -> None:
    """Upsert one stock's AI texts. A None text is stored as SQL NULL, never "None"."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_insights"
            " (ticker, generated_at, business, news_summary, headlines, model)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET"
            "  generated_at=excluded.generated_at, business=excluded.business,"
            "  news_summary=excluded.news_summary, headlines=excluded.headlines,"
            "  model=excluded.model",
            (
                ticker, generated_at, business, news_summary,
                json.dumps(headlines, ensure_ascii=False), model,
            ),
        )


def save_price_series(
    db_path: str,
    *,
    ticker: str,
    as_of: str,
    first_date: str,
    last_date: str,
    closes: list[float],
    dates: list[str] | None = None,
) -> None:
    """Upsert one stock's downsampled 1-year close series.

    `dates` is one ISO day per close, so the chart can place month ticks on real trading
    days. Optional for callers that only have closes; the chart then omits the month axis.

    `allow_nan=False` is the load-bearing part: json's DEFAULT is to write NaN/Infinity as
    bare literals, which are not valid JSON. Such a row round-trips back as a float and
    then fails FastAPI's strict encoder with a 500 on the whole /api/briefs response — one
    bad ticker taking down every card, far from the cause (measured live 2026-08-05).
    Failing here instead makes the bad value the caller's problem, where it belongs.
    """
    init_insights_db(db_path)
    payload = json.dumps(closes, allow_nan=False)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO price_series"
            " (ticker, as_of, first_date, last_date, closes, dates)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET"
            "  as_of=excluded.as_of, first_date=excluded.first_date,"
            "  last_date=excluded.last_date, closes=excluded.closes,"
            "  dates=excluded.dates",
            (ticker, as_of, first_date, last_date, payload, json.dumps(dates or [])),
        )


def load_insights(db_path: str = DEFAULT_DB_PATH) -> dict[str, dict]:
    """Every stored insight keyed by ticker (the API joins this onto the watchlist)."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ticker, generated_at, business, news_summary, headlines, model"
            " FROM stock_insights"
        ).fetchall()
    return {
        row[0]: {
            "generated_at": row[1],
            "business": row[2],
            "news_summary": row[3],
            "headlines": json.loads(row[4] or "[]"),
            "model": row[5],
        }
        for row in rows
    }


def load_price_series(db_path: str = DEFAULT_DB_PATH) -> dict[str, dict]:
    """Every stored 1-year series keyed by ticker."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ticker, as_of, first_date, last_date, closes, dates FROM price_series"
        ).fetchall()
    return {
        row[0]: {
            "as_of": row[1],
            "first_date": row[2],
            "last_date": row[3],
            "closes": json.loads(row[4]),
            # NULL for rows written before the dates column: an empty list, so the chart
            # simply omits the month ticks.
            "dates": json.loads(row[5] or "[]"),
        }
        for row in rows
    }
