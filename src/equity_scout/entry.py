"""Rule-based entry reference levels + tranche plan for a single stock.

Pure math (sma/fib/swing-low/atr/compute_entry_plan) is network-free and unit-tested.
The yfinance fetch is isolated at the bottom (lazy import), mirroring data/yf_provider.py.

Framing: these are REFERENCE levels, not buy signals. No price prediction.

`compute_target_stop` is a different kind of number: a deterministic, model-derived price
target/stop from the `entry_tb` champion's own vol-scaled barrier config — not a rule-based
reference level and not an LLM guess (see `pitch.py`'s guardrail against LLM price targets), but
still an honest computation with an explicit gap (None) when the champion or its history is
missing, never a fallback default.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from equity_scout.ml.labeling import trailing_daily_vol


def clean_prices(values: list[float]) -> list[float]:
    """Drop non-finite/non-positive values (inf/nan/0 from a bad feed row)."""
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]


def sma(closes: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` closes (or all, if fewer). None if empty."""
    clean = clean_prices(closes)
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
    clean = clean_prices(closes)
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


_FIB_LABEL = {"0.382": "Fibonacci 38.2 %", "0.5": "Fibonacci 50 %", "0.618": "Fibonacci 61.8 %"}


def dca_tranche_plan() -> list[Tranche]:
    """Baseline: 4 equal, time-staggered tranches (no price trigger)."""
    return [Tranche(f"Tranche {i + 1}", 0.25, None) for i in range(4)]


def dip_tranche_plan(price: float) -> list[Tranche]:
    """Scale in on drawdown: thirds at now / -7 % / -15 % of the current price.

    Extracted from compute_entry_plan (2026-08-27) so the buy-plan surface can offer the
    SAME ladder without a 1y OHLC fetch. Retyping these three levels next to a price the
    user is about to trade on is exactly the class of duplication that put three dead
    branches into people.ts.
    """
    return [
        Tranche("Jetzt", 1 / 3, round(price, 2)),
        Tranche("bei −7 %", 1 / 3, round(price * 0.93, 2)),
        Tranche("bei −15 %", 1 / 3, round(price * 0.85, 2)),
    ]


def compute_entry_plan(
    ticker: str, closes: list[float], highs: list[float], lows: list[float]
) -> EntryPlan:
    """Build the full reference-level + tranche plan from 1y of daily OHLC closes."""
    clean = clean_prices(closes)
    if len(clean) < 2:
        raise ValueError("compute_entry_plan needs at least 2 valid closes")
    price = clean[-1]
    clean_highs = clean_prices(highs)
    clean_lows = clean_prices(lows)
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

    dca = dca_tranche_plan()
    dip = dip_tranche_plan(price)

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


def compute_target_stop(closes: list[float], barrier_config: dict) -> dict | None:
    """Model-derived price target + stop, from the `entry_tb` champion's OWN vol-scaled barrier
    config (`ml.labeling.BarrierConfig.as_dict()`): `target = price * (1 + k_pt * sigma)`,
    `stop = price * (1 - k_sl * sigma)`, with `sigma` the ticker's OWN trailing daily-return
    volatility over `vol_window` trailing days. Reuses `trailing_daily_vol` (the exact function the
    training label is built from, `ml.entry_eval.triple_barrier_entry_label`) so the live number can
    never drift from what the champion was actually trained on.

    `price` is the last CLEAN close (mirrors `compute_entry_plan`), `sigma` is read as of that same
    last date — the live equivalent of "at" in the training label.

    None (an honest gap, never a guessed default) when there is not yet a full `vol_window` of
    trailing daily returns to compute sigma from (fewer than `vol_window + 1` clean closes), or
    sigma is degenerate (zero/non-finite, e.g. a flat price series)."""
    clean = clean_prices(closes)
    vol_window = int(barrier_config["vol_window"])
    if len(clean) < vol_window + 1:
        return None
    sigma_series = trailing_daily_vol(pd.Series(clean), window=vol_window)
    sigma = float(sigma_series.iloc[-1])
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    price = clean[-1]
    k_pt = float(barrier_config["k_pt"])
    k_sl = float(barrier_config["k_sl"])
    return {
        "target": round(price * (1 + k_pt * sigma), 2),
        "stop": round(price * (1 - k_sl * sigma), 2),
        "sigma": round(sigma, 6),
        "horizon_days": int(barrier_config["horizon_days"]),
    }


# Fallback barrier when no entry_tb champion is registered yet: 2.0σ target vs 1.5σ stop
# over a 20-day window — a 1.33 reward/risk floor, deliberately conservative. Uses the exact
# vol-scaled formula the champion path uses, so a later champion changes the numbers but
# never their meaning.
HEURISTIC_BARRIER_V1 = {"k_pt": 2.0, "k_sl": 1.5, "vol_window": 20, "horizon_days": 20}


def resolve_target_stop(closes: list[float], barrier_config: dict | None) -> dict | None:
    """Target/stop for the UI, tagged with its provenance: the entry_tb champion's own
    barrier config when one exists (``source="model"``), otherwise ``HEURISTIC_BARRIER_V1``
    (``source="heuristic_v1"``) so the Scout-Ziel is populated until a champion is promoted.
    The heuristic also rescues a champion whose ``vol_window`` exceeds the available history.
    None only when even the heuristic's 20-day window cannot be computed (short history or
    degenerate sigma)."""
    if barrier_config:
        result = compute_target_stop(closes, barrier_config)
        if result is not None:
            return {**result, "source": "model"}
    result = compute_target_stop(closes, HEURISTIC_BARRIER_V1)
    if result is not None:
        return {**result, "source": "heuristic_v1"}
    return None


def fetch_entry_history(ticker: str) -> tuple[list[float], list[float], list[float]]:
    """Fetch 1y of daily Close/High/Low for `ticker`. Lazy yfinance import + retry, like
    YFinanceProvider.fetch_quote. Returns ([], [], []) on persistent failure (caller handles)."""
    import yfinance as yf

    from equity_scout.data.fetch import with_retry

    def _hist() -> tuple[list[float], list[float], list[float]]:
        h = yf.Ticker(ticker).history(period="1y", interval="1d")
        if h.empty or not {"Close", "High", "Low"}.issubset(h.columns):
            return [], [], []
        df = h[["Close", "High", "Low"]].dropna()  # drop rows where any of O/H/L is NaN -> aligned, equal-length
        if df.empty:
            return [], [], []
        return (
            [float(c) for c in df["Close"].tolist()],
            [float(c) for c in df["High"].tolist()],
            [float(c) for c in df["Low"].tolist()],
        )

    try:
        return with_retry(_hist, attempts=3)
    except Exception:
        return [], [], []
