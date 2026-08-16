"""52-week-high lane (`highbreak`): buy a stock the day it prints a new yearly high.

George/Hwang's finding, in plain terms: how close a stock trades to its own 52-week high
predicts its next months better than how far it has run in absolute terms. The anchoring
story behind it is that sellers hesitate below a remembered high and capitulate above it.

The rule: enter at the close of the session whose close exceeds the highest close of the
prior `LOOKBACK_DAYS` sessions; exit on a trailing stop from the highest close since entry,
or after `MAX_HOLDING_DAYS`. Long-only, one position per ticker.

Deliberately CLOSE-based, not high-based: an intraday spike through the level that closes
back below it is not the anchoring event this rule is about, and a high-based trigger would
also make the entry unfillable at the price it was measured at.

The lookback EXCLUDES the signal session itself. Including it makes every new high trivially
its own maximum, and the rule would fire on any day that closes at the top of its own window
— a bug that reads as a very effective strategy in a backtest.

Pure decision logic; the runner owns data access and the book.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

LOOKBACK_DAYS = 252  # ~one trading year
TRAILING_STOP = 0.10  # give the trend room; the 52-week high rule is a multi-week idea
MAX_HOLDING_DAYS = 60


@dataclass(frozen=True)
class BreakAction:
    kind: str  # "buy" | "sell"
    ticker: str
    price: float
    at: str
    reason: str


def is_breakout(closes: pd.Series, *, lookback: int = LOOKBACK_DAYS) -> bool:
    """Does the LAST close exceed every close of the `lookback` sessions before it?"""
    closes = closes.dropna()
    if len(closes) < lookback + 1:
        return False
    window = closes.iloc[-(lookback + 1):-1]
    return float(closes.iloc[-1]) > float(window.max())


def decide(
    ticker: str,
    closes: pd.Series,
    *,
    entry_price: float | None,
    peak_since_entry: float | None,
    days_held: int,
) -> BreakAction | None:
    """One decision for the newest completed session. `entry_price=None` means flat."""
    closes = closes.dropna()
    if closes.empty:
        return None
    close = float(closes.iloc[-1])
    at = str(closes.index[-1])[:10]
    if entry_price is not None:
        peak = max(peak_since_entry or entry_price, close)
        if close <= peak * (1 - TRAILING_STOP):
            return BreakAction("sell", ticker, close, at, f"Trailing-Stop {TRAILING_STOP:.0%}")
        if days_held >= MAX_HOLDING_DAYS:
            return BreakAction("sell", ticker, close, at, f"Haltefrist {MAX_HOLDING_DAYS} Tage")
        return None
    if is_breakout(closes):
        return BreakAction("buy", ticker, close, at, "Neues 52-Wochen-Hoch")
    return None


def event_study(closes: pd.Series, *, horizon: int = 20, lookback: int = LOOKBACK_DAYS) -> dict:
    """Forward returns after a breakout against forward returns on every other session.

    This is the question the lane rests on — not "does the rule make money" (which depends on
    the exit and on costs), but "is the day after a new high different from any other day".
    """
    closes = closes.dropna()
    if len(closes) < lookback + horizon + 2:
        return {"n_events": 0, "n_other": 0}
    forward = closes.shift(-horizon) / closes - 1
    rolling_max = closes.shift(1).rolling(lookback).max()
    breakout = closes > rolling_max
    usable = forward.notna() & rolling_max.notna()
    events, others = forward[usable & breakout], forward[usable & ~breakout]
    return {
        "n_events": int(len(events)),
        "n_other": int(len(others)),
        "mean_event": float(events.mean()) if len(events) else None,
        "mean_other": float(others.mean()) if len(others) else None,
        "hit_event": float((events > 0).mean()) if len(events) else None,
        "hit_other": float((others > 0).mean()) if len(others) else None,
    }
