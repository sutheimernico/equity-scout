"""Rule-based entry reference levels + tranche plan for a single stock.

Pure math (sma/fib/swing-low/atr/compute_entry_plan) is network-free and unit-tested.
The yfinance fetch is isolated at the bottom (lazy import), mirroring data/yf_provider.py.

Framing: these are REFERENCE levels, not buy signals. No price prediction.
"""
from __future__ import annotations

import math


def _clean(values: list[float]) -> list[float]:
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]


def sma(closes: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` closes (or all, if fewer). None if empty."""
    clean = _clean(closes)
    if not clean:
        return None
    tail = clean[-window:]
    return sum(tail) / len(tail)


def fib_levels(high: float, low: float) -> dict[str, float]:
    """Fibonacci retracement levels measured down from the 52w high: high - range*ratio.
    0.618 is the classic 'prime entry' (capitulation) zone."""
    rng = high - low
    return {ratio: high - rng * float(ratio) for ratio in ("0.382", "0.5", "0.618")}


def recent_swing_low(closes: list[float], k: int = 5) -> float | None:
    """Most recent local minimum: a close strictly lower than the k closes on each side."""
    clean = _clean(closes)
    n = len(clean)
    for i in range(n - k - 1, k - 1, -1):
        window = clean[i - k : i + k + 1]
        if clean[i] == min(window) and window.count(clean[i]) == 1:
            return clean[i]
    return None


def _true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    trs: list[float] = []
    for i in range(1, len(closes)):
        prev_close = closes[i - 1]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close)))
    return trs


def atr(highs: list[float], lows: list[float], closes: list[float], window: int = 14) -> float | None:
    """Average True Range over the last `window` days. None if too little data."""
    if len(closes) < 2 or not (len(highs) == len(lows) == len(closes)):
        return None
    trs = _true_ranges(highs, lows, closes)
    if not trs:
        return None
    tail = trs[-window:]
    return sum(tail) / len(tail)
