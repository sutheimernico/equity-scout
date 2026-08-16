"""Turn-of-month lane (`tom`): hold a broad index only around the month boundary.

The oldest calendar anomaly in the equity literature: returns cluster in the last few
sessions of a month and the first few of the next. This lane buys at the close of the third
to last business day of a month and sells at the close of the third business day of the next,
then sits in cash. Roughly twelve round trips a year, one instrument, long-only.

Why this one first (2026-08-16 plan): the arena's problem is not a shortage of ideas but the
time until a verdict — the intraday lane needs 236 more trades before its result means
anything. A rule that trades twelve times a year with a whole-index position produces few,
large observations instead of many small ones, and pays ~24 crossings of the spread a year
instead of hundreds.

NO LOOK-AHEAD: the entry and exit days are derived from the CALENDAR (business days), never
from the price panel. Counting "third to last trading day" backwards through the observed
sessions would require knowing that no further session follows — which on the day itself is
exactly what you do not know. Public holidays are deliberately not modelled, the same honest
limitation `market_hours` already documents: a holiday inside the window shifts the entry by
one session, which changes the timing slightly and the logic not at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ENTRY_OFFSET = 3  # buy at the close of the 3rd-to-last business day of the month
EXIT_OFFSET = 3  # sell at the close of the 3rd business day of the next month
TICKER = "SPY"


@dataclass(frozen=True)
class TomAction:
    kind: str  # "buy" | "sell"
    ticker: str
    price: float
    at: str  # ISO date of the signal session
    reason: str


def _business_days(year: int, month: int) -> list[pd.Timestamp]:
    start = pd.Timestamp(year=year, month=month, day=1)
    end = start + pd.offsets.MonthEnd(1)
    return list(pd.bdate_range(start, end))


def is_entry_day(day: pd.Timestamp) -> bool:
    """The 3rd-to-last business day of its month."""
    days = _business_days(day.year, day.month)
    return len(days) >= ENTRY_OFFSET and day.normalize() == days[-ENTRY_OFFSET].normalize()


def is_exit_day(day: pd.Timestamp) -> bool:
    """The 3rd business day of its month."""
    days = _business_days(day.year, day.month)
    return len(days) >= EXIT_OFFSET and day.normalize() == days[EXIT_OFFSET - 1].normalize()


def decide(day: pd.Timestamp, close: float, *, holding: bool) -> TomAction | None:
    """One decision per completed session. Exit is checked first: on a month with fewer than
    six business days the same date could satisfy both, and leaving a position open is the
    outcome that keeps risk on the book."""
    at = day.normalize().date().isoformat()
    if holding and is_exit_day(day):
        return TomAction("sell", TICKER, close, at, "Turn-of-Month-Fenster beendet")
    if not holding and is_entry_day(day):
        return TomAction("buy", TICKER, close, at, "Turn-of-Month-Fenster beginnt")
    return None


def backtest(closes: pd.Series, *, cost_bps: float = 10.0) -> dict:
    """Run the rule over a close series and report it against buy-and-hold.

    `cost_bps` is charged per side, so a round trip pays twice. Ten basis points is the floor
    `costs.py` applies to a liquid ETF — using the floor keeps the answer optimistic rather
    than flattering: if the rule cannot survive the floor, it cannot survive reality.
    """
    closes = closes.dropna().sort_index()
    if len(closes) < 2:
        return {"trades": 0, "strategy_return": None, "buy_and_hold": None}
    equity, holding, entry_price = 1.0, False, 0.0
    trades, wins, days_in_market = 0, 0, 0
    for day, close in closes.items():
        day = pd.Timestamp(day)
        if holding:
            days_in_market += 1
        action = decide(day, float(close), holding=holding)
        if action is None:
            continue
        if action.kind == "buy":
            holding, entry_price = True, float(close) * (1 + cost_bps / 10_000)
        else:
            gross = float(close) * (1 - cost_bps / 10_000) / entry_price
            equity *= gross
            trades += 1
            wins += 1 if gross > 1 else 0
            holding = False
    buy_and_hold = float(closes.iloc[-1] / closes.iloc[0]) - 1
    return {
        "trades": trades,
        "win_rate": wins / trades if trades else None,
        "strategy_return": equity - 1,
        "buy_and_hold": buy_and_hold,
        "days_in_market_share": days_in_market / len(closes),
        "first_day": str(closes.index[0])[:10],
        "last_day": str(closes.index[-1])[:10],
    }
