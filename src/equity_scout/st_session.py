"""Intraday session lane (vision v11, lane `session`): Opening-Range-Breakout, flat by close.

Pure decision logic over settled 15-minute bars (see `intraday_bars` for the delay-honesty
gate). Per ticker and day: the first 30 minutes (2 bars) define the opening range; a settled
bar CLOSING above the range high signals a long, filled at the OPEN of the NEXT settled bar
(both already observed — no fill can use a price before it was knowable). Risk unit is the
range itself: stop = entry − 0.5×range, target = entry + 1×range, and any position still
open at the session's last bar is force-flattened at that bar's close — the lane NEVER
holds overnight. Fills are pessimistic: stops fill at min(stop, bar open), targets at the
target price, never better. One entry per ticker per day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from equity_scout.shortterm_book import LanePosition

OPENING_RANGE_BARS = 2  # 2 x 15 min = first 30 minutes
ENTRY_FRACTION = 0.15
STOP_RANGE_MULT = 0.5
TARGET_RANGE_MULT = 1.0
LAST_BAR_START = time(15, 45)  # ET start of the session's final 15-min bar


@dataclass(frozen=True)
class SessionAction:
    kind: str  # "buy" | "sell"
    ticker: str
    price: float
    at: str  # ISO timestamp of the bar the fill belongs to
    reason: str


def opening_range(bars: pd.DataFrame) -> tuple[float, float] | None:
    """(high, low) of the first 30 minutes; None until both bars are settled."""
    if len(bars) < OPENING_RANGE_BARS:
        return None
    head = bars.iloc[:OPENING_RANGE_BARS]
    return float(head["high"].max()), float(head["low"].min())


def _is_last_session_bar(ts: pd.Timestamp) -> bool:
    return ts.time() >= LAST_BAR_START


def decide(
    ticker: str,
    bars: pd.DataFrame,
    position: LanePosition | None,
    *,
    or_range: tuple[float, float],
    last_processed: str | None,
    traded_today: bool,
) -> tuple[list[SessionAction], str | None]:
    """Walk the settled bars after `last_processed` once, in order, and emit fills.

    Returns (actions, new_last_processed). The caller applies actions to the book and
    persists the marker — feeding the same bars again is then a no-op (idempotent runs).
    """
    or_high, or_low = or_range
    range_size = or_high - or_low
    actions: list[SessionAction] = []
    if range_size <= 0 or bars.empty:
        return actions, last_processed

    fresh = bars if last_processed is None else bars.loc[bars.index > pd.Timestamp(last_processed)]
    if fresh.empty:
        return actions, last_processed

    entry_price = position.entry_price if position else None
    holding = position is not None
    has_traded = traded_today

    # Skip the opening-range bars themselves for signals; they only define the range.
    signal_pending = False
    for ts, bar in fresh.iterrows():
        at = ts.isoformat()
        if holding and entry_price is not None:
            stop = entry_price - STOP_RANGE_MULT * range_size
            target = entry_price + TARGET_RANGE_MULT * range_size
            if float(bar["low"]) <= stop:
                fill = min(stop, float(bar["open"]))  # pessimistic: gap-through fills worse
                actions.append(SessionAction("sell", ticker, fill, at, "Stop (0.5x Range)"))
                holding = False
            elif float(bar["high"]) >= target:
                actions.append(SessionAction("sell", ticker, target, at, "Ziel (1x Range)"))
                holding = False
            elif _is_last_session_bar(ts):
                actions.append(
                    SessionAction("sell", ticker, float(bar["close"]), at, "Session-Ende (flat)")
                )
                holding = False
        elif signal_pending and not has_traded:
            # the breakout was signalled on the PREVIOUS settled bar -> fill at this open
            if not _is_last_session_bar(ts):  # no fresh entry into the closing bar
                entry_price = float(bar["open"])
                actions.append(SessionAction("buy", ticker, entry_price, at, "ORB-Ausbruch"))
                holding = True
                has_traded = True
                # pessimistic same-bar stop: an entry bar that itself trades through the
                # stop must not survive until the next bar's check
                stop = entry_price - STOP_RANGE_MULT * range_size
                if float(bar["low"]) <= stop:
                    fill = min(stop, entry_price)
                    actions.append(SessionAction("sell", ticker, fill, at, "Stop (0.5x Range)"))
                    holding = False
            signal_pending = False
        elif (
            not holding
            and not has_traded
            and bars.index.get_loc(ts) >= OPENING_RANGE_BARS
            and float(bar["close"]) > or_high
        ):
            signal_pending = True

    if signal_pending:
        # The breakout sits on the newest settled bar — leave that bar unprocessed so the
        # NEXT run (once the following bar settles) executes the fill at its open.
        prior = bars.index[bars.index < fresh.index[-1]]
        return actions, prior[-1].isoformat() if len(prior) else last_processed
    return actions, fresh.index[-1].isoformat()
