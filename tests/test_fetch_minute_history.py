"""Bulk minute download: resumable, asset classes labelled, gaps reported not hidden."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_minute_history import (
    ASSET_CLASSES,
    FULL_YEARS,
    MINUTE_UNIVERSE,
    asset_class,
    missing_jobs,
    summarise_coverage,
)


def test_universe_spans_every_asset_class_nico_asked_about():
    classes = set(ASSET_CLASSES.values())
    assert {"stock", "index", "commodity", "bond", "currency"} <= classes
    assert len(MINUTE_UNIVERSE) == len(set(MINUTE_UNIVERSE))  # no duplicates
    assert "SPY" in MINUTE_UNIVERSE and "GLD" in MINUTE_UNIVERSE and "USO" in MINUTE_UNIVERSE


def test_asset_class_labels_unknown_tickers_instead_of_guessing():
    assert asset_class("gld") == "commodity"
    assert asset_class("AAPL") == "stock"
    assert asset_class("ZZZZ") == "unknown"


def test_the_current_year_is_excluded_because_the_plan_blocks_recent_sip():
    assert FULL_YEARS == tuple(range(2016, 2026))


def test_missing_jobs_lists_only_absent_ticker_years(tmp_path):
    (tmp_path / "AAPL-2024.csv.gz").write_bytes(b"")
    assert missing_jobs(["AAPL", "MSFT"], [2024], root=tmp_path) == [("MSFT", 2024)]


def test_summarise_coverage_counts_rows_and_flags_thin_years(tmp_path):
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=pd.to_datetime(["2024-01-02T14:30:00Z"]),
    )
    frame.to_csv(tmp_path / "AAPL-2024.csv.gz", compression="gzip", index_label="t")
    assert summarise_coverage(["AAPL"], [2024], root=tmp_path) == [
        {"ticker": "AAPL", "year": 2024, "bars": 1, "thin": True}
    ]


def test_coverage_of_an_absent_ticker_year_is_simply_not_reported(tmp_path):
    assert summarise_coverage(["AAPL"], [2024], root=tmp_path) == []
