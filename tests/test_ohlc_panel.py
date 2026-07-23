"""OHLC panel loader (v13 O1): fake-downloader round trip, cache path, honest misses."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.data.ohlc_panel import (
    OHLC_FIELDS,
    load_ohlc_panel,
    load_ohlc_snapshot,
    save_ohlc_snapshot,
)


def _ohlc(days: int, *, start: str = "2026-01-01", base: float = 100.0) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    close = base + np.arange(days, dtype=float)
    return pd.DataFrame(
        {"open": close - 0.5, "high": close + 1.0, "low": close - 1.0, "close": close},
        index=idx,
    )


def test_load_ohlc_panel_fake_downloader_round_trip(tmp_path):
    snapshot = str(tmp_path / "ohlc.csv")
    fake = {"AAA": _ohlc(10), "BBB": _ohlc(3, start="2026-01-12")}
    panel = load_ohlc_panel(
        ["AAA", "BBB", "MISSING"], start="2026-01-01", snapshot=snapshot,
        refresh=True, downloader=lambda tickers, start: fake,
    )
    assert set(panel) == {"AAA", "BBB"}  # MISSING: absent key, no crash
    assert list(panel["AAA"].columns) == list(OHLC_FIELDS)
    assert len(panel["AAA"]) == 10
    assert len(panel["BBB"]) == 3  # young ticker keeps its own short history only


def test_load_ohlc_panel_reads_snapshot_without_downloader(tmp_path):
    snapshot = str(tmp_path / "ohlc.csv")
    save_ohlc_snapshot({"AAA": _ohlc(5)}, snapshot)

    def exploding_downloader(tickers, start):
        raise AssertionError("cache hit path must not download")

    panel = load_ohlc_panel(
        ["AAA"], start="2026-01-01", snapshot=snapshot, downloader=exploding_downloader
    )
    assert len(panel["AAA"]) == 5
    assert panel["AAA"]["close"].iloc[-1] == 104.0


def test_ohlc_snapshot_round_trip_preserves_values_and_dates(tmp_path):
    snapshot = str(tmp_path / "ohlc.csv")
    original = {"AAA": _ohlc(4), "BBB": _ohlc(2, base=50.0)}
    save_ohlc_snapshot(original, snapshot)
    loaded = load_ohlc_snapshot(snapshot)
    assert set(loaded) == {"AAA", "BBB"}
    for ticker, frame in original.items():
        pd.testing.assert_frame_equal(
            loaded[ticker], frame, check_freq=False, check_names=False
        )


def test_empty_panel_snapshot_round_trips(tmp_path):
    snapshot = str(tmp_path / "ohlc.csv")
    save_ohlc_snapshot({}, snapshot)
    assert load_ohlc_snapshot(snapshot) == {}
