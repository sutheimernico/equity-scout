"""Evaluate a matrix signal on live panel data — the bridge from register to trade (v17).

## The problem this solves honestly

The matrix measures on OHLCV minute bars. The depot's `PricePanel` carries daily CLOSES only
(`market.py`: "Daily adjusted closes for a basket"). So a plateau built on `momentum_up` (which
compares close to its own bar OPEN) or on `volume_spike` cannot be evaluated live at all.

There are two ways to handle that and only one of them is honest:

- Fake the missing columns (open = close, volume = 1). The signal then runs, returns something,
  and trades on a quantity that does not exist. `momentum_up` with open == close is identically
  False; `volume_spike` with constant volume is identically False — so the strategy would silently
  hold nothing while believing it evaluated its rule.
- Build the frame WITHOUT those columns, let the signal raise, and report the plateau as
  not-live-evaluable. Then it does not trade, and the reason is visible.

This module does the second. `evaluable_signals()` probes each registered signal once against a
close-only frame and reports which ones can be used live. A plateau whose signal is not in that
set is skipped by the strategy and named in the log — never traded on substitute data.

Closing that gap for real means giving the depot an OHLCV panel, which is a separate piece of
work (an `autotrader_ohlc.csv` already exists for the fill logic but is not wired into
`PricePanel`). Until then this is a documented limit, not a silent one.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from equity_scout.matrix.signals import SIGNALS

if TYPE_CHECKING:
    from equity_scout.market import MarketView
    from equity_scout.matrix.registry import QualifiedPlateau

# A signal needs at least this much visible history before its rolling statistics mean anything.
MIN_HISTORY_BARS = 60


def close_only_frame(closes: pd.Series) -> pd.DataFrame:
    """A frame carrying ONLY `close`.

    Deliberately missing open/high/low/volume: a signal that needs them must fail loudly here
    rather than compute a plausible number from a substitute.
    """
    return pd.DataFrame({"close": closes.astype(float)})


def evaluable_signals() -> tuple[set[str], dict[str, str]]:
    """(names usable on close-only data, {name: reason it is not}).

    Probed once against a synthetic series rather than hard-coded, so a signal added later is
    classified automatically instead of silently inheriting someone's assumption.
    """
    probe = close_only_frame(pd.Series(
        [100.0 + (index % 7) for index in range(120)],
        index=pd.date_range("2020-01-01", periods=120, freq="D", tz="UTC"),
    ))
    usable: set[str] = set()
    blocked: dict[str, str] = {}
    for name, spec in SIGNALS.items():
        threshold = spec.thresholds[0]
        try:
            result = spec.detect(probe, threshold=threshold)
        except KeyError as missing:
            blocked[name] = f"braucht Spalte {missing} — im Tagespanel nicht vorhanden"
            continue
        except Exception as exc:  # noqa: BLE001 - any failure means "not usable here"
            blocked[name] = f"nicht auswertbar: {type(exc).__name__}"
            continue
        if not isinstance(result, pd.Series) or result.dtype != bool:
            blocked[name] = "liefert keine bool-Serie"
            continue
        usable.add(name)
    return usable, blocked


def make_signal_fires(*, usable: set[str] | None = None):
    """Build the `signal_fires` callable that MatrixStrategy expects.

    Signature (plateau, ticker, as_of, market) -> bool. True means: this plateau's rule fires for
    this ticker on the LAST visible bar. Look-ahead safety comes from `MarketView`, which only
    exposes data strictly before `as_of` — this function never indexes past the visible end.
    """
    allowed = usable if usable is not None else evaluable_signals()[0]

    def signal_fires(
        plateau: QualifiedPlateau, ticker: str, as_of, market: MarketView
    ) -> bool:
        if plateau.signal not in allowed:
            return False
        history = market.history(ticker)
        if history is None or len(history) < MIN_HISTORY_BARS:
            return False
        spec = SIGNALS.get(plateau.signal)
        if spec is None:
            return False
        bars = close_only_frame(history.dropna())
        if len(bars) < MIN_HISTORY_BARS:
            return False
        # Any threshold of the plateau firing counts: the region's claim is that the rule holds
        # ACROSS its neighbourhood, so requiring the strictest one would trade a narrower rule
        # than the one that was actually validated.
        for threshold in plateau.thresholds:
            try:
                fired = spec.detect(bars, threshold=threshold)
            except Exception:  # noqa: BLE001 - a broken evaluation is not a signal
                continue
            if len(fired) and bool(fired.iloc[-1]):
                return True
        return False

    return signal_fires
