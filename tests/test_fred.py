"""FRED feature loader: snapshot alignment/ffill + graceful skip when unavailable."""
from __future__ import annotations

import pandas as pd

import equity_scout.ml.fred as fred_mod
from equity_scout.ml.fred import fred_available, load_fred_features


def test_fred_features_align_and_forward_fill(tmp_path) -> None:
    snap = tmp_path / "fred.csv"
    pd.DataFrame(
        {"vix": [20.0, 21.0], "term_spread": [0.5, 0.4], "hy_spread": [3.0, 3.1]},
        index=pd.to_datetime(["2020-01-01", "2020-01-03"]),
    ).to_csv(snap)

    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
    out = load_fred_features(dates, snapshot=snap)

    assert list(out.columns) == ["vix", "term_spread", "hy_spread"]
    assert list(out.index) == list(dates)
    assert out.loc["2020-01-02", "vix"] == 20.0  # forward-filled from 01-01 (no own observation)
    assert out.loc["2020-01-03", "vix"] == 21.0


def test_fred_unavailable_returns_empty_frame(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fred_mod, "_fetch_series", lambda sid, start: None)  # simulate network failure
    snap = tmp_path / "missing.csv"
    dates = pd.to_datetime(["2020-01-01", "2020-01-02"])
    out = load_fred_features(dates, snapshot=snap)

    assert out.shape[1] == 0  # no columns → callers treat as "no FRED features"
    assert not fred_available(snap)
