"""Resolve-CLI tests: resolve due predictions via an injected fetch, leave not-yet-due open."""
from __future__ import annotations

import sys

import pandas as pd
import pytest

import scripts.run_resolve_predictions as resolve_mod
from equity_scout.market import PricePanel
from equity_scout.ml.prediction_ledger import log_predictions, resolved_stats
from scripts.run_resolve_predictions import main, run_resolve_predictions

HORIZON = 20


def _panel() -> PricePanel:
    """Business-day panel where AAA outruns SPY over every forward horizon → positive rel return."""
    idx = pd.bdate_range("2025-06-01", periods=400)
    n = len(idx)
    data = {
        "SPY": [100.0 * 1.0002**i for i in range(n)],
        "AAA": [100.0 * 1.0008**i for i in range(n)],
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def _fetch(panel: PricePanel):
    return lambda tickers, start: panel  # DI seam: ignores the window, returns the synthetic panel


def test_resolve_cli_resolves_due_and_leaves_not_yet_due_open(tmp_path):
    db = str(tmp_path / "led.db")
    # Logged 2026-01-05 → resolve_after 2026-01-25: DUE at the run time below.
    log_predictions(
        db, model_version=1, scored=[("AAA", 80, {"mkt_vol": 0.1})],
        now="2026-01-05T00:00:00+00:00", horizon_days=HORIZON,
    )
    # Logged 2026-05-01 → resolve_after 2026-05-21: NOT yet due at the run time below.
    log_predictions(
        db, model_version=1, scored=[("AAA", 40, {"mkt_vol": 0.1})],
        now="2026-05-01T00:00:00+00:00", horizon_days=HORIZON,
    )

    result = run_resolve_predictions(
        db, now="2026-03-01T00:00:00+00:00", fetch_prices=_fetch(_panel())
    )

    assert result["resolved"] == 1
    assert result["still_open"] == 1  # the 2026-05-01 prediction is not yet due
    stats = resolved_stats(db)
    assert stats["n_resolved"] == 1 and stats["n_open"] == 1


def test_resolve_cli_no_due_predictions_is_a_noop(tmp_path):
    db = str(tmp_path / "led.db")
    log_predictions(
        db, model_version=1, scored=[("AAA", 80, {"mkt_vol": 0.1})],
        now="2026-05-01T00:00:00+00:00", horizon_days=HORIZON,
    )
    result = run_resolve_predictions(
        db, now="2026-05-02T00:00:00+00:00", fetch_prices=_fetch(_panel())
    )
    assert result == {"resolved": 0, "still_open": 1}


def test_resolve_main_happy_path_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "led.db")
    # created well in the past so it is due against the real wall clock main() reads.
    log_predictions(
        db, model_version=1, scored=[("AAA", 80, {"mkt_vol": 0.1})],
        now="2026-01-05T00:00:00+00:00", horizon_days=HORIZON,
    )
    monkeypatch.setattr(resolve_mod, "_fetch_price_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(sys, "argv", ["run_resolve_predictions.py", "--db", db])

    assert main() == 0
    assert resolved_stats(db)["n_resolved"] == 1
    assert "Aufgelöst" in capsys.readouterr().out


def test_panel_that_starts_after_created_at_resolves_to_none():
    """A panel whose first row lies AFTER the prediction date must not silently measure a
    shifted window (regression 2026-08-05: clean_panel/young tickers moved the panel start)."""
    truncated = PricePanel(_panel().closes.loc[pd.Timestamp("2026-01-20"):])
    assert resolve_mod._realized_relative_return(
        truncated, "AAA", "2026-01-05T00:00:00+00:00", 20
    ) is None


def test_price_panel_loader_is_column_wise(monkeypatch):
    """Prediction tickers are global (5101.T, CQR.AX, PETR4.SA) — the common-range trim of
    load_etf_panel/clean_panel would cut every history at the youngest ticker's first bar."""
    import equity_scout.data.etf_panel as panel_mod
    seen = {}
    monkeypatch.setattr(
        panel_mod, "load_price_history",
        lambda tickers, **kw: seen.update(kw) or PricePanel(pd.DataFrame()),
    )
    monkeypatch.setattr(
        panel_mod, "load_etf_panel",
        lambda *a, **k: pytest.fail("resolver must not use the common-range loader"),
    )
    resolve_mod._fetch_price_panel(["AAA", "SPY"], "2026-01-01")
    assert seen["snapshot"] == resolve_mod.RESOLVE_SNAPSHOT
    assert seen["refresh"] is True
