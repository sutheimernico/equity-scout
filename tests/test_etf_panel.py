import numpy as np
import pandas as pd

from equity_scout.data.etf_panel import clean_panel, load_snapshot, save_snapshot
from equity_scout.etf_universe import ETF_BY_TICKER, ETF_TICKERS, ETF_UNIVERSE
from equity_scout.market import PricePanel


def _frame(data: dict[str, list[float]]) -> pd.DataFrame:
    n = len(next(iter(data.values())))
    return pd.DataFrame(data, index=pd.bdate_range("2021-01-01", periods=n))


def test_clean_panel_trims_to_common_start():
    df = _frame({"AAA": [1.0, 2.0, 3.0, 4.0, 5.0], "BBB": [np.nan, np.nan, 30.0, 40.0, 50.0]})
    panel = clean_panel(df)
    assert panel.dates[0] == df.index[2]  # starts where the last-to-appear ticker has data
    assert len(panel.dates) == 3


def test_clean_panel_forward_fills_stray_gaps():
    df = _frame({"AAA": [1.0, np.nan, 3.0], "BBB": [10.0, 20.0, 30.0]})
    panel = clean_panel(df)
    assert panel.closes["AAA"].iloc[1] == 1.0  # filled from the prior day, not dropped
    assert len(panel.dates) == 3


def test_snapshot_roundtrip(tmp_path):
    panel = PricePanel(_frame({"AAA": [1.0, 2.0], "BBB": [3.0, 4.0]}))
    path = str(tmp_path / "panel.csv")
    save_snapshot(panel, path)
    loaded = load_snapshot(path)
    assert loaded.tickers == ["AAA", "BBB"]
    assert list(loaded.dates) == list(panel.dates)
    assert (loaded.closes.values == panel.closes.values).all()


def test_etf_universe_shape():
    assert len(ETF_TICKERS) == 10
    assert ETF_BY_TICKER["SPY"].sector == "US Equity"
    assert all(inst.currency == "USD" for inst in ETF_UNIVERSE)
