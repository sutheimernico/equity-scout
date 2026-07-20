"""Crypto lane (vision v11, lane `crypto`): Donchian breakout on real-time 15-minute bars.

Turtle-style, deliberately simple and fully stated: enter long when a completed bar CLOSES
above the highest high of the 20 completed bars before it; exit when a completed bar closes
below the lowest low of the prior 10 bars (channel exit) or at −2 % from entry (hard stop).
One position per pair, 25 % of book value each, long-only. Fills at the signal bar's close
plus slippage — with real-time data the just-closed bar's close IS the freshest observable
price, so unlike the equities session lane no delay model is needed. Benchmark honesty:
the lane races BTC buy-and-hold, not cash.

Pure decision logic; the runner owns Kraken I/O and the book.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from equity_scout.shortterm_book import LanePosition

ENTRY_LOOKBACK = 20
EXIT_LOOKBACK = 10
STOP_PCT = 0.02
ENTRY_FRACTION = 0.25


@dataclass(frozen=True)
class CryptoAction:
    kind: str  # "buy" | "sell"
    symbol: str
    price: float
    at: str  # ISO timestamp of the signal bar's START
    reason: str


def decide_pair(
    symbol: str,
    bars: pd.DataFrame,
    position: LanePosition | None,
    *,
    last_processed: str | None,
) -> tuple[CryptoAction | None, str | None]:
    """Judge the newest COMPLETED bar exactly once. Returns (action|None, new_marker);
    the marker is the judged bar's timestamp — feeding the same bars again is a no-op."""
    if bars.empty or len(bars) < ENTRY_LOOKBACK + 1:
        return None, last_processed
    signal_bar = bars.iloc[-1]
    signal_ts = bars.index[-1]
    if last_processed is not None and signal_ts <= pd.Timestamp(last_processed):
        return None, last_processed
    at = signal_ts.isoformat()
    close = float(signal_bar["close"])

    if position is None:
        entry_channel = float(bars["high"].iloc[-(ENTRY_LOOKBACK + 1):-1].max())
        if close > entry_channel:
            return (
                CryptoAction("buy", symbol, close, at,
                             f"Donchian-{ENTRY_LOOKBACK}-Ausbruch (> {entry_channel:,.2f})"),
                at,
            )
        return None, at

    exit_channel = float(bars["low"].iloc[-(EXIT_LOOKBACK + 1):-1].min())
    stop = position.entry_price * (1.0 - STOP_PCT)
    if close <= stop:
        return CryptoAction("sell", symbol, close, at, f"Stop -{STOP_PCT:.0%}"), at
    if close < exit_channel:
        return (
            CryptoAction("sell", symbol, close, at, f"Donchian-{EXIT_LOOKBACK}-Exit"),
            at,
        )
    return None, at
