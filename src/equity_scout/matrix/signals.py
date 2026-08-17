"""Signal detectors for the matrix — one pure function per pattern.

Contract every detector honours: it returns a boolean Series aligned to `bars`, and the flag at
row i uses ONLY rows <= i. `test_no_detector_looks_into_the_future` pins that by truncating the
frame and demanding identical earlier flags. Without that guarantee a whole matrix is worthless,
and look-ahead has bitten this repo before (the 15:57-intraday-as-close incident).

Threshold axes are tuples, not single values, because the unit of evidence is a PLATEAU: a rule
that works at exactly one threshold and fails at its neighbours is noise. Every axis therefore
has at least four points.

Two of these seven have never been measured in this repo before (verified 2026-08-17 — no
occurrence of hammer/engulfing/doji anywhere): `hammer` and `bullish_engulfing`, the candlestick
family Nico asked about. The others re-measure rules that were only ever tested on a single
time slice, which is the whole point of putting a slice axis on them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

VOLUME_LOOKBACK = 20  # bars for the trailing median in volume_spike
TREND_LOOKBACK = 20  # bars for the breakout high in breakout_high


@dataclass(frozen=True)
class SignalSpec:
    detect: Callable[..., pd.Series]
    thresholds: tuple[float, ...]
    description: str


def _body(bars: pd.DataFrame) -> pd.Series:
    return (bars["close"] - bars["open"]).abs()


def momentum_up(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar closed `threshold` above its own open — "it is running right now", the
    buy-the-flow idea. Long-only by construction; the repo has no borrow-cost model."""
    change = bars["close"] / bars["open"] - 1.0
    return (change >= threshold).fillna(False)


def reversal_down(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar closed `threshold` BELOW its open — buy what just got dumped, i.e. the
    liquidity-provision setup. The 5-minute study measured this effect at t = -32.1; the open
    question is only whether any (slice, hold, cost) region keeps it positive after costs."""
    change = bars["close"] / bars["open"] - 1.0
    return (change <= -threshold).fillna(False)


def volume_spike(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Volume at least `threshold` times the trailing median. The median is SHIFTED, so the
    current bar is never part of its own baseline."""
    median = bars["volume"].rolling(VOLUME_LOOKBACK).median().shift(1)
    return (bars["volume"] >= threshold * median).fillna(False)


def breakout_high(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Close breaks `threshold` above the highest close of the previous TREND_LOOKBACK bars —
    the Donchian idea the crypto and session lanes ran, now on every slice at once."""
    prior_high = bars["close"].rolling(TREND_LOOKBACK).max().shift(1)
    return (bars["close"] >= prior_high * (1.0 + threshold)).fillna(False)


def hammer(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Long lower wick, small body, close in the upper part of the range.

    `threshold` is the minimum lower-wick-to-body ratio. Zero-body bars are excluded rather
    than treated as an infinite ratio — a doji is a different pattern and gets no free pass.
    """
    body = _body(bars)
    lower_wick = bars[["open", "close"]].min(axis=1) - bars["low"]
    span = (bars["high"] - bars["low"]).replace(0.0, float("nan"))
    close_position = (bars["close"] - bars["low"]) / span
    return (
        (body > 0) & (lower_wick >= threshold * body) & (close_position >= 0.6)
    ).fillna(False)


def bullish_engulfing(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """An up bar whose body covers the previous DOWN bar's body by at least `threshold`x."""
    prev_open, prev_close = bars["open"].shift(1), bars["close"].shift(1)
    prev_body = (prev_open - prev_close).abs()
    covered = (bars["close"] >= prev_open) & (bars["open"] <= prev_close)
    return (
        (prev_close < prev_open)  # previous bar was down
        & (bars["close"] > bars["open"])  # this bar is up
        & covered
        & (_body(bars) >= threshold * prev_body)
        & (prev_body > 0)
    ).fillna(False)


def gap_up(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar opened `threshold` above the previous bar's close. On intraday slices that is
    an intraday jump; on the 1D slice it is the overnight gap."""
    gap = bars["open"] / bars["close"].shift(1) - 1.0
    return (gap >= threshold).fillna(False)


def gap_down(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar opened `threshold` BELOW the previous close — buying the gap, not fading it."""
    gap = bars["open"] / bars["close"].shift(1) - 1.0
    return (gap <= -threshold).fillna(False)


def spike_pullback(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Nico's setup: a big UP move, then an immediate small give-back — buy the dip in the spike.

    Fires when the bar before last rose at least `threshold` and the last bar gave part of it
    back (a red bar, but less than the spike itself, so this is a pullback and not a full
    reversal). The economic story is short-lived overreaction to the buying pressure, which is a
    different claim from `reversal_down` (that one needs no prior spike at all).
    """
    change = bars["close"] / bars["open"] - 1.0
    spike = change.shift(1) >= threshold
    give_back = (change < 0) & (change.abs() < change.shift(1).abs())
    return (spike & give_back).fillna(False)


def spike_fade(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """The opposite claim on the same event: after an outsized DOWN move, buy the exhaustion.

    Long-only, so this is the tradable half of "fade the overreaction". It fires one bar after
    the drop, which is what makes it distinguishable from `reversal_down` firing on the drop bar
    itself — the two together answer whether the entry timing matters.
    """
    change = bars["close"] / bars["open"] - 1.0
    return ((change.shift(1) <= -threshold) & (change >= 0)).fillna(False)


def consecutive_down(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """`threshold` red bars in a row (threshold is a COUNT here, not a percentage).

    The pure "it has fallen long enough" reflex, with no size condition at all — worth measuring
    precisely because it is the most common human reason to buy a dip.
    """
    red = (bars["close"] < bars["open"]).astype(int)
    streak = red.rolling(int(threshold)).sum()
    return (streak >= int(threshold)).fillna(False)


def range_contraction(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar's range is at most `threshold` times the trailing average range — the "coiled
    spring" idea (contraction precedes expansion). Fires on the quiet bar, so the trade is on
    what comes AFTER the calm, not on the move itself."""
    span = bars["high"] - bars["low"]
    baseline = span.rolling(VOLUME_LOOKBACK).mean().shift(1)
    return ((span <= threshold * baseline) & (baseline > 0)).fillna(False)


def new_low_20(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Close breaks `threshold` below the lowest close of the previous TREND_LOOKBACK bars —
    the mirror of breakout_high, and the setup a trend follower would refuse to touch."""
    prior_low = bars["close"].rolling(TREND_LOOKBACK).min().shift(1)
    return (bars["close"] <= prior_low * (1.0 - threshold)).fillna(False)


SIGNALS: dict[str, SignalSpec] = {
    "momentum_up": SignalSpec(
        momentum_up, (0.002, 0.005, 0.01, 0.02), "Bar schließt X über eigenem Open"
    ),
    "reversal_down": SignalSpec(
        reversal_down, (0.002, 0.005, 0.01, 0.02), "Bar schließt X unter eigenem Open"
    ),
    "volume_spike": SignalSpec(
        volume_spike, (2.0, 3.0, 5.0, 8.0), "Volumen X-fach über Trailing-Median"
    ),
    "breakout_high": SignalSpec(
        breakout_high, (0.0, 0.002, 0.005, 0.01), "Close bricht 20-Bar-Hoch um X"
    ),
    "hammer": SignalSpec(
        hammer, (1.5, 2.0, 3.0, 4.0), "Langer unterer Schatten, kleiner Körper"
    ),
    "bullish_engulfing": SignalSpec(
        bullish_engulfing, (1.0, 1.5, 2.0, 3.0), "Körper verschlingt Vorgänger-Körper"
    ),
    "gap_up": SignalSpec(
        gap_up, (0.002, 0.005, 0.01, 0.02), "Open X über vorherigem Close"
    ),
    "gap_down": SignalSpec(
        gap_down, (0.002, 0.005, 0.01, 0.02), "Open X unter vorherigem Close"
    ),
    "spike_pullback": SignalSpec(
        spike_pullback, (0.002, 0.005, 0.01, 0.02),
        "Großer Aufwärtssprung, dann sofortiger Rücksetzer (Nicos Setup)"
    ),
    "spike_fade": SignalSpec(
        spike_fade, (0.002, 0.005, 0.01, 0.02),
        "Nach übermäßigem Abwärtssprung die Erschöpfung kaufen"
    ),
    "consecutive_down": SignalSpec(
        consecutive_down, (2.0, 3.0, 4.0, 5.0),
        "X rote Bars in Folge (Schwelle ist eine ANZAHL, kein Prozentwert)"
    ),
    "range_contraction": SignalSpec(
        range_contraction, (0.3, 0.5, 0.7, 0.9),
        "Bar-Range höchstens X der Trailing-Durchschnittsrange"
    ),
    "new_low_20": SignalSpec(
        new_low_20, (0.0, 0.002, 0.005, 0.01), "Close bricht 20-Bar-Tief um X"
    ),
}
