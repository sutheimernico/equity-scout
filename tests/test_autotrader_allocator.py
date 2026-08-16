"""Allocator: anchor fallback, Sharpe tilt ordering, floor/cap bounds, walk-forward guard."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.autotrader_allocator import (
    SleeveAllocation,
    blend_weights,
    returns_before,
    sleeve_return_frame,
)
from equity_scout.forward_paper import ForwardValuation
from equity_scout.forward_storage import append_valuation, init_forward_db


def _returns(days: int, columns: dict[str, float], seed: int = 7) -> pd.DataFrame:
    """Synthetic daily returns: per-column constant drift plus small deterministic noise."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-01-02", periods=days)
    data = {
        name: drift + rng.normal(0.0, 0.002, size=days) for name, drift in columns.items()
    }
    return pd.DataFrame(data, index=index)


def test_too_little_overlap_falls_back_to_equal_weight() -> None:
    returns = _returns(30, {"a": 0.001, "b": -0.001})
    allocation = blend_weights(returns, ["a", "b"])
    assert allocation.mode == "anchor"
    assert allocation.weights == {"a": 0.5, "b": 0.5}
    assert allocation.sharpes == {}


def test_a_new_sleeve_keeps_its_anchor_share_without_freezing_the_others() -> None:
    """A newcomer must not be punished for being new — and must not freeze the rest either.

    Until 2026-08-16 the whole allocation dropped to equal weight whenever ONE sleeve lacked
    history, and the overlap was counted across all sleeves at once. Live consequence: the
    depot took on four new lanes on 2026-08-14, which reset the shared clock to five
    observations and pushed the first performance-based weighting from October to November.
    Every future intake would have pushed it again.
    """
    returns = _returns(120, {"winner": 0.002, "loser": -0.002})
    returns["brand_new"] = pd.NA
    returns.iloc[-4:, returns.columns.get_loc("brand_new")] = 0.001
    allocation = blend_weights(returns, ["winner", "loser", "brand_new"])
    assert allocation.mode == "tilt"
    # The newcomer sits at the equal-weight anchor: neither rewarded nor punished.
    assert allocation.weights["brand_new"] == pytest.approx(1 / 3, abs=0.02)
    # ...while the two with a track record are ranked against each other.
    assert allocation.weights["winner"] > allocation.weights["loser"]
    assert sum(allocation.weights.values()) == pytest.approx(1.0)
    assert "brand_new" not in allocation.sharpes  # nothing measured, nothing claimed


def test_all_sleeves_young_still_falls_back_to_equal_weight() -> None:
    """With fewer than two measurable sleeves there is no ranking to make."""
    returns = _returns(120, {"a": 0.001})
    returns["b"] = pd.NA
    returns.iloc[-3:, returns.columns.get_loc("b")] = 0.001
    allocation = blend_weights(returns, ["a", "b"])
    assert allocation.mode == "anchor"
    assert allocation.weights == pytest.approx({"a": 0.5, "b": 0.5})


def test_tilt_overweights_the_higher_sharpe_sleeve_within_bounds() -> None:
    returns = _returns(120, {"winner": 0.002, "flat": 0.0, "loser": -0.002})
    allocation = blend_weights(returns, ["winner", "flat", "loser"])
    assert allocation.mode == "tilt"
    assert allocation.weights["winner"] > allocation.weights["flat"] > allocation.weights["loser"]
    assert sum(allocation.weights.values()) == pytest.approx(1.0)
    for weight in allocation.weights.values():
        assert 0.05 - 1e-9 <= weight <= 0.40 + 1e-9
    assert allocation.sharpes["winner"] > allocation.sharpes["loser"]
    assert allocation.window_obs == 63


def test_cap_is_widened_when_infeasible_for_small_n() -> None:
    # Two sleeves cannot both stay <= 0.40 and sum to 1 — the cap widens to 1/n honestly.
    returns = _returns(120, {"winner": 0.003, "loser": -0.003})
    allocation = blend_weights(returns, ["winner", "loser"])
    assert allocation.mode == "tilt"
    assert sum(allocation.weights.values()) == pytest.approx(1.0)
    assert allocation.weights["winner"] >= 0.5
    assert allocation.weights["loser"] >= 0.05 - 1e-9


def test_returns_before_excludes_the_cutoff_day_itself() -> None:
    returns = _returns(10, {"a": 0.001})
    cutoff = returns.index[5]
    visible = returns_before(returns, cutoff)
    assert visible.index.max() < cutoff
    assert len(visible) == 5


def test_empty_sleeve_list_yields_empty_allocation() -> None:
    allocation = blend_weights(pd.DataFrame(), [])
    assert allocation == SleeveAllocation(weights={}, mode="anchor")


def test_sleeve_return_frame_reads_forward_valuations(tmp_path) -> None:
    db = tmp_path / "forward.db"
    init_forward_db(db)
    for day, equity in [("2026-07-01", 10_000.0), ("2026-07-02", 10_100.0), ("2026-07-03", 10_050.0)]:
        append_valuation(
            db,
            "gem",
            ForwardValuation(
                created_at=day, equity=equity, total_return=equity / 10_000.0 - 1.0,
                benchmark_equity=10_000.0, benchmark_return=0.0,
            ),
        )
    frame = sleeve_return_frame(db, ["gem", "unknown_sleeve"])
    assert list(frame.columns) == ["gem"]  # sleeve without >=2 valuations yields no column
    assert len(frame) == 2
    assert frame["gem"].iloc[0] == pytest.approx(0.01)


def test_multi_day_gaps_are_dropped_from_the_return_frame(tmp_path) -> None:
    """R9/P2 (review 2026-07-20): a missed-cron gap must not enter the Sharpe window as
    one fake 'daily' return; normal weekend gaps stay."""
    db = tmp_path / "forward.db"
    init_forward_db(db)
    days = [
        ("2026-07-02", 10_000.0),  # Thu
        ("2026-07-03", 10_050.0),  # Fri (normal 1-day gap)
        ("2026-07-06", 10_100.0),  # Mon (weekend gap, 3 days - keep)
        ("2026-07-16", 11_000.0),  # Thu after a 10-day outage - drop this observation
        ("2026-07-17", 11_050.0),  # Fri (normal again)
    ]
    for day, equity in days:
        append_valuation(db, "gem", ForwardValuation(
            created_at=day, equity=equity, total_return=equity / 10_000.0 - 1.0,
            benchmark_equity=10_000.0, benchmark_return=0.0,
        ))
    frame = sleeve_return_frame(db, ["gem"])
    dates = [d.date().isoformat() for d in frame.index]
    assert "2026-07-16" not in dates  # the 10-day jump is not a daily return
    assert {"2026-07-03", "2026-07-06", "2026-07-17"} <= set(dates)
