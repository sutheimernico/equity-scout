"""Per-bet attribution: error ranking + regime contrast."""
from __future__ import annotations

from equity_scout.ml.attribution import attribution_summary
from equity_scout.ml.meta_model import BetRecord


def test_attribution_contrasts_regimes_and_ranks_errors_by_confidence() -> None:
    bets = [
        BetRecord("2020-01-01", 0.90, "follow", 1, True, {"vol": 0.10}),
        BetRecord("2020-02-01", 0.80, "follow", 0, False, {"vol": 0.50}),  # confident wrong
        BetRecord("2020-03-01", 0.55, "follow", 0, False, {"vol": 0.40}),  # marginal wrong
        BetRecord("2020-04-01", 0.30, "avoid", 0, True, {"vol": 0.20}),
    ]
    summary = attribution_summary(bets, top_n=2)

    assert summary["n_bets"] == 4
    assert summary["n_errors"] == 2
    assert summary["hit_rate"] == 0.5
    # most overconfident mistake first: |0.80-0.5| > |0.55-0.5|
    assert [w["date"] for w in summary["worst"]] == ["2020-02-01", "2020-03-01"]
    # the model is wrong in higher-volatility regimes here
    assert summary["regime_contrast"]["vol"]["wrong"] > summary["regime_contrast"]["vol"]["correct"]


def test_attribution_empty_is_safe() -> None:
    assert attribution_summary([]) == {
        "n_bets": 0,
        "n_errors": 0,
        "hit_rate": 0.0,
        "worst": [],
        "regime_contrast": {},
    }
