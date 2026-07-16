"""Regime traffic light: pure signal logic + green-count composite (v8 C1)."""
from __future__ import annotations

from equity_scout.regime import (
    breadth_signal,
    build_regime,
    combine,
    compute_breadth,
    sma,
    trend_signal,
    vix_signal,
    yield_curve_signal,
)


def _uptrend(n: int = 250) -> list[float]:
    return [100.0 + i * 0.1 for i in range(n)]


def _downtrend(n: int = 250) -> list[float]:
    return [125.0 - i * 0.1 for i in range(n)]


def test_sma_needs_full_window():
    assert sma([1.0, 2.0, 3.0], 3) == 2.0
    assert sma([1.0, 2.0], 3) is None
    assert sma([], 200) is None


def test_trend_signal_green_above_200d():
    assert trend_signal(_uptrend())["green"] is True
    assert trend_signal(_downtrend())["green"] is False
    assert trend_signal([100.0] * 10)["green"] is None  # too short -> honest absence
    assert trend_signal(None)["green"] is None


def test_vix_signal_bands():
    assert vix_signal(12.0)["green"] is True
    assert vix_signal(20.0)["green"] is True
    assert vix_signal(31.5)["green"] is False
    assert "erhöhte Nervosität" in vix_signal(31.5)["note"]
    assert vix_signal(None)["green"] is None


def test_breadth_signal_thresholds():
    assert breadth_signal(72.0)["green"] is True
    assert breadth_signal(45.0)["green"] is False
    assert "gemischt" in breadth_signal(45.0)["note"]
    assert "Korrektur" in breadth_signal(30.0)["note"]
    assert breadth_signal(None)["green"] is None


def test_yield_curve_signal_sign_only():
    assert yield_curve_signal(42.0, 13.0)["green"] is True
    inverted = yield_curve_signal(40.0, 53.0)
    assert inverted["green"] is False
    assert "invertiert" in inverted["note"]
    assert yield_curve_signal(None, 13.0)["green"] is None


def test_combine_green_count_levels():
    def sig(green):
        return {"key": "x", "label": "x", "green": green, "value": None, "note": ""}

    assert combine([sig(True)] * 4)["level"] == "green"
    assert combine([sig(True)] * 3 + [sig(False)])["level"] == "green"
    assert combine([sig(True)] * 2 + [sig(False)] * 2)["level"] == "yellow"
    assert combine([sig(True)] + [sig(False)] * 3)["level"] == "red"
    assert combine([sig(False)] * 4)["level"] == "red"


def test_combine_degrades_honestly_on_missing_signals():
    def sig(green):
        return {"key": "x", "label": "x", "green": green, "value": None, "note": ""}

    # Only two evaluable -> no traffic light, never a guess.
    result = combine([sig(True), sig(True), sig(None), sig(None)])
    assert result["level"] == "unknown"
    assert result["available"] == 2
    # Three evaluable is enough; the missing one never counts as green.
    result = combine([sig(True), sig(True), sig(True), sig(None)])
    assert result["level"] == "green"
    assert result["green_count"] == 3


def test_compute_breadth_skips_short_histories():
    universe = {
        "UP": _uptrend(),
        "DOWN": _downtrend(),
        "SHORT": [1.0, 2.0],  # skipped, not counted as either
    }
    assert compute_breadth(universe) == 50.0
    assert compute_breadth({}) is None
    assert compute_breadth({"SHORT": [1.0]}) is None


def test_build_regime_assembles_all_four():
    result = build_regime(_uptrend(), 18.0, 65.0, 42.0, 13.0)
    assert result["level"] == "green"
    assert [s["key"] for s in result["signals"]] == ["trend", "vix", "breadth", "curve"]


def test_breadth_signal_names_its_subject_honestly():
    note = build_regime(None, None, 72.0, None, None, breadth_subject="Sektoren")
    breadth = next(s for s in note["signals"] if s["key"] == "breadth")
    assert "72 % der Sektoren" in breadth["note"]


def test_api_regime_endpoint(tmp_path, monkeypatch):
    """Wiring: mocked yfinance legs + a real sector panel snapshot -> a green light with
    the breadth leg labelled as sector breadth. Result is cached per calendar day."""
    import pandas as pd
    from fastapi.testclient import TestClient

    import equity_scout.charts as charts_mod
    from equity_scout.api import create_app
    from equity_scout.data.etf_panel import save_snapshot
    from equity_scout.etf_universe import SECTOR_ETF_TICKERS
    from equity_scout.market import PricePanel

    legs = {"SPY": _uptrend(), "^VIX": [18.0], "^TNX": [42.0], "^IRX": [13.0]}
    calls: list[str] = []

    def fake_fetch(ticker):
        calls.append(ticker)
        values = legs[ticker]
        return list(range(len(values))), values

    monkeypatch.setattr(charts_mod, "fetch_year_closes", fake_fetch)
    panel = PricePanel(pd.DataFrame(
        {t: _uptrend() for t in SECTOR_ETF_TICKERS},
        index=pd.bdate_range("2020-01-01", periods=250),
    ))
    snapshot = str(tmp_path / "panel.csv")
    save_snapshot(panel, snapshot)

    client = TestClient(create_app(db_path=str(tmp_path / "api.db"), snapshot=snapshot))
    body = client.get("/api/regime").json()
    assert body["regime"]["level"] == "green"
    assert body["regime"]["available"] == 4
    breadth = next(s for s in body["regime"]["signals"] if s["key"] == "breadth")
    assert "Sektoren" in breadth["note"]
    fetches_after_first = len(calls)
    client.get("/api/regime")  # same day -> served from cache, no second fetch round
    assert len(calls) == fetches_after_first


def test_api_regime_degrades_honestly_offline(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import equity_scout.charts as charts_mod
    from equity_scout.api import create_app

    def dead(ticker):
        raise OSError("offline")

    monkeypatch.setattr(charts_mod, "fetch_year_closes", dead)
    client = TestClient(create_app(db_path=str(tmp_path / "api.db"),
                                   snapshot=str(tmp_path / "missing.csv")))
    body = client.get("/api/regime").json()
    assert body["regime"]["level"] == "unknown"
    assert body["regime"]["available"] == 0
