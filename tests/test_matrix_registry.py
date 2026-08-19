"""Tests for the plateau register and the matrix strategy (trader #3, v17).

Two properties are load-bearing and tested hardest:

1. The hold-out can be spent exactly ONCE. A second opening must be refused, because a reopened
   hold-out is just another search window and this project has no clean data left after it.
2. An unqualified register trades NOTHING. The failure mode to avoid is a strategy that, absent
   evidence, quietly falls back on something plausible.
"""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.matrix.registry import (
    STAGE_FOUND,
    STAGE_QUALIFIED,
    STAGE_REJECTED,
    bootstrap_verdict,
    fingerprint,
    holdout_is_open,
    holdout_log,
    init_matrix_db,
    load_all,
    load_qualified,
    record_holdout_result,
    record_plateau,
    register_holdout_opening,
)
from equity_scout.strategies.matrix_strategy import (
    MAX_GROSS_EXPOSURE,
    MAX_WEIGHT_PER_TICKER,
    MatrixStrategy,
)

NOW = "2026-08-19T20:00:00+00:00"


def _plateau(signal: str = "drop2pct", cost: float = 10.0) -> dict:
    return {
        "signal": signal, "asset_class": "stocks", "context": "none", "cost_bps": cost,
        "thresholds": [-0.02, -0.03], "slices": ["1D"], "hold_bars": [2, 3],
        "size": 5, "median_net_bp": 32.1, "worst_net_bp": 18.0, "worst_t": 2.4,
        "total_trades": 1672,
    }


def _boot(t: float = 3.5, p: float = 0.001, n: int = 1672, ci_low: float = 8.0) -> dict:
    return {"n_trades": n, "n_blocks": 84, "mean_net_bp": 32.1, "std_error_bp": 9.2,
            "t": t, "p_value": p, "ci_low_bp": ci_low, "ci_high_bp": 60.0,
            "naive_t": 3.04, "inflation_factor": 1.9}


# --- the hold-out is a consumable ---------------------------------------------------------

def test_holdout_can_be_opened_exactly_once(tmp_path):
    path = tmp_path / "matrix.db"
    init_matrix_db(path)
    assert holdout_is_open(path, "2023-01-01")

    register_holdout_opening(path, window_start="2023-01-01", now=NOW,
                             hypothesis="drop2pct trägt auch 2023-2025",
                             fingerprints=["fp-1"])
    assert not holdout_is_open(path, "2023-01-01")

    with pytest.raises(RuntimeError, match="verbraucht"):
        register_holdout_opening(path, window_start="2023-01-01", now=NOW,
                                 hypothesis="nochmal probieren", fingerprints=["fp-2"])


def test_holdout_hypothesis_is_recorded_before_the_result(tmp_path):
    """A hypothesis written after the outcome is not a hypothesis."""
    path = tmp_path / "matrix.db"
    register_holdout_opening(path, window_start="2023-01-01", now=NOW,
                             hypothesis="H1", fingerprints=["fp-1"])
    entry = holdout_log(path)[0]
    assert entry["hypothesis"] == "H1"
    assert entry["result_json"] is None  # claimed first, filled later

    record_holdout_result(path, window_start="2023-01-01", result={"survived": 0})
    assert holdout_log(path)[0]["result_json"] is not None


def test_a_different_window_is_still_available(tmp_path):
    path = tmp_path / "matrix.db"
    register_holdout_opening(path, window_start="2023-01-01", now=NOW,
                             hypothesis="H1", fingerprints=[])
    assert holdout_is_open(path, "2026-01-01")


# --- the register ---------------------------------------------------------------------------

def test_fingerprint_is_stable_across_reruns_but_distinguishes_sides():
    plateau = _plateau()
    assert fingerprint(plateau) == fingerprint(dict(plateau))
    assert fingerprint(plateau, side="short") != fingerprint(plateau, side="long")


def test_fingerprint_ignores_statistics_so_a_remeasure_is_not_a_new_finding():
    """Re-measuring the same rule on more data must not smuggle it in as a second finding."""
    first = _plateau()
    remeasured = {**_plateau(), "median_net_bp": 41.0, "total_trades": 2500, "size": 7}
    assert fingerprint(first) == fingerprint(remeasured)


def test_stages_advance_one_record_instead_of_duplicating(tmp_path):
    path = tmp_path / "matrix.db"
    key = record_plateau(path, _plateau(), now=NOW, stage=STAGE_FOUND)
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot())
    rows = load_all(path)
    assert len(rows) == 1
    assert rows[0]["stage"] == STAGE_QUALIFIED and rows[0]["fingerprint"] == key


def test_only_qualified_plateaus_are_loaded_for_trading(tmp_path):
    path = tmp_path / "matrix.db"
    record_plateau(path, _plateau("a"), now=NOW, stage=STAGE_FOUND, bootstrap=_boot())
    record_plateau(path, _plateau("b"), now=NOW, stage=STAGE_REJECTED,
                   rejected_reason="Bootstrap-t 1.63 unter 2.0")
    record_plateau(path, _plateau("c"), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot())
    assert [p.signal for p in load_qualified(path)] == ["c"]


def test_qualified_without_statistics_cannot_trade(tmp_path):
    """A row that lost its bootstrap numbers cannot be sized, so it must not be traded."""
    path = tmp_path / "matrix.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=None)
    assert load_qualified(path) == []


def test_rejections_are_kept_as_evidence(tmp_path):
    path = tmp_path / "matrix.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_REJECTED,
                   rejected_reason="95-%-Intervall enthält die Null")
    rejected = load_all(path, stage=STAGE_REJECTED)
    assert rejected[0]["rejected_reason"] == "95-%-Intervall enthält die Null"


def test_missing_db_is_not_an_error(tmp_path):
    """A machine that never ran the matrix reports 'nothing qualified', not a crash."""
    assert load_qualified(tmp_path / "absent.db") == []
    assert load_all(tmp_path / "absent.db") == []
    assert holdout_is_open(tmp_path / "absent.db", "2023-01-01")


def test_unknown_stage_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="stage"):
        record_plateau(tmp_path / "m.db", _plateau(), now=NOW, stage="probably_fine")


# --- the bootstrap gate --------------------------------------------------------------------

def test_bootstrap_verdict_accepts_a_strong_result():
    passes, reason = bootstrap_verdict(_boot())
    assert passes and reason == "bestanden"


def test_bootstrap_verdict_rejects_the_measured_borderline_case():
    """The real 2026-08-19 measurement: t 1.63, CI [-4.6, +73.1]. Must not qualify."""
    passes, reason = bootstrap_verdict(
        {**_boot(t=1.63, p=0.047, ci_low=-4.6)})
    assert not passes
    assert "1.63" in reason


def test_bootstrap_verdict_distinguishes_unmeasurable_from_rejected():
    passes, reason = bootstrap_verdict({**_boot(), "t": None, "p_value": None})
    assert not passes
    assert "nicht messbar" in reason


def test_bootstrap_verdict_rejects_a_zero_crossing_interval():
    passes, reason = bootstrap_verdict(_boot(ci_low=-1.0))
    assert not passes and "Null" in reason


def test_bootstrap_verdict_rejects_thin_samples():
    passes, reason = bootstrap_verdict(_boot(n=120))
    assert not passes and "120" in reason


def test_bootstrap_verdict_rejects_negative_net():
    passes, reason = bootstrap_verdict({**_boot(), "mean_net_bp": -5.0})
    assert not passes and "positiv" in reason


# --- the strategy ---------------------------------------------------------------------------

class _FakeMarket:
    tickers = ["AAA", "BBB", "CCC"]
    as_of = pd.Timestamp("2026-08-19", tz="UTC")


def test_empty_register_trades_nothing(tmp_path):
    """The important negative: no evidence means no position, not a plausible default."""
    strategy = MatrixStrategy(db_path=str(tmp_path / "m.db"),
                              signal_fires=lambda *a: True)
    assert strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket()) == []
    assert not strategy.ready


def test_qualified_plateau_produces_weights(tmp_path):
    path = tmp_path / "m.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot(t=8.0))
    strategy = MatrixStrategy(db_path=str(path), universe=["AAA", "BBB"],
                              signal_fires=lambda plateau, ticker, as_of, market: ticker == "AAA")
    weights = strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket())
    assert [w.ticker for w in weights] == ["AAA"]
    assert weights[0].side == "long"
    assert 0 < weights[0].weight <= MAX_WEIGHT_PER_TICKER
    assert strategy.ready


def test_short_plateau_produces_a_short_weight(tmp_path):
    path = tmp_path / "m.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED,
                   side="short", bootstrap=_boot(t=8.0))
    strategy = MatrixStrategy(db_path=str(path), universe=["AAA"],
                              signal_fires=lambda *a: True)
    weights = strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket())
    assert weights[0].side == "short"
    assert weights[0].signed_weight < 0


def test_uncertain_plateau_gets_a_smaller_position(tmp_path):
    """Sizing follows the bootstrap t: uncertainty shrinks the position, never grows it."""
    confident = tmp_path / "confident.db"
    shaky = tmp_path / "shaky.db"
    record_plateau(confident, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot(t=8.0))
    record_plateau(shaky, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot(t=2.1))

    def weight_of(path):
        s = MatrixStrategy(db_path=str(path), universe=["AAA"], signal_fires=lambda *a: True)
        return s.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket())[0].weight

    assert weight_of(shaky) < weight_of(confident)


def test_gross_exposure_never_exceeds_one(tmp_path):
    """No combination of findings may create leverage — the protection chain assumes 1x."""
    path = tmp_path / "m.db"
    for index in range(12):
        record_plateau(path, _plateau(signal=f"sig{index}"), now=NOW,
                       stage=STAGE_QUALIFIED, bootstrap=_boot(t=8.0))
    universe = [f"T{i}" for i in range(30)]
    strategy = MatrixStrategy(db_path=str(path), universe=universe,
                              signal_fires=lambda *a: True)
    weights = strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket())
    assert sum(w.weight for w in weights) <= MAX_GROSS_EXPOSURE + 1e-9
    assert all(w.weight <= MAX_WEIGHT_PER_TICKER + 1e-9 for w in weights)


def test_no_firing_signal_means_no_position(tmp_path):
    path = tmp_path / "m.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot())
    strategy = MatrixStrategy(db_path=str(path), universe=["AAA"],
                              signal_fires=lambda *a: False)
    assert strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket()) == []


def test_missing_signal_evaluator_trades_nothing(tmp_path):
    """Without an evaluator the strategy cannot know what fires — it must abstain, not guess."""
    path = tmp_path / "m.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot())
    strategy = MatrixStrategy(db_path=str(path), universe=["AAA"], signal_fires=None)
    assert strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket()) == []


def test_dust_positions_are_dropped(tmp_path):
    path = tmp_path / "m.db"
    record_plateau(path, _plateau(), now=NOW, stage=STAGE_QUALIFIED, bootstrap=_boot(t=2.0))
    universe = [f"T{i}" for i in range(200)]
    strategy = MatrixStrategy(db_path=str(path), universe=universe,
                              signal_fires=lambda *a: True)
    weights = strategy.decide(pd.Timestamp("2026-08-19", tz="UTC"), _FakeMarket())
    assert all(w.weight > 0.0005 for w in weights)
