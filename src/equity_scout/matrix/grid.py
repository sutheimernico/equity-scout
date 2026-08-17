"""One matrix cell = one (signal, threshold, slice, hold, cost, asset class) measurement.

Design decisions that keep the numbers honest:

- **Costs are an AXIS, not a constant.** Every rule this repo ever tested died on costs, not on
  significance (`minute-scale-trading`: exactly one positive cell in the whole cost table). A
  matrix that fixes one cost level hides the thing that actually decides.
- **No pyramiding.** While a trade is open, later signals are ignored. Overlapping entries would
  multiply one market move into several "independent" observations and inflate t.
- **A hard sample floor.** Below MIN_TRADES a cell reports its trade count and nothing else. A
  cell with 12 trades and a big mean is the champion-artifact failure mode (AUC 0.6195 on 220
  rows that became 0.5152 on 3281).
- **Entry at the signal bar's close, exit `hold` bars later at the close.** The signal is known
  only once its bar has closed, so that close is the earliest honest fill. Costs are charged
  once per roundtrip.
- **Asset class travels with the cell** so "do commodities behave differently from stocks" is a
  question the matrix answers rather than one it averages away.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HOLD_BARS = (1, 2, 3, 6, 12)  # in units of the cell's own slice
COST_BPS = (2.0, 4.0, 10.0, 20.0)  # roundtrip; 4 bp = liquid names, 10 bp = realistic
MIN_TRADES = 200  # below this a cell is not evidence
HOLD_OUT_START = "2023-01-01"  # opened ONCE, at the end of a matrix run


def split_periods(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(search window, hold-out). The hold-out exists so a plateau found by searching a large
    space can be checked on data the search never touched."""
    cut = pd.Timestamp(HOLD_OUT_START, tz="UTC")
    return bars.loc[bars.index < cut], bars.loc[bars.index >= cut]


def trade_returns(bars: pd.DataFrame, signal: pd.Series, *, hold_bars: int) -> np.ndarray:
    """Gross forward returns in bp of every NON-OVERLAPPING signal entry.

    Split out from `evaluate_cell` for one reason that decides whether a full run finishes at
    all: the cost axis does not change which trades happen, only what they earn. Computing the
    trades once and subtracting each cost level afterwards divides the work by len(COST_BPS).
    The selection also walks the signal INDICES (typically <1 % of bars) instead of every bar,
    which is what makes a million-bar series tractable in Python.
    """
    closes = bars["close"].to_numpy(dtype=float)
    candidates = np.flatnonzero(signal.to_numpy(dtype=bool))
    limit = len(closes) - hold_bars
    entries: list[int] = []
    next_free = 0
    for position in candidates:
        if position >= limit:
            break
        if position < next_free or closes[position] <= 0:
            continue
        entries.append(int(position))
        next_free = position + hold_bars  # the position occupies its holding window
    if not entries:
        return np.empty(0, dtype=float)
    taken = np.asarray(entries)
    return (closes[taken + hold_bars] / closes[taken] - 1.0) * 10_000.0


def cell_from_returns(gross_bp: np.ndarray, *, cost_bps: float) -> dict:
    """One cell's statistics from pre-computed gross returns; None below the sample floor."""
    n = len(gross_bp)
    if n < MIN_TRADES:
        return {"n": n, "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None}
    net = gross_bp - cost_bps
    std = float(net.std(ddof=1))
    return {
        "n": n,
        "gross_bp": float(gross_bp.mean()),
        "net_bp": float(net.mean()),
        "t": float(net.mean()) / (std / math.sqrt(n)) if std > 0 else None,
        "hit_rate": float((net > 0).mean()),
    }


def evaluate_cell(
    bars: pd.DataFrame, signal: pd.Series, *, hold_bars: int, cost_bps: float
) -> dict:
    """Forward return of every non-overlapping signal entry, gross and after costs.

    Returns n / gross_bp / net_bp / t / hit_rate. n is ALWAYS reported; the statistics come back
    as None when n < MIN_TRADES, so a thin cell cannot masquerade as a finding. Convenience
    wrapper over trade_returns + cell_from_returns for single-cell callers and tests.
    """
    return cell_from_returns(
        trade_returns(bars, signal, hold_bars=hold_bars), cost_bps=cost_bps
    )


def pool_cells(per_ticker: list[dict], **axes) -> dict:
    """Trade-weighted pool of per-ticker cells, carrying the axis values.

    Pooling instead of a per-ticker matrix is deliberate: 70 separate matrices would multiply
    the search space by 70 and invite exactly the cherry-picking the plateau design exists to
    prevent. The pool measures the MECHANISM; per-ticker behaviour is a later question.

    The pooled t uses sum(t_i * sqrt(n_i)) / sqrt(sum(n_i)) — Stouffer-style, deliberately
    conservative: it never assumes the tickers are independent draws of one effect, which they
    are not (they share market-wide moves).
    """
    usable = [c for c in per_ticker if c["net_bp"] is not None]
    out = {
        **axes,
        "n": sum(c["n"] for c in per_ticker),
        "tickers": len(per_ticker),
        "tickers_measurable": len(usable),
        "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None,
    }
    if not usable:
        return out
    weight = sum(c["n"] for c in usable)
    out["gross_bp"] = sum(c["gross_bp"] * c["n"] for c in usable) / weight
    out["net_bp"] = sum(c["net_bp"] * c["n"] for c in usable) / weight
    out["hit_rate"] = sum(c["hit_rate"] * c["n"] for c in usable) / weight
    with_t = [c for c in usable if c["t"] is not None]
    if with_t:
        out["t"] = sum(c["t"] * (c["n"] ** 0.5) for c in with_t) / (
            sum(c["n"] for c in with_t) ** 0.5
        )
    return out
