"""Nightly lane review: decomposition, verdict, movement since last time, honest wording."""
from __future__ import annotations

from equity_scout.lane_review import LaneReview, render, review_lane


def _sell(pnl: float, reason: str = "Gewinnziel") -> dict:
    return {"side": "sell", "realized_pnl": pnl, "reason": reason, "ticker": "X"}


def test_open_positions_do_not_count_as_results() -> None:
    trades = [_sell(10.0), {"side": "buy", "realized_pnl": None, "reason": "Einstieg"}]
    review = review_lane("swing", trades)
    assert review.n_closed == 1
    assert review.net == 10.0


def test_the_dominant_exit_reason_is_named_without_claiming_a_cause() -> None:
    trades = [_sell(-90.0, "Altbestand (zwangsflat)")] + [_sell(1.0) for _ in range(10)]
    review = review_lane("session", trades)
    note = " ".join(review.notes)
    assert "Altbestand (zwangsflat)" in note
    # The wording must stop at "where", not slide into "why".
    assert "nicht warum" in note


def test_a_settled_verdict_says_more_trades_will_not_change_it() -> None:
    # 40 losing trades with little spread: the test resolves.
    review = review_lane("crypto", [_sell(-14.0 + (i % 3)) for i in range(40)])
    assert review.significant
    assert any("statistisch entschieden" in n for n in review.notes)


def test_an_open_measurement_says_how_many_trades_are_missing() -> None:
    review = review_lane("swing", [_sell(18.0 - (i % 7) * 9) for i in range(8)])
    assert not review.significant
    assert any("fehlen" in n for n in review.notes)


def test_movement_since_the_previous_review_is_reported() -> None:
    previous = LaneReview(
        lane="swing", n_closed=6, net=100.0, verdict="noch nicht aussagekräftig",
        significant=False, trades_missing=20,
    )
    review = review_lane("swing", [_sell(25.0) for _ in range(8)], previous=previous)
    assert review.delta_trades == 2
    assert review.delta_net == 100.0


def test_a_night_without_a_closed_trade_says_so() -> None:
    previous = LaneReview(
        lane="session", n_closed=2, net=5.0, verdict="zu wenige Trades",
        significant=False, trades_missing=None,
    )
    review = review_lane("session", [_sell(2.5), _sell(2.5)], previous=previous)
    assert review.delta_trades == 0
    assert any("nichts Neues zu lernen" in n for n in review.notes)


def test_render_leads_with_the_lane_that_needs_a_decision() -> None:
    settled = review_lane("crypto", [_sell(-14.0 + (i % 3)) for i in range(40)])
    open_one = review_lane("swing", [_sell(18.0 - (i % 7) * 9) for i in range(8)])
    text = render([open_one, settled])
    assert text.index("crypto") < text.index("swing")


def test_render_survives_a_night_with_no_lane_at_all() -> None:
    assert "keine Lane" in render([])
