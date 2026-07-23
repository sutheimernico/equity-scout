"""Runner: the ML-bots' stock panel load path must be gap-tolerant (R3 follow-up).

Nightly forward_paper runs WITH --refresh and therefore WRITES data/prices/ml_bots_panel.csv;
run_autotrader runs right after it WITHOUT --refresh and just reads that snapshot back. If this
load path still trims to the common range (load_etf_panel -> clean_panel), a single young
watchlist ticker truncates every other stock's history in the SAVED file — R3's combined_panel
fix in run_autotrader.py (commit b01ab1f) then reads pre-trimmed data anyway, no matter how
gap-tolerant its own loader is.
"""
from __future__ import annotations

import pandas as pd

from equity_scout.data.etf_panel import clean_columns

import scripts.run_forward_paper as runner


def test_stock_panel_for_bots_survives_a_young_ticker(monkeypatch) -> None:
    old_index = pd.bdate_range("2024-01-02", periods=500)  # ~2 years
    young_index = old_index[-10:]  # joined 10 trading days ago
    raw = pd.DataFrame(index=old_index)
    raw["OLD"] = 100.0
    raw["YOUNG"] = float("nan")
    raw.loc[young_index, "YOUNG"] = 50.0

    def fake_load_etf_panel(tickers, **kwargs):  # noqa: ANN001, ANN201
        # The stock-bot panel must NOT be routed through here — this loader still applies the
        # destructive common-range trim (dropna(how="any") over ALL bot tickers).
        raise AssertionError("stock panel must use load_price_history, not load_etf_panel")

    monkeypatch.setattr(runner, "load_etf_panel", fake_load_etf_panel)
    monkeypatch.setattr(runner, "load_price_history", lambda tickers, **kwargs: clean_columns(raw))

    panel = runner.stock_panel_for_bots(["OLD", "YOUNG"], start="2007-01-01", refresh=False)

    assert panel.closes["OLD"].notna().sum() == len(old_index)  # full history kept, not trimmed
    young = panel.closes["YOUNG"]
    assert young.notna().sum() == len(young_index)  # young ticker's own short history present
    assert young.isna().sum() == len(old_index) - len(young_index)  # gap tolerated, not dropped
