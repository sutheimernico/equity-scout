"""Rule-based entry reference levels + tranche plan for a single stock.

Pure math (sma/fib/swing-low/atr/compute_entry_plan) is network-free and unit-tested.
The yfinance fetch is isolated at the bottom (lazy import), mirroring data/yf_provider.py.

Framing: these are REFERENCE levels, not buy signals. No price prediction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


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
    """Average True Range over the last `window` days. None if too little valid data.

    Cleans row-wise (drops any day with a non-finite/non-positive H/L/C) so the three
    series stay index-aligned — yfinance occasionally returns NaN/0 rows."""
    if not (len(highs) == len(lows) == len(closes)):
        return None
    rows = [
        (h, low, c)
        for h, low, c in zip(highs, lows, closes)
        if all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in (h, low, c))
    ]
    if len(rows) < 2:
        return None
    h = [r[0] for r in rows]
    low_s = [r[1] for r in rows]
    c = [r[2] for r in rows]
    trs = _true_ranges(h, low_s, c)
    if not trs:
        return None
    tail = trs[-window:]
    return sum(tail) / len(tail)


@dataclass(frozen=True)
class EntryLevel:
    label: str          # "200-Tage-Schnitt", "Fib 61.8 %", "Jüngstes Tief", "−1 ATR"
    price: float
    kind: str           # "anchor" | "support" | "volatility"
    note: str


@dataclass(frozen=True)
class Tranche:
    label: str                      # "Tranche 1", "Jetzt", "bei −7 %"
    fraction: float                 # share of capital in [0,1]
    trigger_price: float | None     # None = time-based (DCA); else the price that arms it


@dataclass(frozen=True)
class EntryPlan:
    ticker: str
    price: float
    sma200: float | None
    high_52w: float
    low_52w: float
    drawdown_from_high: float       # negative fraction, e.g. -0.20
    atr: float | None
    levels: list[EntryLevel]
    dca_tranches: list[Tranche]
    dip_tranches: list[Tranche]
    near_reference: bool            # neutral: price is at/below the reference zone — NOT a buy signal
    reference_note: str


_FIB_LABEL = {"0.382": "Fib 38.2 %", "0.5": "Fib 50 %", "0.618": "Fib 61.8 %"}


def compute_entry_plan(
    ticker: str, closes: list[float], highs: list[float], lows: list[float]
) -> EntryPlan:
    """Build the full reference-level + tranche plan from 1y of daily OHLC closes."""
    clean = _clean(closes)
    if len(clean) < 2:
        raise ValueError("compute_entry_plan needs at least 2 valid closes")
    price = clean[-1]
    clean_highs = _clean(highs)
    clean_lows = _clean(lows)
    high_52w = max(clean_highs) if clean_highs else price
    low_52w = min(clean_lows) if clean_lows else price
    sma200 = sma(closes, window=200)
    _atr_window = 14
    # Guard on len(clean): yfinance gaps drop whole OHLC rows together, so the cleaned-close
    # count tracks the cleaned-row count atr() uses. (A thin ATR from selectively-missing H/L
    # is not a real yfinance failure mode.)
    atr_val = atr(highs, lows, closes, window=_atr_window) if len(clean) > _atr_window else None
    drawdown = price / high_52w - 1.0 if high_52w > 0 else 0.0
    fibs = fib_levels(high_52w, low_52w)
    swing = recent_swing_low(closes, k=5)

    levels: list[EntryLevel] = []
    if sma200 is not None:
        rel = price / sma200 - 1.0
        levels.append(EntryLevel(
            "200-Tage-Schnitt", round(sma200, 2), "anchor",
            f"Langfrist-Anker. Preis liegt {rel * 100:+.1f} % dazu.",
        ))
    for ratio, lvl in fibs.items():
        levels.append(EntryLevel(
            _FIB_LABEL[ratio], round(lvl, 2), "support",
            "Retracement vom 52-Wochen-Hoch zum -Tief." if ratio == "0.618"
            else "Fibonacci-Retracement-Level.",
        ))
    if swing is not None:
        levels.append(EntryLevel(
            "Jüngstes Tief", round(swing, 2), "support", "Letztes lokales Kurstief (Support)."
        ))
    if atr_val:  # truthy: skip both when ATR is None or a meaningless 0.0 (flat price)
        levels.append(EntryLevel(
            "−1 ATR", round(price - atr_val, 2), "volatility",
            "Eine durchschnittliche Tagesschwankung unter dem Kurs.",
        ))
        levels.append(EntryLevel(
            "−2 ATR", round(price - 2 * atr_val, 2), "volatility",
            "Zwei Tagesschwankungen unter dem Kurs (tiefere Pullback-Zone).",
        ))

    # Baseline: 4 equal, time-staggered DCA tranches (no price trigger).
    dca = [Tranche(f"Tranche {i + 1}", 0.25, None) for i in range(4)]

    # Option: scale in on drawdown. Thirds at now / -7 % / -15 % relative to the current price.
    dip = [
        Tranche("Jetzt", 1 / 3, round(price, 2)),
        Tranche("bei −7 %", 1 / 3, round(price * 0.93, 2)),
        Tranche("bei −15 %", 1 / 3, round(price * 0.85, 2)),
    ]

    # Neutral "reference zone" flag — confluence of below-fair-value AND near a support level.
    near_support = (swing is not None and price <= swing * 1.05) or price <= fibs["0.618"] * 1.02
    below_anchor = sma200 is not None and price <= sma200
    # Deliberate: both conditions required. With no SMA (short history) near_reference is False
    # by design — we don't flag a "reference zone" without the long-term anchor.
    near_reference = bool(below_anchor and near_support)
    if near_reference:
        note = "Kurs unter dem 200-Tage-Schnitt und nahe einem Support — eine der Referenzzonen."
    elif below_anchor:
        note = "Kurs unter dem 200-Tage-Schnitt, aber über den Support-Levels."
    else:
        note = "Kurs über dem 200-Tage-Schnitt — keine der Referenzzonen erreicht."

    return EntryPlan(
        ticker=ticker, price=round(price, 2), sma200=round(sma200, 2) if sma200 else None,
        high_52w=round(high_52w, 2), low_52w=round(low_52w, 2),
        drawdown_from_high=round(drawdown, 4), atr=round(atr_val, 2) if atr_val else None,
        levels=levels, dca_tranches=dca, dip_tranches=dip,
        near_reference=near_reference, reference_note=note,
    )
