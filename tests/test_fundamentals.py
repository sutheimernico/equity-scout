"""Fundamentals mapper + fetch-seam tests. Pure `from_info`; no network anywhere —
the live `fetch_fundamentals` is exercised only via a monkeypatched raising yfinance
stub asserting the honest all-None fallback."""
from __future__ import annotations

import sys
import types

import pytest

from equity_scout.fundamentals import Fundamentals, fetch_fundamentals, from_info


def test_from_info_maps_all_fields():
    fund = from_info(
        {
            "trailingPE": 18.4,
            "targetMeanPrice": 210.5,
            "numberOfAnalystOpinions": 27,
            "currency": "USD",
        }
    )
    assert fund == Fundamentals(
        trailing_pe=18.4, analyst_target=210.5, analyst_count=27, currency="USD"
    )


def test_from_info_empty_is_all_none():
    assert from_info({}) == Fundamentals(None, None, None, None)


@pytest.mark.parametrize("bad", [None, 0, -5.0, float("nan"), float("inf"), "n/a"])
def test_from_info_rejects_bad_trailing_pe(bad):
    assert from_info({"trailingPE": bad}).trailing_pe is None


@pytest.mark.parametrize("bad", [None, 0, -1.0, float("nan"), float("inf"), "x"])
def test_from_info_rejects_bad_analyst_target(bad):
    assert from_info({"targetMeanPrice": bad}).analyst_target is None


@pytest.mark.parametrize(
    "raw, expected",
    [(None, None), (0, None), (-2, None), ("x", None), (5, 5), ("3", 3)],
)
def test_from_info_analyst_count(raw, expected):
    assert from_info({"numberOfAnalystOpinions": raw}).analyst_count == expected


@pytest.mark.parametrize("raw, expected", [("EUR", "EUR"), ("", None), (None, None)])
def test_from_info_currency(raw, expected):
    assert from_info({"currency": raw}).currency == expected


def test_fetch_fundamentals_returns_all_none_when_yfinance_raises(monkeypatch):
    """The fetch seam must never raise into the pitch path — a broken yfinance
    degrades to an honest all-None Fundamentals (no network in this test)."""
    fake_yf = types.ModuleType("yfinance")

    def boom(ticker):
        raise RuntimeError("network down")

    fake_yf.Ticker = boom
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    assert fetch_fundamentals("AAPL") == Fundamentals(None, None, None, None)
