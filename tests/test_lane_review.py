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


def _resolved(sim_return: float | None, reason: str = "Maximale Haltedauer überschritten") -> dict:
    return {"lane": "swing", "ticker": "R", "reason": "not_bullish",
            "sim_return": sim_return, "sim_exit_reason": reason,
            "resolved_at": "2026-08-21T02:30:00Z"}


def test_resolved_rejections_enter_the_review_with_gross_wording() -> None:
    """The no-trade book meets the review: how many rejected opportunities settled, how
    many would have worked, and the direct traded-vs-rejected sentence — marked gross."""
    trades = [_sell(10.0), _sell(-4.0)]
    rejections = [_resolved(0.04), _resolved(0.02), _resolved(-0.01), _resolved(None, "keine Daten")]
    review = review_lane("swing", trades, rejections=rejections)
    note = " ".join(review.notes)
    assert "3 verworfene" in note  # the no-data row is not a measured opportunity
    assert "2/3" in note
    assert "+1,7" in note or "+1.7" in note  # mean of 4, 2, -1 percent
    assert "brutto" in note.lower()
    assert "6,00 USD" in note or "6.00 USD" in note  # what the traded book actually made


def test_review_without_rejections_keeps_its_old_shape() -> None:
    review = review_lane("swing", [_sell(10.0)])
    assert not any("verworfen" in n for n in review.notes)


def test_rejections_without_any_closed_trade_still_reviewed() -> None:
    review = review_lane("swing", [], rejections=[_resolved(0.03)])
    note = " ".join(review.notes)
    assert "1 verworfene" in note
    assert "kein abgeschlossener eigener Trade" in note


def _dated_sell(executed_at: str, pnl: float) -> dict:
    return {
        "executed_at": executed_at, "ticker": "BTC/USD", "side": "sell",
        "qty": 1.0, "price": 100.0, "fees": 0.1, "reason": "channel_exit",
        "realized_pnl": pnl,
    }


def test_crypto_review_starts_at_the_daily_bars_epoch() -> None:
    from equity_scout.lane_review import MEASUREMENT_EPOCHS

    assert MEASUREMENT_EPOCHS["crypto"] == "2026-08-10"
    trades = [
        _dated_sell("2026-07-01T10:00:00", -400.0),
        _dated_sell("2026-08-12T10:00:00", 5.0),
    ]
    review = review_lane("crypto", trades)
    assert review.n_closed == 1  # the 15-minute-era trade is outside the verdict window
    assert review.net == 5.0
    assert any("2026-08-10" in note for note in review.notes)


def test_other_lanes_keep_their_full_history() -> None:
    trades = [_dated_sell("2026-07-01T10:00:00", -1.0), _dated_sell("2026-08-12T10:00:00", 2.0)]
    assert review_lane("swing", trades).n_closed == 2


def test_a_trade_without_a_timestamp_is_not_silently_dropped() -> None:
    # live rows always carry executed_at (NOT NULL); a row without one must still be counted
    # rather than vanish from the book behind an epoch filter
    assert review_lane("crypto", [_sell(3.0)]).n_closed == 1


def test_a_window_change_suspends_the_movement_comparison() -> None:
    # the last review was measured over the full history (no epoch); reporting the shrink as
    # a gain would invent a fee refund the lane never earned
    previous = {"n_closed": 32, "net": -451.60}  # pre-epoch shape: no "epoch" key at all
    review = review_lane("crypto", [_dated_sell("2026-08-12T10:00:00", -129.72)], previous=previous)
    assert review.delta_net is None and review.delta_trades is None
    assert any("anderen Bewertungsfenster" in note for note in review.notes)


def test_movement_returns_once_both_reviews_share_the_window() -> None:
    previous = {"n_closed": 1, "net": -100.0, "epoch": "2026-08-10"}
    review = review_lane(
        "crypto",
        [_dated_sell("2026-08-12T10:00:00", -100.0), _dated_sell("2026-08-13T10:00:00", 20.0)],
        previous=previous,
    )
    assert review.delta_trades == 1
    assert review.delta_net == 20.0
