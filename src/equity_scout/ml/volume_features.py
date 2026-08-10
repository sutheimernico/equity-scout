"""Point-in-time volume features for the entry model (v17c).

The entry model sits at AUC 0.47–0.50 — indistinguishable from a coin flip — on eleven
price-only features. Volume is the most obvious predictor it has never seen: price says at what
level buyer and seller agreed, volume says how many of them there were. Whether that closes
the gap is an empirical question, and the honest answer may well be no (the v15 P3 evidence
features added +0.003 AUC and no champion). This module makes the question askable.

Built as a deliberate copy of `evidence_features.EvidenceIndex`'s shape — same constructor
seam, same `features(ticker, as_of)` signature, same additive contract in `entry_dataset` — so
a reader who knows one knows the other, and `build_entry_dataset` needs no new concepts.

**Point-in-time rule, strictly enforced:** every window is half-open `[start, as_of)`. A row
dated `as_of` must never see volume from `as_of` itself, because on rebalance day the session
is not over and its volume is not knowable. Getting this wrong produces a beautiful backtest
and a worthless model, which is the single most expensive mistake available here.

Feature choice follows `volume_signals` — the same three behavioural readings, expressed as
model inputs:

- `vol_ratio_20d`: the day's volume over its own trailing median. Attention/participation.
- `vol_ratio_5d`: the same over five days, to separate a one-day event from a busy week.
- `vol_obv_20d`: on-balance volume over the window, normalised by the baseline — accumulation
  versus distribution, comparable across tickers.

All three are RELATIVE by construction. An absolute share count would let the model learn
"SPY is big", which is not behaviour, it is market cap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

VOLUME_FEATURE_COLUMNS: tuple[str, ...] = (
    "vol_ratio_20d",
    "vol_ratio_5d",
    "vol_obv_20d",
)
# The column that says "this row had usable volume at all" — the coverage question the P3
# evidence work taught us to ask FIRST, before reading any effect size.
VOLUME_ACTIVE_COLUMN = VOLUME_FEATURE_COLUMNS[0]

BASELINE_DAYS = 20
SHORT_DAYS = 5
MIN_BASELINE_OBS = 10
# A row with no usable volume history gets neutral values rather than being dropped: dropping
# would silently shrink the training set for exactly the young/illiquid tickers whose behaviour
# is most interesting, and the model can learn "1.0 with obv 0.0 means unknown" from the
# coverage pattern itself.
NEUTRAL: dict[str, float] = {"vol_ratio_20d": 1.0, "vol_ratio_5d": 1.0, "vol_obv_20d": 0.0}


def _as_date(value: object) -> date:
    """Same strictness as `evidence_features._as_date`: a null or tz-aware as_of is a caller
    bug that would silently shift every window, so it raises instead of coercing."""
    stamp = pd.Timestamp(value)  # type: ignore[arg-type]
    if stamp is pd.NaT:
        raise ValueError("as_of must not be null")
    if stamp.tzinfo is not None:
        raise ValueError(f"as_of must be tz-naive, got {stamp!r}")
    return stamp.date()


def _median(values: list[float]) -> float | None:
    usable = sorted(v for v in values if math.isfinite(v) and v > 0)
    if len(usable) < MIN_BASELINE_OBS:
        return None
    mid = len(usable) // 2
    return usable[mid] if len(usable) % 2 else (usable[mid - 1] + usable[mid]) / 2.0


@dataclass(frozen=True)
class VolumeIndex:
    """Per-ticker date-indexed volume and close series, queried once per dataset row.

    Holds closes as well as volumes because on-balance volume needs the price DIRECTION —
    a volume figure alone cannot say whether it was buying or selling.

    Same mutability caveat as `EvidenceIndex`: `frozen=True` freezes the field binding, not the
    frames it points at. Treat as read-only after construction.
    """

    volumes: pd.DataFrame  # index = dates, columns = tickers
    closes: pd.DataFrame   # same shape; used for OBV direction

    def features(self, ticker: str, as_of: object) -> dict[str, float]:
        """The volume block for one (ticker, as_of), keys == `VOLUME_FEATURE_COLUMNS`.

        Returns NEUTRAL (never None) when the history is too thin — see NEUTRAL's comment for
        why a missing row is kept rather than dropped. Windows end STRICTLY before `as_of`.
        """
        as_of_date = _as_date(as_of)
        if ticker not in self.volumes.columns:
            return dict(NEUTRAL)
        stamp = pd.Timestamp(as_of_date)
        # Strictly before as_of: on rebalance day the session is not finished.
        vol_series = self.volumes.loc[self.volumes.index < stamp, ticker].dropna()
        if len(vol_series) < MIN_BASELINE_OBS + 1:
            return dict(NEUTRAL)
        recent = [float(v) for v in vol_series.iloc[-(BASELINE_DAYS + 1):]]
        today = recent[-1]
        baseline = _median(recent[:-1])
        if baseline is None or baseline <= 0 or not math.isfinite(today):
            return dict(NEUTRAL)
        short_window = recent[-(SHORT_DAYS + 1):-1] or [today]
        short_avg = sum(short_window) / len(short_window)

        obv = 0.0
        if ticker in self.closes.columns:
            close_series = self.closes.loc[self.closes.index < stamp, ticker].dropna()
            aligned = close_series.reindex(vol_series.index).dropna()
            window_dates = aligned.index[-(BASELINE_DAYS + 1):]
            prices = [float(v) for v in aligned.loc[window_dates]]
            vols = [float(v) for v in vol_series.loc[window_dates]]
            for i in range(1, min(len(prices), len(vols))):
                if prices[i] > prices[i - 1]:
                    obv += vols[i]
                elif prices[i] < prices[i - 1]:
                    obv -= vols[i]
        return {
            "vol_ratio_20d": today / baseline,
            "vol_ratio_5d": short_avg / baseline,
            "vol_obv_20d": obv / baseline,
        }

    def coverage(self, tickers: list[str]) -> float:
        """Share of `tickers` that have enough volume history to produce a real reading.

        The number to read BEFORE any AUC comparison: the P3 evidence run looked like a
        +0.003 improvement until coverage turned out to be 2.5 %, at which point the
        comparison meant nothing. Same trap, same guard.
        """
        if not tickers:
            return 0.0
        usable = sum(
            1 for t in tickers
            if t in self.volumes.columns
            and int(self.volumes[t].notna().sum()) >= MIN_BASELINE_OBS + 1
        )
        return usable / len(tickers)


def load_volume_index(volume_csv: str, price_csv: str) -> VolumeIndex | None:
    """Build the index from the two snapshots, or None when either is missing.

    None (not an empty index) so a caller can tell "no volume data available" from "volume
    available but this ticker has none" — the first is a setup state, the second is a fact.
    """
    import os

    if not (os.path.exists(volume_csv) and os.path.exists(price_csv)):
        return None
    volumes = pd.read_csv(volume_csv, index_col=0, parse_dates=True)
    closes = pd.read_csv(price_csv, index_col=0, parse_dates=True)
    if volumes.empty or closes.empty:
        return None
    return VolumeIndex(volumes=volumes, closes=closes)
