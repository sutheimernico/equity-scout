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
        "horizon_days", "calibrated", "feature_means", "is_auc", "wfe",
        # v15 P3: always present, so "trained without evidence" is a recorded fact, not an
        # absent key that a later reader has to guess about.
        "evidence_features", "evidence_coverage_91d",
        # 2026-08-11: WHICH universe this model was measured on. Its absence is why the champion
        # defect stayed invisible for five weeks — the row recorded n_train but not the sample's
        # identity, so two AUCs from different universes looked comparable.
        "universe",
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


def test_run_train_entry_all_passes_presets_per_family_as_n_candidates(tmp_path, monkeypatch):
    """C2: the multiple-testing guard's candidate count is the number of presets competing against
    ONE family's champion (len(models)) — never the total across families (len(models) *
    len(families)). run_train_entry_all must wire len(models) into every promote_if_better call,
    regardless of how many families it loops over."""
    db = str(tmp_path / "train.db")
    monkeypatch.setattr(train_mod, "walk_forward_evaluate", lambda *a, **k: _metrics(0.65))
    seen_n_candidates = []
    real_promote = train_mod.promote_if_better

    def _spy_promote(*args, **kwargs):
        seen_n_candidates.append(kwargs["n_candidates"])
        return real_promote(*args, **kwargs)

    monkeypatch.setattr(train_mod, "promote_if_better", _spy_promote)

    train_mod.run_train_entry_all(
        db, panel=_panel_with_vol(), tickers=["AAA", "BBB"], now=NOW,
        models=("random_forest", "elastic_net"), families=("entry", "entry_short"),
    )

    # 2 presets x 2 families = 4 calls, each with n_candidates == 2 (presets PER family, not 4)
    assert seen_n_candidates == [2, 2, 2, 2]


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


def test_train_cli_explains_why_walk_forward_yielded_zero_splits(tmp_path, capsys):
    """v9 Q5: every nightly preset printed 'Splits=0' without saying why — the honest line
    names the cause (too few monthly sample dates for one purged split) and the remedy
    (more panel history, never looser split parameters)."""
    db = str(tmp_path / "train.db")
    result = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)

    assert result["metrics"]["n_splits_used"] == 0
    out = capsys.readouterr().out
    assert "Sample-Stichtage" in out
    assert "Walk-Forward" in out


def test_filter_short_history_keeps_span_and_logs_exclusion(capsys):
    """v13 Q1: one young watchlist ticker must not trim the training panel to its own
    listing date — it is excluded (logged with the rule) and the survivors keep the span."""
    import numpy as np

    idx = pd.bdate_range("2019-01-01", periods=1000)
    closes = pd.DataFrame({"SPY": 100.0, "AAA": 50.0}, index=idx)
    closes["IPO"] = np.nan
    closes.loc[idx[900]:, "IPO"] = 20.0
    panel = train_mod._filter_short_history(closes)
    assert list(panel.closes.columns) == ["SPY", "AAA"]
    assert panel.dates[0] == idx[0]  # full span kept
    out = capsys.readouterr().out
    assert "Ausgeschlossen IPO" in out
    assert idx[900].date().isoformat() in out  # history start named


def test_filter_short_history_all_young_raises_instead_of_empty_panel():
    """v13 Q1 edge: if the filter leaves nothing but the benchmark, training must abort
    loudly — a silent stock-less panel would 'train' on nothing."""
    import numpy as np
    import pytest

    idx = pd.bdate_range("2019-01-01", periods=1000)
    closes = pd.DataFrame({"SPY": 100.0}, index=idx)
    closes["IPO1"] = np.nan
    closes.loc[idx[900]:, "IPO1"] = 20.0
    closes["IPO2"] = np.nan
    closes.loc[idx[950]:, "IPO2"] = 30.0
    with pytest.raises(RuntimeError, match="ohne Aktien-Ticker"):
        train_mod._filter_short_history(closes)


def test_plain_run_records_that_no_evidence_features_were_used(tmp_path):
    db = str(tmp_path / "train.db")
    result = run_train_entry(db, panel=_panel(), tickers=["AAA", "BBB"], now=NOW)
    assert result["metrics"]["evidence_features"] == []
    assert result["metrics"]["evidence_coverage_91d"] is None


def test_evidence_run_records_columns_and_coverage(tmp_path, capsys):
    """The coverage share is a first-class output: a feature set that is zero on ~every
    training row cannot possibly beat the champion, and must say so before anyone believes a
    promotion."""
    from datetime import date

    from equity_scout.ml.evidence_features import EVIDENCE_FEATURE_COLUMNS, EvidenceIndex

    db = str(tmp_path / "train.db")
    index = EvidenceIndex({"AAA": [(date(2020, 6, 1), 7)]})
    result = run_train_entry(
        db, panel=_panel_with_vol(), tickers=["AAA", "BBB"], now=NOW,
        family="entry_tb", barrier_config=BarrierConfig(), evidence_index=index,
    )
    assert result["metrics"]["evidence_features"] == list(EVIDENCE_FEATURE_COLUMNS)
    assert 0.0 < result["metrics"]["evidence_coverage_91d"] < 1.0
    assert "Evidence-Features aktiv" in capsys.readouterr().out


def test_evidence_variant_only_doubles_entry_tb_and_its_candidate_count(tmp_path, monkeypatch):
    """Ruling 1: the evidence block competes inside entry_tb only. Ruling 7: the extra
    challengers must raise that family's multiple-testing count — testing twice as many
    presets against the same champion without raising the bar is exactly the noise-promotion
    hole `_min_auc_delta` exists to close."""
    from datetime import date

    from equity_scout.ml.evidence_features import EvidenceIndex
    from scripts.run_train_entry import run_train_entry_all

    calls: list[tuple] = []

    def _fake(db_path, **kwargs):
        calls.append(
            (kwargs["family"], kwargs["model"], kwargs["evidence_index"] is not None,
             kwargs["n_candidates"])
        )
        return {"version": len(calls), "metrics": {}, "promoted": False, "n_train": 1}

    monkeypatch.setattr(train_mod, "run_train_entry", _fake)
    run_train_entry_all(
        str(tmp_path / "train.db"), panel=_panel(), tickers=["AAA"], now=NOW,
        models=("random_forest", "elastic_net"),
        evidence_index=EvidenceIndex({"AAA": [(date(2020, 6, 1), 7)]}),
    )

    by_family: dict[str, list[tuple]] = {}
    for family, model, with_evidence, n_candidates in calls:
        by_family.setdefault(family, []).append((model, with_evidence, n_candidates))

    assert [c[1] for c in by_family["entry"]] == [False, False]
    assert {c[2] for c in by_family["entry"]} == {2}  # unchanged: 2 presets, 1 variant
    assert [c[1] for c in by_family["entry_short"]] == [False, False]
    assert sorted(c[1] for c in by_family["entry_tb"]) == [False, False, True, True]
    assert {c[2] for c in by_family["entry_tb"]} == {4}  # 2 presets x 2 variants


def test_cli_without_the_flag_loads_no_evidence_index(tmp_path, monkeypatch):
    """The nightly chain calls `run_train_entry.py` bare — it must stay evidence-free."""
    seen: dict = {}

    monkeypatch.setattr(train_mod, "_load_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(
        train_mod, "run_train_entry_all",
        lambda db, **kwargs: seen.update(kwargs) or [],
    )
    monkeypatch.setattr(sys, "argv", ["run_train_entry.py", "--db", str(tmp_path / "x.db")])
    assert main() == 0
    assert seen["evidence_index"] is None
