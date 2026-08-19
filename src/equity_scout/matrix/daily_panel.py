"""OHLCV daily bars for live signal evaluation (v17, trader #3).

## Why this exists

The depot's `PricePanel` carries daily CLOSES only. Probed on 2026-08-19, that leaves exactly 3 of
15 matrix signals evaluable live (`breakout_high`, `new_low_20`, `catalyst_age`); the other 12 need
`open`, `high` or `volume`. A trader that can only act on a fifth of its own validated rules is
not the trader Nico asked for.

Rather than change `PricePanel` — which every other strategy depends on and which would turn a
data upgrade into a risk for the working ETF depot — the matrix strategy reads its own OHLCV
source: `data/daily/daily-<year>.csv.gz`, fetched by `scripts/fetch_spike_history.py` for 6241
tradable single stocks with `adjustment=all`.

## The look-ahead rule this file must not break

Bypassing `MarketView` means bypassing the protection that made look-ahead impossible. So the cut
is enforced here, in one place, strictly: `bars_before(ticker, as_of)` returns bars with
`date < as_of`, never `<=`. A bar dated `as_of` is the day being decided — using its close would
be trading on tomorrow's information, which is the single easiest way to manufacture a strategy
that backtests beautifully and loses live. The test suite pins this.

Loaded once per process and cached: 6241 tickers x 7 years is ~10 million rows, and a strategy
that reloads them per decision would never finish a backtest.
"""
from __future__ import annotations

import gzip
from functools import lru_cache
from pathlib import Path

import pandas as pd

DAILY_DIR = Path("data/daily")
COLUMNS = ("open", "high", "low", "close", "volume")


def available_years(root: Path | str = DAILY_DIR) -> list[int]:
    root = Path(root)
    if not root.exists():
        return []
    years = []
    for path in root.glob("daily-*.csv.gz"):
        try:
            years.append(int(path.stem.split("-")[1].split(".")[0]))
        except (IndexError, ValueError):
            continue
    return sorted(years)


def _read_year(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt") as handle:
        frame = pd.read_csv(handle)
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    return frame


@lru_cache(maxsize=1)
def load_panel(root: str = str(DAILY_DIR), tickers: tuple[str, ...] | None = None) -> pd.DataFrame:
    """All available daily bars as one long frame (ticker, date, o/h/l/c/v), date-sorted.

    Cached because it is large. `tickers` restricts the load — a backtest over a 30-name universe
    has no reason to hold 6241.
    """
    root_path = Path(root)
    frames = []
    for year in available_years(root_path):
        path = root_path / f"daily-{year}.csv.gz"
        frame = _read_year(path)
        if tickers:
            frame = frame[frame["ticker"].isin(tickers)]
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", *COLUMNS])
    panel = pd.concat(frames, ignore_index=True)
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True)


class DailyOHLCV:
    """Look-ahead-safe OHLCV access for one universe.

    Holds the panel grouped by ticker so a per-decision lookup is a dict hit plus one index
    search, not a scan of ten million rows.
    """

    def __init__(self, *, root: str | Path = DAILY_DIR, tickers: list[str] | None = None) -> None:
        panel = load_panel(str(root), tuple(sorted(tickers)) if tickers else None)
        self._by_ticker: dict[str, pd.DataFrame] = {}
        if panel.empty:
            return
        for ticker, group in panel.groupby("ticker", sort=False):
            frame = group.set_index("date")[list(COLUMNS)].sort_index()
            self._by_ticker[str(ticker)] = frame

    @property
    def tickers(self) -> list[str]:
        return sorted(self._by_ticker)

    def bars_before(self, ticker: str, as_of) -> pd.DataFrame:
        """Bars strictly BEFORE `as_of`.

        Strictly, not inclusively: the bar dated `as_of` belongs to the session being decided, and
        its close is not known when the decision is made. This is the one invariant of this file.
        """
        frame = self._by_ticker.get(ticker)
        if frame is None or frame.empty:
            return pd.DataFrame(columns=list(COLUMNS))
        cut = pd.Timestamp(as_of)
        if cut.tzinfo is None:
            cut = cut.tz_localize("UTC")
        return frame.loc[frame.index < cut]

    def has(self, ticker: str) -> bool:
        return ticker in self._by_ticker


def make_ohlcv_signal_fires(source: DailyOHLCV, *, min_history: int = 60):
    """`signal_fires` for MatrixStrategy backed by real OHLCV — all 15 signals usable.

    Same contract as `live_signal.make_signal_fires`, but no signal has to be refused for missing
    columns. The look-ahead guarantee comes from `bars_before`, not from MarketView, which is why
    that method is the one place the cut is implemented.
    """
    from equity_scout.matrix.signals import SIGNALS

    def signal_fires(plateau, ticker: str, as_of, market) -> bool:  # noqa: ARG001 - seam contract
        spec = SIGNALS.get(plateau.signal)
        if spec is None or not source.has(ticker):
            return False
        bars = source.bars_before(ticker, as_of)
        if len(bars) < min_history:
            return False
        for threshold in plateau.thresholds:
            try:
                fired = spec.detect(bars, threshold=threshold)
            except Exception:  # noqa: BLE001 - a broken evaluation is never a signal
                continue
            if len(fired) and bool(fired.iloc[-1]):
                return True
        return False

    return signal_fires
