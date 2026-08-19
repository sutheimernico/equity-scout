"""Catalyst events as a matrix axis — the CONJUNCTION Nico asked for (v17, step 2).

Nico's brief (2026-08-17, verbatim): "hohe Volatilität und ein hoher Greed-Index, Kongressmitglied
hat gekauft und dann kommen noch News dazu". The matrix could measure the price half of that
sentence and nothing else: every axis in `signals.py` is derived from OHLCV. This module supplies
the missing half — WHEN something happened to the company — so a cell can state "the pattern pays
only in the window after a catalyst" instead of averaging that window away.

## Where the history comes from, and why that is the whole point

The live radar (`catalyst_storage`, v16) started writing on 2026-08-19. A matrix cell needs
hundreds of trades, so today's rows are worth nothing as evidence for years. The re-derivable
source is the local news archive (`data/news/news-*.csv.gz`, 262,953 wire items) run through the
SAME classifier the live sweep uses (`catalyst_news.classify_catalyst`). That turns a decade of
headlines into dated catalyst events, which is the only way this axis can be measured at all.

Three limits of that backfill, all consequences of re-deriving rather than recording:

1. **Only what the keyword rules catch.** Recall is unmeasured (stated in catalyst_news too); a
   catalyst phrased unusually is simply absent, and absence looks like "no catalyst", not like
   "unknown". Cells under a catalyst condition are therefore about *classified* catalysts.
2. **Wire time, not event time.** `created_at` is when Benzinga published, which already contains
   the publication delay. That delay is measured downstream (news-latency study), never hidden.
3. **No pre-event dimension.** The forward calendar (`kind='upcoming'`) exists only from
   2026-08-19 on, so "a known date is approaching" cannot be backtested yet and is deliberately
   NOT registered as an axis — an axis that can never hold is dead weight in a 7-million-row grid.

## The look-ahead rule, which is the only thing that makes this axis worth anything

An event is visible from the FIRST BAR whose label is at or after its timestamp. Bar labels are
left-edged (`timeframes.resample_bars`) and the grid enters at the bar's CLOSE, so a wire item
stamped inside a bar counts from the NEXT bar — never the one that was already trading. Ages are
built only from positions <= i by construction (running maximum), and
`test_catalyst_age_is_free_of_look_ahead` pins it by truncation, the same way the signal suite
does. This repo has paid for look-ahead once (the 15:57-intraday-as-close incident); news data is
where it is easiest to repeat, because the headline "explains" the move that preceded it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from equity_scout import db
from equity_scout.catalyst_news import (
    MAX_SYMBOLS_PER_ARTICLE,
    MIN_STRENGTH,
    classify_catalyst,
)
from equity_scout.catalyst_storage import SOURCE_NEWS, SOURCE_SCAN

EVENT_COLUMNS = ("seen_at", "ticker", "kind", "strength", "source")

# "Recently" in bars, matching the runner's GATE_WINDOW_BARS: a signal-as-condition counts for 10
# bars there, and a catalyst window that used a different number would make the two conditions
# incomparable. Bars, not wall-clock, on purpose — a catalyst window measured in minutes would
# interact with the slice axis, and then a plateau spanning 5min..1D could not be read as one
# claim. In bar units the slice axis itself reports the time scale the effect lives on.
WINDOW_BARS = 10

# Kind families. Grouped rather than one condition per kind because 16 kinds x the existing
# condition axis is a space the sample cannot fill: earnings_surprise alone carries 2,810 archive
# articles, index_event carries 2. Families keep every group above the floor while still
# separating claims that have nothing to do with each other economically.
#   hard        — the jump-makers: a deal, a regulator or a readout re-prices the company at once.
#   fundamental — the business result: the number moved, the outlook moved, an order landed.
#   any         — everything the classifier accepted, plus verified price ignitions from the live
#                 scanner (kind 'ignition_up'), which have no news class at all.
FAMILIES: dict[str, tuple[str, ...]] = {
    "any": (),
    "hard": ("merger_acquisition", "fda_decision", "trial_result", "bankruptcy_distress"),
    "fundamental": ("earnings_surprise", "guidance_change", "contract_award"),
}


def empty_events() -> pd.DataFrame:
    """An empty event frame with the right columns and a UTC stamp dtype.

    Returned instead of None wherever a source is missing, so callers never have to branch on
    "absent" versus "empty" — and an absent source can only ever mean "no catalyst", never
    "catalyst everywhere", which is the direction that would invent trades.
    """
    return pd.DataFrame({
        "seen_at": pd.Series(dtype="datetime64[ns, UTC]"),
        "ticker": pd.Series(dtype="object"),
        "kind": pd.Series(dtype="object"),
        "strength": pd.Series(dtype="float64"),
        "source": pd.Series(dtype="object"),
    })


def events_from_news_archive(
    news: pd.DataFrame,
    *,
    min_strength: float = MIN_STRENGTH,
    max_symbols: int = MAX_SYMBOLS_PER_ARTICLE,
) -> pd.DataFrame:
    """Classify a whole news archive into dated catalyst events, one row per (symbol, article).

    Mirrors the live sweep's filter chain (`catalyst_news.build_news_signals`) — same classifier,
    same strength floor, same roundup cut — with one deliberate difference: the event keeps the
    WIRE timestamp, while the live path stamps rows with the moment the sweep saw them. For a
    backtest the wire time is the only usable one; `now` would put every historical event on
    today.

    A multi-symbol article yields one event per symbol because both sides of an acquisition are
    catalysts, exactly as the live path does it.
    """
    if news is None or news.empty:
        return empty_events()
    rows: list[dict] = []
    for stamp, headline, symbols in zip(
        news["created_at"], news["headline"], news["symbols"], strict=False
    ):
        tickers = [s for s in str(symbols).split(",") if s]
        if not tickers or len(tickers) > max_symbols:
            continue  # no company attached, or a "10 stocks to watch" roundup
        classified = classify_catalyst(str(headline))
        if classified is None:
            continue
        kind, strength, _phrase = classified
        if strength < min_strength:
            continue
        for ticker in tickers:
            rows.append({
                "seen_at": stamp, "ticker": ticker.upper(), "kind": kind,
                "strength": strength, "source": SOURCE_NEWS,
            })
    if not rows:
        return empty_events()
    frame = pd.DataFrame(rows)
    frame["seen_at"] = pd.to_datetime(frame["seen_at"], utc=True, format="ISO8601")
    return frame.sort_values("seen_at").reset_index(drop=True)


def events_from_catalyst_db(
    db_path: str | Path,
    *,
    min_strength: float = 0.0,
    sources: tuple[str, ...] = (SOURCE_SCAN, SOURCE_NEWS),
) -> pd.DataFrame:
    """The live radar's signal book as events — the forward-looking half of the same axis.

    `calendar` rows are excluded by default: their `seen_at` is when we LEARNED that a date is
    coming, not when anything happened, so mixing them in would blend "something is announced for
    November" with "something just happened". They are a separate question (see the module
    docstring on the missing pre-event dimension).

    `strength` carries different meanings per source and that is kept visible via the `source`
    column: for news rows it is the class prior, for scan rows it is the ignition's quality score.
    Neither is a probability.
    """
    path = Path(db_path)
    if not path.exists():
        return empty_events()
    placeholders = ", ".join("?" for _ in sources)
    with db.connect(str(path)) as con:
        rows = con.execute(
            f"SELECT seen_at, ticker, kind, score, source FROM catalyst_signals "
            f"WHERE source IN ({placeholders}) AND score >= ? ORDER BY seen_at",
            (*sources, min_strength),
        ).fetchall()
    if not rows:
        return empty_events()
    frame = pd.DataFrame(rows, columns=["seen_at", "ticker", "kind", "strength", "source"])
    # The book stores both "…Z" and "…+00:00"; both are tz-aware, so one parse handles them.
    frame["seen_at"] = pd.to_datetime(frame["seen_at"], utc=True, format="ISO8601")
    frame["ticker"] = frame["ticker"].str.upper()
    return frame.sort_values("seen_at").reset_index(drop=True)


def merge_events(*frames: pd.DataFrame) -> pd.DataFrame:
    """Concatenate event sources and drop rows that describe the same event twice.

    The archive and the live book overlap from 2026-08-19 on (both classify the same wire), and a
    duplicated event would let one market reaction enter a cell twice — the inflation the
    no-pyramiding rule exists to prevent, arriving through the back door.
    """
    usable = [f for f in frames if f is not None and not f.empty]
    if not usable:
        return empty_events()
    merged = pd.concat(usable, ignore_index=True)
    merged = merged.drop_duplicates(subset=["seen_at", "ticker", "kind"])
    return merged.sort_values("seen_at").reset_index(drop=True)


def events_for_ticker(events: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
    """Exact-match subset for one instrument (the frame is already exploded per symbol)."""
    if events is None or events.empty:
        return empty_events()
    return events.loc[events["ticker"] == ticker.upper()]


def select_events(
    events: pd.DataFrame | None, *, family: str = "any", min_strength: float = 0.0
) -> pd.DataFrame:
    """Restrict events to a kind FAMILY and a strength floor. Unknown family raises."""
    if family not in FAMILIES:
        raise ValueError(f"unbekannte Katalysator-Familie: {family!r}")
    if events is None or events.empty:
        return empty_events()
    kinds = FAMILIES[family]
    selected = events if not kinds else events.loc[events["kind"].isin(kinds)]
    if min_strength > 0.0:
        selected = selected.loc[selected["strength"] >= min_strength]
    return selected


def catalyst_age_bars(bars: pd.DataFrame, events: pd.DataFrame | None) -> pd.Series:
    """Bars since the most recent catalyst that was already public — NaN where none was.

    Age 0 is the first bar that could have known: the earliest bar whose label is at or after the
    event stamp. `side="left"` therefore keeps an event stamped exactly on a bar label visible on
    that bar (its close is later), while an event stamped one second into a bar counts from the
    next one. Everything else would let a cell trade a move on the bar that produced it.

    NaN, not a large number, for "no catalyst yet": a sentinel like 9999 would silently satisfy
    every "older than" comparison a later caller might write.
    """
    if bars.empty:
        return pd.Series(dtype="float64", index=bars.index)
    if events is None or events.empty:
        return pd.Series(np.nan, index=bars.index, dtype="float64")
    stamps = pd.DatetimeIndex(pd.to_datetime(events["seen_at"], utc=True)).sort_values()
    positions = bars.index.searchsorted(stamps, side="left")
    n = len(bars)
    latest = np.full(n, -1, dtype=np.int64)
    inside = positions[positions < n]  # events after the last bar are simply not visible yet
    if len(inside):
        np.maximum.at(latest, inside, inside)
    latest = np.maximum.accumulate(latest)
    age = np.arange(n, dtype="float64") - latest
    age[latest < 0] = np.nan
    return pd.Series(age, index=bars.index)


def catalyst_window(
    bars: pd.DataFrame,
    events: pd.DataFrame | None,
    *,
    window_bars: int = WINDOW_BARS,
) -> pd.Series:
    """Boolean: a catalyst became public within the last `window_bars` bars (inclusive).

    Includes age 0 — the bar that first sees the headline — because the grid enters at that bar's
    close, which is a fill that was actually available. That differs from `recent_signal_gate`,
    which excludes its own bar on purpose: there the gate must PRECEDE the signal it conditions,
    while here the catalyst is the event under study.
    """
    age = catalyst_age_bars(bars, events)
    return ((age >= 0) & (age <= float(window_bars))).fillna(False)
