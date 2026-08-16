"""Capitulation lane (`capitulation`): buy the panic, stop under its low.

The setup traders describe as capitulation: an outsized volume day on a sharp decline, read
as the last holders giving up. What makes it attractive on paper is not the hit rate but the
geometry — the panic low is a sharp, well-defined invalidation point, so the stop sits close.

The definition is NOT re-invented here. `volume_signals.read_volume` already decides what
counts as a spike (volume against the ticker's own 20-day MEDIAN, today excluded) and what
counts as capitulation (spike plus a decline of at least `CAPITULATION_DROP`). That module
has been live since v17 and feeds the market-behaviour block; a second, slightly different
definition in a trading rule would eventually disagree with the one on screen.

`event_study` re-implements the same rule vectorised, because judging 300k days one call at a
time is too slow to iterate on — `test_event_study_matches_read_volume` pins the two against
each other so the fast path can never drift from the displayed one.

Pure decision logic; the runner owns data access and the book.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from equity_scout.volume_signals import (
    BASELINE_DAYS,
    CAPITULATION_DROP,
    SPIKE_RATIO,
)

STOP_BUFFER = 0.02  # stop this far below the panic low — the low itself is a magnet
MAX_HOLDING_DAYS = 20


@dataclass(frozen=True)
class CapitulationAction:
    kind: str  # "buy" | "sell"
    ticker: str
    price: float
    at: str
    reason: str


def decide(
    ticker: str,
    closes: pd.Series,
    volumes: pd.Series,
    *,
    entry_price: float | None,
    panic_low: float | None,
    days_held: int,
) -> CapitulationAction | None:
    """One decision for the newest completed session. `entry_price=None` means flat."""
    if closes.empty or len(closes) != len(volumes):
        return None
    close = float(closes.iloc[-1])
    at = str(closes.index[-1])[:10]
    if entry_price is not None:
        if panic_low is not None and close <= panic_low * (1 - STOP_BUFFER):
            return CapitulationAction("sell", ticker, close, at, "Panik-Tief unterschritten")
        if days_held >= MAX_HOLDING_DAYS:
            return CapitulationAction("sell", ticker, close, at,
                                      f"Haltefrist {MAX_HOLDING_DAYS} Tage")
        return None
    from equity_scout.volume_signals import read_volume

    reading = read_volume(ticker, list(closes.astype(float)), list(volumes.astype(float)))
    if reading.is_capitulation:
        return CapitulationAction("buy", ticker, close, at,
                                  f"Kapitulation: {reading.ratio:.1f}× Normalvolumen")
    return None


def capitulation_mask(
    closes: pd.Series,
    volumes: pd.Series,
    *,
    spike_ratio: float = SPIKE_RATIO,
    drop: float = CAPITULATION_DROP,
    baseline_days: int = BASELINE_DAYS,
) -> pd.Series:
    """Vectorised twin of `read_volume(...).is_capitulation`, day by day.

    The baseline excludes the day itself (`shift(1)`); including it dampens exactly the spike
    the signal looks for."""
    baseline = volumes.shift(1).rolling(baseline_days).median()
    ratio = volumes / baseline
    change = closes.pct_change()
    return (ratio >= spike_ratio) & (change <= -drop) & baseline.notna() & (baseline > 0)


def event_study(
    closes: pd.Series,
    volumes: pd.Series,
    *,
    horizon: int = 20,
    spike_ratio: float = SPIKE_RATIO,
) -> dict:
    """Forward returns after a capitulation day against every other day."""
    closes, volumes = closes.dropna(), volumes.dropna()
    common = closes.index.intersection(volumes.index)
    closes, volumes = closes.loc[common], volumes.loc[common]
    if len(closes) < BASELINE_DAYS + horizon + 2:
        return {"n_events": 0, "n_other": 0}
    forward = closes.shift(-horizon) / closes - 1
    events_mask = capitulation_mask(closes, volumes, spike_ratio=spike_ratio)
    usable = forward.notna() & events_mask.notna()
    events, others = forward[usable & events_mask], forward[usable & ~events_mask]
    return {
        "n_events": int(len(events)),
        "n_other": int(len(others)),
        "mean_event": float(events.mean()) if len(events) else None,
        "mean_other": float(others.mean()) if len(others) else None,
        "hit_event": float((events > 0).mean()) if len(events) else None,
        "hit_other": float((others > 0).mean()) if len(others) else None,
        "std_event": float(events.std()) if len(events) > 1 else None,
        "std_other": float(others.std()) if len(others) > 1 else None,
    }
