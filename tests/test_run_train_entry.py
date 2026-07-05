"""Train-CLI tests: backfill -> walk-forward -> register -> promote, offline (panel injected)."""
from __future__ import annotations

import sys

import pandas as pd

import scripts.run_train_entry as train_mod
from equity_scout.market import PricePanel
from equity_scout.ml.model_registry import champion, registry_summary
from scripts.run_train_entry import main, run_train_entry

NOW = "2026-07-05T12:00:00+00:00"


def _panel(n: int = 500) -> PricePanel:
    """SPY benchmark; AAA beats it over every horizon (label 1), BBB lags it (label 0) — a
    learnable, deterministic backfill (no randomness, so two runs produce identical OOS metrics)."""
    idx = pd.bdate_range("2019-01-01", periods=n)
    data = {
        "SPY": [100.0 * 1.0004**i for i in range(n)],
        "AAA": [100.0 * 1.0006**i for i in range(n)],  # steeper → beats SPY
        "BBB": [100.0 * 1.0002**i for i in range(n)],  # flatter → lags SPY
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def _metrics(auc: float) -> dict:
    return {
        "auc": auc, "brier": 0.2, "rank_ic": 0.1,
        "n_oos": 10, "n_splits_used": 2, "feature_importance": {},
    }


def test_train_cli_builds_evaluates_registers_and_promotes_first(tmp_path, capsys):
    db = str(tmp_path / "train.db")
    result = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)

    assert result["version"] == 1
    assert result["promoted"] is True  # first model bootstraps the champion regardless of metric
    assert result["n_train"] > 0
    assert set(result["metrics"]) == {
        "auc", "brier", "rank_ic", "n_oos", "n_splits_used", "feature_importance"
    }
    got = champion(db)
    assert got is not None and got[0] == 1

    out = capsys.readouterr().out
    assert "Out-of-Sample" in out
    assert "Als Champion übernommen: ja" in out


def test_train_cli_second_run_registers_v2_and_promotes_only_if_better(tmp_path):
    db = str(tmp_path / "train.db")
    panel = _panel()
    first = run_train_entry(db, panel=panel, tickers=["AAA", "BBB"], now=NOW)
    second = run_train_entry(db, panel=panel, tickers=["AAA", "BBB"], now=NOW)

    assert first["version"] == 1 and first["promoted"] is True
    assert second["version"] == 2
    # identical data → identical OOS metric → NOT strictly better → champion stays v1
    assert second["promoted"] is False
    assert champion(db)[0] == 1
    assert [v["version"] for v in registry_summary(db)["versions"]] == [2, 1]


def test_train_cli_promotes_strictly_better_challenger(tmp_path, monkeypatch):
    """Champion logic end-to-end: a challenger with a strictly higher OOS AUC displaces v1."""
    db = str(tmp_path / "train.db")
    scores = iter([_metrics(0.60), _metrics(0.80)])
    monkeypatch.setattr(train_mod, "walk_forward_evaluate", lambda *a, **k: next(scores))

    run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)
    second = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)

    assert second["promoted"] is True
    assert champion(db)[0] == 2


def test_train_main_happy_path_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "train.db")
    monkeypatch.setattr(train_mod, "_load_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(sys, "argv", ["run_train_entry.py", "--db", db, "--tickers", "AAA,BBB"])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Out-of-Sample" in out
    assert champion(db) is not None
