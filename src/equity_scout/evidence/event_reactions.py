"""Honest paper-reaction study for classified beat/miss/guidance events (Strang B4).

The plan's own honesty gate (docs/superpowers/plans/2026-07-15-vision-v7-target-exits-
events-learning.md:11-16) already ruled minute-level trading unmeasurable on free data.
B4 does not build a trading lane on top of that — it MEASURES whether our latency is
worth anything at all. For every classified event with a clear direction (beat/
guidance_up -> long, miss/guidance_down -> a hypothetical SHORT — never an actual
position; `lanes.py` stays long-only), this module computes the hypothetical
reaction return over 1d/5d trading days from daily closes, sign-adjusted for the
call, plus the seen_at-minus-published_at latency. `unknown`/`earnings_filed`/
`other_8k` carry no directional call and are never queued.

1h is a *structural* dead end, not a missing feature: no historical intraday price
series exists anywhere in this repo (a repo-wide grep for interval="1h" is empty,
see charts.py/entry.py/run_lanes.py, all daily-only), so it is never looked up and
never approximated by the daily close under a different name. `aggregate_reactions`
always reports it as `measurable: False` with the honest reason instead of a bare
NULL a reader would have to guess about.

The anchor (`_anchor`) is the last close that had ALREADY SETTLED at seen_at — a
close settles only after 16:00 ET on its trading day. An intraday seen_at anchors on
the PREVIOUS day's close, never today's still-unknown one (the look-ahead the naive
date-only version had). Documented limitation of daily data: when seen_at is intraday
on day X, the anchor is close(X-1) and the 1d window runs to close(X), so the part of
day X that moved BEFORE seen_at is included in the measurement. That is imprecise
attribution within the day, NOT look-ahead — close(X) is still a future price relative
to an intraday seen_at; free daily data simply cannot slice the anchor day finer.

Predict-then-resolve, mirroring `ml/prediction_ledger.py`: `queue_pending_reactions`
appends a `pending` row (INSERT OR IGNORE by event_key — idempotent, same re-run-safe
contract as `event_storage.save_classified_events`) the moment a classified event is
seen, with only the latency filled in (it needs no price data). `resolve_reaction`
performs the one permitted mutation — a guarded pending -> resolved transition, WHERE
status = 'pending', so a second attempt is refused and the first resolution stands.
Resolution only happens once the LONGER window (5d) is fully observable; a fresh event
whose 5d window hasn't elapsed yet stays pending with BOTH returns NULL — never
evaluated on an incomplete window, even if 1d alone would already be computable.
"""
from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from equity_scout.evidence.event_classifier import (
    EVENT_BEAT,
    EVENT_GUIDANCE_DOWN,
    EVENT_GUIDANCE_UP,
    EVENT_MISS,
)
from equity_scout.ml.entry_eval import forward_return

# Sign of the hypothetical paper reaction per directional event type. Any event_type
# not in this map (unknown/earnings_filed/other_8k) carries no call to react to.
REACTION_SIGN: dict[str, float] = {
    EVENT_BEAT: 1.0,
    EVENT_GUIDANCE_UP: 1.0,
    EVENT_MISS: -1.0,
    EVENT_GUIDANCE_DOWN: -1.0,
}

# Trading-day windows measurable from daily closes (module docstring). WINDOW_5D
# also gates resolution: a row is only ever resolved once THIS window is observable.
WINDOW_1D = 1
WINDOW_5D = 5

ONE_HOUR_NOT_MEASURABLE_REASON = (
    "no historical intraday price data available anywhere in this repo (free sources "
    "are daily-only) — never approximated by the daily close; see plan v7 B4"
)

# A US daily close is only KNOWN after the regular session closes at 16:00 America/
# New_York (DST-correct via zoneinfo). The anchor rule below compares real instants,
# not calendar dates, so an intraday seen_at never anchors on a close that had not
# settled yet (the look-ahead the naive .normalize() version had).
_MARKET_TZ = ZoneInfo("America/New_York")
_MARKET_CLOSE = time(16, 0)


def init_event_reactions_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS event_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                ticker TEXT NOT NULL,
                event_type TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                published_at TEXT,
                latency_minutes REAL,
                ret_1d REAL,
                ret_5d REAL,
                status TEXT NOT NULL
            )"""
        )


def _parse_dt(value: str) -> datetime | None:
    """ISO-8601 -> aware datetime, naive treated as UTC (news published_at is often
    date-only with no offset; seen_at always carries one). None on anything that does
    not parse, rather than guessing."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def latency_minutes(published_at: str | None, seen_at: str) -> float | None:
    """Minutes from the source's published_at to this tool's seen_at. None when the
    source gave no published_at (event_storage never backfills it — an unknown
    latency is honestly NULL, not zero) or either timestamp fails to parse."""
    if not published_at:
        return None
    published = _parse_dt(published_at)
    seen = _parse_dt(seen_at)
    if published is None or seen is None:
        return None
    return round((seen - published).total_seconds() / 60.0, 2)


def _settled_at(trading_day: pd.Timestamp) -> datetime:
    """The instant a trading day's daily close becomes KNOWN: 16:00 America/New_York
    on that calendar date (DST-correct — zoneinfo picks EDT vs EST by the date)."""
    return datetime.combine(trading_day.date(), _MARKET_CLOSE, tzinfo=_MARKET_TZ)


def _anchor(closes: pd.Series, seen_at: str) -> pd.Timestamp | None:
    """The last trading day whose daily close had ALREADY SETTLED at seen_at — i.e.
    whose 16:00-ET close instant is at or before seen_at. An INTRADAY seen_at (US
    market still open) therefore anchors on the PREVIOUS day's close, never today's
    still-unknown one; a post-close seen_at anchors on today's. No look-ahead.

    A tz-naive seen_at is read as UTC (the repo's existing convention, and the
    conservative one here: a UTC instant maps to an earlier ET wall-clock than the
    same digits read as ET would, so we never over-count a day as settled)."""
    seen = _parse_dt(seen_at)
    if seen is None:
        return None
    settled = [day for day in closes.index if _settled_at(day) <= seen]
    return settled[-1] if settled else None


def compute_reaction_returns(closes: pd.Series, seen_at: str, event_type: str) -> dict:
    """Hypothetical paper-reaction return over 1d/5d trading days from the close
    at/before seen_at, sign-adjusted for `event_type`'s direction. `closes` is one
    ticker's daily-close series (index = trading days); `seen_at` and `closes` are
    both injected, never read from the network or the wall clock here.

    status is one of:
      - "skipped":  event_type has no direction (unknown/earnings_filed/other_8k)
      - "pending":  directional, but the 5d window has not fully elapsed yet
      - "resolved": both ret_1d and ret_5d are filled
    """
    sign = REACTION_SIGN.get(event_type)
    if sign is None:
        return {"status": "skipped", "ret_1d": None, "ret_5d": None}

    series = closes.dropna()
    anchor = _anchor(series, seen_at) if len(series) else None
    if anchor is None:
        return {"status": "pending", "ret_1d": None, "ret_5d": None}

    raw_5d = forward_return(series, anchor, WINDOW_5D)
    if raw_5d is None:
        return {"status": "pending", "ret_1d": None, "ret_5d": None}
    raw_1d = forward_return(series, anchor, WINDOW_1D)
    return {
        "status": "resolved",
        "ret_1d": round(sign * raw_1d, 6) if raw_1d is not None else None,
        "ret_5d": round(sign * raw_5d, 6),
    }


def queue_pending_reactions(db_path: str | Path, events: list[dict]) -> list[dict]:
    """Queue one pending row per directional classified event (dicts shaped like
    `event_storage.load_classified_events` rows). Non-directional event types are
    silently skipped — they carry no call to react to. Idempotent by event_key
    (INSERT OR IGNORE); returns only the newly queued events."""
    init_event_reactions_db(db_path)
    inserted: list[dict] = []
    with sqlite3.connect(db_path) as con:
        for event in events:
            if event["event_type"] not in REACTION_SIGN:
                continue
            cursor = con.execute(
                "INSERT OR IGNORE INTO event_reactions"
                " (event_key, ticker, event_type, seen_at, published_at, latency_minutes, status)"
                " VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (
                    event["event_key"],
                    event["ticker"],
                    event["event_type"],
                    event["seen_at"],
                    event["published_at"],
                    latency_minutes(event["published_at"], event["seen_at"]),
                ),
            )
            if cursor.rowcount == 1:
                inserted.append(event)
    return inserted


_ROW_FIELDS = (
    "event_key", "ticker", "event_type", "seen_at", "published_at",
    "latency_minutes", "ret_1d", "ret_5d", "status",
)


def _row_to_dict(row: tuple) -> dict:
    return dict(zip(_ROW_FIELDS, row))


def pending_reactions(db_path: str | Path) -> list[dict]:
    """All rows still awaiting their 5d window — ready-to-resolve check happens in
    the caller (scripts/run_resolve_events.py), against real forward prices."""
    init_event_reactions_db(db_path)
    with sqlite3.connect(db_path) as con:
        rows = con.execute(
            f"SELECT {', '.join(_ROW_FIELDS)} FROM event_reactions"
            " WHERE status = 'pending' ORDER BY id"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def resolve_reaction(
    db_path: str | Path, event_key: str, *, ret_1d: float | None, ret_5d: float | None
) -> bool:
    """Fill the outcome of one pending reaction. Guarded WHERE status = 'pending', so
    a re-resolution finds no open row and is refused — the first resolution stands.
    No resolved_at here (unlike prediction_ledger.resolve_prediction): the table has
    no such column — the row's own event_key + seen_at already pin it in time, and a
    parameter this function silently dropped would be worse than not having it.
    Returns True iff the update was applied."""
    init_event_reactions_db(db_path)
    with sqlite3.connect(db_path) as con:
        cursor = con.execute(
            "UPDATE event_reactions SET ret_1d = ?, ret_5d = ?, status = 'resolved'"
            " WHERE event_key = ? AND status = 'pending'",
            (ret_1d, ret_5d, event_key),
        )
        return cursor.rowcount == 1


def resolved_reactions(db_path: str | Path, ticker: str | None = None) -> list[dict]:
    """Resolved rows, optionally filtered to one ticker — the aggregation's raw input."""
    init_event_reactions_db(db_path)
    query = f"SELECT {', '.join(_ROW_FIELDS)} FROM event_reactions WHERE status = 'resolved'"
    args: tuple = ()
    if ticker is not None:
        query += " AND ticker = ?"
        args = (ticker.upper(),)
    query += " ORDER BY id"
    with sqlite3.connect(db_path) as con:
        rows = con.execute(query, args).fetchall()
    return [_row_to_dict(r) for r in rows]


def _window_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean_return": None, "hit_rate": None}
    return {
        "n": len(values),
        "mean_return": round(statistics.mean(values), 6),
        "hit_rate": round(sum(1 for v in values if v > 0) / len(values), 4),
    }


def aggregate_reactions(db_path: str | Path) -> dict:
    """The honest answer to "is there anything to harvest on our latency": per
    event_type x window (1d/5d) the mean reaction return + hit rate (share of
    positive reaction returns) over RESOLVED rows only, plus the mean/median latency
    across every reaction with a known one. 1h is always reported as
    `measurable: False` with the reason — never a bare NULL (module docstring)."""
    init_event_reactions_db(db_path)
    with sqlite3.connect(db_path) as con:
        resolved_rows = con.execute(
            "SELECT event_type, ret_1d, ret_5d FROM event_reactions WHERE status = 'resolved'"
        ).fetchall()
        latencies = [
            r[0]
            for r in con.execute(
                "SELECT latency_minutes FROM event_reactions WHERE latency_minutes IS NOT NULL"
            ).fetchall()
        ]
        n_pending = con.execute(
            "SELECT COUNT(*) FROM event_reactions WHERE status = 'pending'"
        ).fetchone()[0]

    by_type: dict[str, dict[str, list[float]]] = {}
    for event_type, ret_1d, ret_5d in resolved_rows:
        bucket = by_type.setdefault(event_type, {"1d": [], "5d": []})
        if ret_1d is not None:
            bucket["1d"].append(ret_1d)
        if ret_5d is not None:
            bucket["5d"].append(ret_5d)

    by_event_type = {
        event_type: {window: _window_stats(values) for window, values in windows.items()}
        for event_type, windows in by_type.items()
    }

    return {
        "n_resolved": len(resolved_rows),
        "n_pending": int(n_pending),
        "by_event_type": by_event_type,
        "latency_minutes": {
            "n": len(latencies),
            "mean": round(statistics.mean(latencies), 2) if latencies else None,
            "median": round(statistics.median(latencies), 2) if latencies else None,
        },
        "1h": {"measurable": False, "reason": ONE_HOUR_NOT_MEASURABLE_REASON},
    }
