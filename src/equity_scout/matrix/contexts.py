"""Context filters: the conditions a signal is allowed to fire under.

Nico's brief (2026-08-17): "hoher Greed-Index UND dazu eine positive News" — i.e. the interesting
part is not another signal, it is the CONJUNCTION of a signal with market context. This module
supplies those conditions as boolean masks; the grid then measures every (signal x context) pair,
which turns "does the pattern work?" into "does it work, and under which circumstances?".

Two design rules, both about not fooling ourselves:

1. **Depth one.** A context is combined with exactly ONE signal, never stacked. Every additional
   condition cuts the sample: a filter that keeps a third of the bars turns 900 trades into 300,
   and two stacked filters turn them into 100 — below the floor, where the matrix can only report
   "not measurable". The honest limit of ten years of minute bars is one condition, and the
   `none` context is always measured alongside so the filter's CONTRIBUTION stays visible.
2. **A context never peeks.** Same look-ahead contract as the signals: the mask at row i uses only
   information available at row i. `after_news` uses the wire timestamp, `high_vix` uses the
   PREVIOUS session's close, and the trend filters use shifted rolling windows.

Contexts are not an adjacency axis in the plateau finder, for the same reason cost levels are not:
"works only when news just dropped" is a different economic claim from "works always", and
merging them would hide exactly the finding Nico is after.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

TREND_LOOKBACK = 50  # bars for the slow average behind uptrend/downtrend
VOLUME_LOOKBACK = 20  # bars for the relative-volume baseline
NEWS_WINDOW_MINUTES = 30  # how long a wire item counts as "just happened"
VIX_CALM, VIX_STRESS = 15.0, 22.0  # the greed/fear proxy's bands (VIX close, previous session)


@dataclass(frozen=True)
class ContextSpec:
    mask: Callable[..., pd.Series]
    description: str
    needs: tuple[str, ...] = ()  # extra inputs: "news", "vix"


def _all_true(bars: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=bars.index)


def none(bars: pd.DataFrame, **_) -> pd.Series:
    """No condition — the baseline every filtered variant is compared against."""
    return _all_true(bars)


def first_hour(bars: pd.DataFrame, **_) -> pd.Series:
    """09:30-10:30 ET. The opening hour carries most of the day's volume and volatility, and
    every intraday study in this repo so far pooled it with the quiet midday."""
    local = bars.index.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    return pd.Series((minutes >= 9 * 60 + 30) & (minutes < 10 * 60 + 30), index=bars.index)


def last_hour(bars: pd.DataFrame, **_) -> pd.Series:
    """15:00-16:00 ET — the closing auction's run-up, a different regime from midday."""
    local = bars.index.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    return pd.Series(minutes >= 15 * 60, index=bars.index)


def midday(bars: pd.DataFrame, **_) -> pd.Series:
    """10:30-15:00 ET — the thin middle."""
    local = bars.index.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    return pd.Series(
        (minutes >= 10 * 60 + 30) & (minutes < 15 * 60), index=bars.index
    )


def high_rel_volume(bars: pd.DataFrame, **_) -> pd.Series:
    """This bar's volume is above twice the trailing median (shifted baseline)."""
    baseline = bars["volume"].rolling(VOLUME_LOOKBACK).median().shift(1)
    return (bars["volume"] >= 2.0 * baseline).fillna(False)


def uptrend(bars: pd.DataFrame, **_) -> pd.Series:
    """Close above the slow average — "the tape is already up", Nico's flow condition."""
    slow = bars["close"].rolling(TREND_LOOKBACK).mean().shift(1)
    return (bars["close"] > slow).fillna(False)


def downtrend(bars: pd.DataFrame, **_) -> pd.Series:
    """Close below the slow average. A mean-reversion signal may only work here."""
    slow = bars["close"].rolling(TREND_LOOKBACK).mean().shift(1)
    return (bars["close"] < slow).fillna(False)


def after_news(bars: pd.DataFrame, *, news_stamps: pd.Series | None = None, **_) -> pd.Series:
    """A wire item for this instrument landed within the last NEWS_WINDOW_MINUTES.

    This is Nico's "und dazu eine positive News" condition, minus the direction: the wire's
    sentiment is not classified here. Direction would be a second condition, and depth stays at
    one — measure whether news matters at all before splitting it into good and bad.
    """
    if news_stamps is None or len(news_stamps) == 0:
        return pd.Series(False, index=bars.index)
    window = pd.Timedelta(minutes=NEWS_WINDOW_MINUTES)
    stamps = pd.DatetimeIndex(pd.to_datetime(news_stamps, utc=True)).sort_values()
    # For each bar: the most recent wire item at or before it. searchsorted keeps this O(n log n)
    # instead of comparing every bar against every headline.
    position = stamps.searchsorted(bars.index, side="right") - 1
    fresh = pd.Series(False, index=bars.index)
    valid = position >= 0
    if valid.any():
        latest = stamps[position[valid]]
        fresh.loc[valid] = (bars.index[valid] - latest) <= window
    return fresh


def _vix_for_bars(bars: pd.DataFrame, vix_closes: pd.Series | None) -> pd.Series | None:
    """The PREVIOUS session's VIX close aligned to each bar — never the same day's, which would
    let a bar know how the fear gauge ended after it traded."""
    if vix_closes is None or vix_closes.empty:
        return None
    daily = vix_closes.copy()
    daily.index = pd.DatetimeIndex(daily.index).tz_localize(None).normalize()
    shifted = daily.shift(1).dropna()
    bar_days = pd.DatetimeIndex(
        bars.index.tz_convert("America/New_York").tz_localize(None).normalize()
    )
    return pd.Series(shifted.reindex(bar_days).to_numpy(), index=bars.index)


def calm_market(bars: pd.DataFrame, *, vix_closes: pd.Series | None = None, **_) -> pd.Series:
    """Previous VIX close below VIX_CALM — the greed end of the fear/greed scale.

    VIX stands in for the Fear-&-Greed index on purpose: the composite was measured in this repo
    on 2026-08-11 and came out WEAKER than its own best ingredient, so the ingredient is used.
    """
    aligned = _vix_for_bars(bars, vix_closes)
    if aligned is None:
        return pd.Series(False, index=bars.index)
    return (aligned < VIX_CALM).fillna(False)


def stressed_market(bars: pd.DataFrame, *, vix_closes: pd.Series | None = None, **_) -> pd.Series:
    """Previous VIX close above VIX_STRESS — the fear end."""
    aligned = _vix_for_bars(bars, vix_closes)
    if aligned is None:
        return pd.Series(False, index=bars.index)
    return (aligned > VIX_STRESS).fillna(False)


def recent_signal_gate(
    detect: Callable[..., pd.Series], *, threshold: float, window_bars: int
) -> Callable[..., pd.Series]:
    """Turn a SIGNAL into a CONDITION: "this fired within the last `window_bars` bars".

    This is what makes "every parameter against every parameter" measurable at all. Two events
    coinciding on the exact same bar is vanishingly rare — two signals that each fire on 1 % of
    bars coincide on 0.01 %, i.e. ~100 cases in a million bars, below the sample floor. As a
    STATE, the same signal covers `window_bars` times more ground, so the conjunction reaches a
    countable sample without weakening the claim: "B happened recently, then A fired" is the
    setup a human would actually describe.

    The window is shifted by one bar, so the gate never includes the bar being judged — the
    condition must be established BEFORE the signal it gates.
    """
    def mask(bars: pd.DataFrame, **_) -> pd.Series:
        fired = detect(bars, threshold=threshold).astype(int)
        recent = fired.shift(1).rolling(window_bars).sum()
        return (recent > 0).fillna(False)

    return mask


CONTEXTS: dict[str, ContextSpec] = {
    "none": ContextSpec(none, "Keine Bedingung (Basislinie)"),
    "first_hour": ContextSpec(first_hour, "Erste Handelsstunde"),
    "midday": ContextSpec(midday, "Mittagsflaute"),
    "last_hour": ContextSpec(last_hour, "Letzte Handelsstunde"),
    "high_rel_volume": ContextSpec(high_rel_volume, "Volumen über 2x Trailing-Median"),
    "uptrend": ContextSpec(uptrend, "Close über langsamem Schnitt"),
    "downtrend": ContextSpec(downtrend, "Close unter langsamem Schnitt"),
    "after_news": ContextSpec(
        after_news, f"Wire-Meldung in den letzten {NEWS_WINDOW_MINUTES} Minuten", needs=("news",)
    ),
    "calm_market": ContextSpec(
        calm_market, f"VIX (Vortag) unter {VIX_CALM:.0f} — Greed-Seite", needs=("vix",)
    ),
    "stressed_market": ContextSpec(
        stressed_market, f"VIX (Vortag) über {VIX_STRESS:.0f} — Fear-Seite", needs=("vix",)
    ),
}
