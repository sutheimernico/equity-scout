"""Matrix runner: full axis coverage, resumable checkpoint, hold-out kept shut."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_signal_matrix import cells_for_ticker, done_tickers, pooled_cells


def _bars(n: int, day: str = "2022-06-01") -> pd.DataFrame:
    index = pd.date_range(f"{day}T13:30:00Z", periods=n, freq="1min")
    closes = [100.0 + (i % 7) * 0.1 for i in range(n)]
    return pd.DataFrame(
        {"open": closes, "high": [c + 0.05 for c in closes], "low": [c - 0.05 for c in closes],
         "close": closes, "volume": [100 + i % 50 for i in range(n)]},
        index=index, dtype=float,
    )


def test_cells_carry_every_axis_and_the_asset_class():
    rows = cells_for_ticker(_bars(2000), "SPY", "search")
    assert rows, "expected cells for a 2000-bar series"
    for row in rows:
        assert set(row) >= {
            "ticker", "asset_class", "window", "signal", "threshold", "slice",
            "hold_bars", "cost_bps", "n",
        }
    assert {row["asset_class"] for row in rows} == {"index"}  # SPY is an index ETF
    assert {row["window"] for row in rows} == {"search"}


def test_a_slice_too_coarse_for_the_sample_floor_is_skipped_not_faked():
    # 2000 one-minute bars can never yield 200 monthly bars
    rows = cells_for_ticker(_bars(2000), "SPY", "search")
    assert "1M" not in {row["slice"] for row in rows}
    assert "1min" in {row["slice"] for row in rows}


def test_unknown_tickers_are_labelled_rather_than_guessed():
    rows = cells_for_ticker(_bars(1000), "ZZZZ", "search")
    assert {row["asset_class"] for row in rows} == {"unknown"}


def test_done_tickers_reads_the_checkpoint_and_survives_a_torn_line(tmp_path):
    path = tmp_path / "cells.jsonl"
    path.write_text(
        json.dumps({"ticker": "SPY", "window": "search"}) + "\n"
        + json.dumps({"ticker": "GLD", "window": "search"}) + "\n"
        + '{"ticker": "AAPL", "wind'  # killed mid-write
    )
    assert done_tickers(path) == {"SPY", "GLD"}


def test_done_tickers_on_a_missing_file_is_empty(tmp_path):
    assert done_tickers(tmp_path / "nothing.jsonl") == set()


def test_pooled_cells_groups_per_asset_class_and_ignores_other_windows(tmp_path):
    path = tmp_path / "cells.jsonl"
    common = {"signal": "hammer", "threshold": 2.0, "slice": "5min", "hold_bars": 3,
              "cost_bps": 4.0, "gross_bp": 10.0, "net_bp": 6.0, "t": 3.0, "hit_rate": 0.6}
    rows = [
        {"ticker": "AAPL", "asset_class": "stock", "window": "search", "n": 300, **common},
        {"ticker": "MSFT", "asset_class": "stock", "window": "search", "n": 100, **common},
        {"ticker": "GLD", "asset_class": "commodity", "window": "search", "n": 500, **common},
        {"ticker": "AAPL", "asset_class": "stock", "window": "holdout", "n": 900, **common},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pooled = pooled_cells(path, "search")
    assert len(pooled) == 2  # stock + commodity, holdout excluded
    by_class = {cell["asset_class"]: cell for cell in pooled}
    assert by_class["stock"]["n"] == 400 and by_class["stock"]["tickers"] == 2
    assert by_class["commodity"]["n"] == 500
