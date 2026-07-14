"""Train-CLI tests: backfill -> walk-forward -> register -> promote, offline (panel injected)."""
from __future__ import annotations

import sys

import pandas as pd

import scripts.run_train_entry as train_mod
from equity_scout.market import PricePanel
from equity_scout.ml.labeling import BarrierConfig
from equity_scout.ml.model_registry import entry_champion, registry_summary
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


def _panel_with_vol(n: int = 500) -> PricePanel:
    """Like `_panel()` but with a small daily oscillation added. `_panel()`'s series have a pure
    geometric (constant daily return) growth, so their trailing realized vol is exactly 0 — the
    entry_tb label rejects a zero-width barrier (see `triple_barrier_entry_label`), so every
    entry_tb row would be dropped on the plain `_panel()`."""
    idx = pd.bdate_range("2019-01-01", periods=n)
    data = {
        "SPY": [100.0 * 1.0004**i + 0.05 * ((-1) ** i) for i in range(n)],
        "AAA": [100.0 * 1.0006**i + 0.05 * ((-1) ** i) for i in range(n)],
        "BBB": [100.0 * 1.0002**i + 0.05 * ((-1) ** i) for i in range(n)],
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def _metrics(auc: float) -> dict:
    return {
        "auc": auc, "brier": 0.2, "rank_ic": 0.1,
        # MIN_OOS_N-clearing so these mocked runs exercise the AUC-delta gate, not the OOS-floor
        # gate (see test_train_cli_first_run_with_insufficient_oos_data_does_not_promote for that).
        "n_oos": 250, "n_splits_used": 2, "feature_importance": {},
    }


def test_train_cli_first_run_with_insufficient_oos_data_does_not_promote(tmp_path, capsys):
    """The real (unmocked) walk-forward on this tiny 2-ticker/~2-year panel never clears
    MIN_OOS_N (F2) — the registry correctly withholds a champion rather than bootstrapping one off
    an undemonstrated edge, even though it is the first-ever registered model."""
    db = str(tmp_path / "train.db")
    result = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)

    assert result["version"] == 1
    assert result["promoted"] is False  # F2 baseline-quality gate: too few OOS rows
    assert result["n_train"] > 0
    assert set(result["metrics"]) == {
        "auc", "brier", "rank_ic", "n_oos", "n_splits_used", "feature_importance",
        "horizon_days", "calibrated", "feature_means",
    }
    assert entry_champion(db) is None

    out = capsys.readouterr().out
    assert "Out-of-Sample" in out
    assert "Als Champion übernommen: nein" in out


def test_train_cli_second_run_on_same_insufficient_data_still_has_no_champion(tmp_path):
    """Two identical runs on the tiny panel each register a challenger version, but neither clears
    F2's baseline-quality gate — repeated retrains without enough OOS history must never sneak in
    a champion."""
    db = str(tmp_path / "train.db")
    panel = _panel()
    first = run_train_entry(db, panel=panel, tickers=["AAA", "BBB"], now=NOW)
    second = run_train_entry(db, panel=panel, tickers=["AAA", "BBB"], now=NOW)

    assert first["version"] == 1 and first["promoted"] is False
    assert second["version"] == 2 and second["promoted"] is False
    assert entry_champion(db) is None
    assert [v["version"] for v in registry_summary(db)["versions"]] == [2, 1]


def test_train_cli_promotes_strictly_better_challenger(tmp_path, monkeypatch):
    """Champion logic end-to-end: adequate OOS data + a strictly higher OOS AUC displaces v1."""
    db = str(tmp_path / "train.db")
    scores = iter([_metrics(0.60), _metrics(0.80)])
    monkeypatch.setattr(train_mod, "walk_forward_evaluate", lambda *a, **k: next(scores))

    first = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)
    second = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)

    assert first["promoted"] is True  # clears baseline quality → first champion
    assert second["promoted"] is True  # delta 0.20 >= MIN_AUC_DELTA → displaces v1
    assert entry_champion(db)[0] == 2


def test_train_main_happy_path_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "train.db")
    monkeypatch.setattr(train_mod, "_load_panel", lambda tickers, start: _panel())
    # Real backfill on this tiny panel never clears MIN_OOS_N (see the dedicated test above); mock
    # adequate OOS metrics here so this smoke test still exercises the "champion gets set" path.
    monkeypatch.setattr(train_mod, "walk_forward_evaluate", lambda *a, **k: _metrics(0.65))
    monkeypatch.setattr(sys, "argv", ["run_train_entry.py", "--db", db, "--tickers", "AAA,BBB"])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Out-of-Sample" in out
    assert entry_champion(db) is not None


# --- entry_tb: nightly-chain wiring + family separation ---
def test_run_train_entry_all_default_families_include_entry_tb(tmp_path):
    db = str(tmp_path / "train.db")
    results = train_mod.run_train_entry_all(
        db, panel=_panel_with_vol(), tickers=["AAA", "BBB"], now=NOW, models=("random_forest",)
    )
    assert len(results) == 3  # entry, entry_short, entry_tb × 1 model — default families
    tb_result = results[2]
    assert tb_result["n_train"] > 0
    assert tb_result["metrics"]["barrier_config"] == BarrierConfig().as_dict()


def test_entry_tb_champion_promotion_is_independent_of_entry_family(tmp_path, monkeypatch):
    """Family separation (F3): a strong entry_tb challenger must never become the `entry` family's
    champion, and vice versa — each family gates its own promotion off its own OOS metric."""
    db = str(tmp_path / "train.db")
    scores = iter([_metrics(0.60), _metrics(0.85)])
    monkeypatch.setattr(train_mod, "walk_forward_evaluate", lambda *a, **k: next(scores))

    entry_result = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW, family="entry")
    tb_result = run_train_entry(
        db, panel=_panel_with_vol(), tickers=["AAA", "BBB"], now=NOW, family="entry_tb"
    )

    assert entry_result["promoted"] is True
    assert tb_result["promoted"] is True
    assert entry_champion(db, family="entry")[0] == entry_result["version"]
    assert entry_champion(db, family="entry_tb")[0] == tb_result["version"]
    tb_metrics = entry_champion(db, family="entry_tb")[2]
    assert tb_metrics["barrier_config"] == BarrierConfig().as_dict()
    # Single source of truth: run_train_entry was called WITHOUT a horizon override (so the
    # HORIZON_DAYS default was in play) — the trained/persisted horizon must still be the barrier
    # config's, never the default. A mismatch here means the stored config lies about the horizon
    # the model was actually trained on, and the target/stop derivation would build on that lie.
    assert tb_metrics["horizon_days"] == tb_metrics["barrier_config"]["horizon_days"]


def test_train_main_default_family_trains_entry_tb_too(tmp_path, monkeypatch):
    """The nightly chain calls run_train_entry.py with no --family arg — its default ("all") must
    include entry_tb so it actually gets retrained every night, not just entry/entry_short."""
    db = str(tmp_path / "train.db")
    monkeypatch.setattr(train_mod, "_load_panel", lambda tickers, start: _panel_with_vol())
    monkeypatch.setattr(train_mod, "walk_forward_evaluate", lambda *a, **k: _metrics(0.65))
    monkeypatch.setattr(sys, "argv", ["run_train_entry.py", "--db", db, "--tickers", "AAA,BBB"])

    assert main() == 0

    assert entry_champion(db, family="entry") is not None
    assert entry_champion(db, family="entry_short") is not None
    assert entry_champion(db, family="entry_tb") is not None
