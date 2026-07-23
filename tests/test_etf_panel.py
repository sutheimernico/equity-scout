import numpy as np
import pandas as pd

from equity_scout.data.etf_panel import (
    clean_panel,
    drop_short_history,
    load_snapshot,
    save_snapshot,
)
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
    # 10 core multi-asset ETFs + 11 SPDR sector funds (v8 sector rotation).
    assert len(ETF_TICKERS) == 21
    assert ETF_BY_TICKER["SPY"].sector == "US Equity"
    assert ETF_BY_TICKER["XLK"].sector == "US Sector: Technology"
    assert all(inst.currency == "USD" for inst in ETF_UNIVERSE)


def test_clean_panel_drops_dead_ticker_instead_of_crashing():
    """An all-NaN column (delisted/junk symbol) used to crash first_valid_index max()."""
    import numpy as np

    idx = pd.bdate_range("2026-01-01", periods=5)
    df = pd.DataFrame({"AAA": [1.0, 2, 3, 4, 5], "DEAD": [np.nan] * 5}, index=idx)
    panel = clean_panel(df)
    assert list(panel.closes.columns) == ["AAA"]
    assert len(panel.closes) == 5


def test_clean_columns_keeps_each_tickers_own_history():
    """No common-range trim: a young ticker must not truncate an old one's history."""
    import numpy as np

    from equity_scout.data.etf_panel import clean_columns

    idx = pd.bdate_range("2026-01-01", periods=6)
    df = pd.DataFrame(
        {
            "OLD": [1.0, 2, 3, 4, 5, 6],
            "YOUNG": [np.nan, np.nan, np.nan, np.nan, 1.0, 2.0],
            "DEAD": [np.nan] * 6,
        },
        index=idx,
    )
    panel = clean_columns(df)
    assert list(panel.closes.columns) == ["OLD", "YOUNG"]
    assert panel.closes["OLD"].notna().all()  # OLD keeps its full range


def test_drop_short_history_excludes_late_starter_with_metadata():
    """v13 Q1: a ticker starting deep into the span is dropped and reported; the earliest
    starter always survives, so a non-empty frame can never come back empty."""
    idx = pd.bdate_range("2020-01-01", periods=1000)
    df = pd.DataFrame({"OLD": 1.0, "SPY": 2.0}, index=idx)
    df["YOUNG"] = np.nan
    df.loc[idx[900]:, "YOUNG"] = 5.0  # starts at 90% of the span
    survivors, excluded = drop_short_history(df, max_span_loss=0.30)
    assert list(survivors.columns) == ["OLD", "SPY"]
    assert len(excluded) == 1
    record = excluded[0]
    assert record["ticker"] == "YOUNG"
    assert record["first_valid"] == idx[900].date().isoformat()
    assert record["panel_start"] == idx[0].date().isoformat()
    assert record["span_loss"] > 0.85


def test_drop_short_history_keeps_tickers_within_the_loss_budget():
    idx = pd.bdate_range("2020-01-01", periods=1000)
    df = pd.DataFrame({"OLD": 1.0}, index=idx)
    df["OK"] = np.nan
    df.loc[idx[200]:, "OK"] = 3.0  # ~20% span loss — inside the 30% budget
    survivors, excluded = drop_short_history(df, max_span_loss=0.30)
    assert list(survivors.columns) == ["OLD", "OK"]
    assert excluded == []


def test_drop_short_history_empty_and_dead_columns():
    assert drop_short_history(pd.DataFrame())[0].empty
    idx = pd.bdate_range("2026-01-01", periods=5)
    df = pd.DataFrame({"OLD": [1.0] * 5, "DEAD": [np.nan] * 5}, index=idx)
    survivors, excluded = drop_short_history(df)
    assert list(survivors.columns) == ["OLD"]  # dead column dropped, not "excluded"
    assert excluded == []
