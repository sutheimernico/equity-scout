"""Sector momentum snapshot: ranking, honest gaps, digest head line, API route."""
from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.data.etf_panel import save_snapshot
from equity_scout.etf_universe import SECTOR_ETF_TICKERS
from equity_scout.market import PricePanel
from equity_scout.sectors import sector_momentum, top_sector_line


def _geom(ret_12m: float, n: int = 300) -> list[float]:
    g = (1 + ret_12m) ** (1 / 252) - 1
    return [100.0 * (1 + g) ** i for i in range(n)]


def _panel(overrides: dict[str, float] | None = None, drop: tuple[str, ...] = ()) -> PricePanel:
    returns = {ticker: 0.02 for ticker in SECTOR_ETF_TICKERS}
    returns.update({"SPY": 0.05, "BIL": 0.01, "IEF": 0.0})
    returns.update(overrides or {})
    for ticker in drop:
        returns.pop(ticker, None)
    n = 300
    return PricePanel(
        pd.DataFrame(
            {t: _geom(r, n) for t, r in returns.items()},
            index=pd.bdate_range("2020-01-01", periods=n),
        )
    )


def test_sector_momentum_sorts_by_blend():
    rows = sector_momentum(_panel({"XLE": 0.40, "XLK": 0.30}))
    assert [row["ticker"] for row in rows[:2]] == ["XLE", "XLK"]
    assert rows[0]["blend"] is not None and rows[0]["blend"] > 0
    assert rows[0]["sector"] == "Energy"
    assert set(rows[0]["returns"]) == {"m1", "m3", "m6", "m12"}


def test_sector_momentum_puts_missing_history_last():
    rows = sector_momentum(_panel(drop=("XLC",)))
    assert rows[-1]["ticker"] == "XLC"
    assert rows[-1]["blend"] is None
    assert all(v is None for v in rows[-1]["returns"].values())


def test_top_sector_line_names_the_leaders():
    rows = sector_momentum(_panel({"XLE": 0.40, "XLK": 0.30, "XLV": 0.20}))
    line = top_sector_line(rows)
    assert line is not None
    assert line.startswith("Stärkste Sektoren: Energy")
    assert "Technology" in line and "Health Care" in line


def test_top_sector_line_is_none_without_rankable_rows():
    rows = sector_momentum(_panel(drop=tuple(SECTOR_ETF_TICKERS)))
    assert top_sector_line(rows) is None


def test_api_sectors_endpoint(tmp_path):
    snapshot = str(tmp_path / "panel.csv")
    save_snapshot(_panel({"XLE": 0.40}), snapshot)
    client = TestClient(create_app(db_path=str(tmp_path / "api.db"), snapshot=snapshot))
    body = client.get("/api/sectors").json()
    assert body["available"] is True
    assert body["sectors"][0]["ticker"] == "XLE"
    assert len(body["sectors"]) == len(SECTOR_ETF_TICKERS)
    assert "disclaimer" in body


def test_api_sectors_without_snapshot_is_graceful(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "api.db"),
                                   snapshot=str(tmp_path / "missing.csv")))
    body = client.get("/api/sectors").json()
    assert body["available"] is False
    assert body["sectors"] == []
