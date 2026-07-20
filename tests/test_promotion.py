"""Promotion gate (v12 I2): an arena lane earns depot capital only on evidence —
every failing criterion is named, never silently waived."""
from __future__ import annotations

import pytest

from equity_scout.promotion import PromotionConfig, lane_promotion_status

TODAY = "2026-07-21"


def _trade(pnl: float | None) -> dict:
    return {"realized_pnl": pnl}


def _vals(first_day: str) -> list[dict]:
    return [{"created_at": f"{first_day}T10:00", "equity": 10_000.0}]


def _winning_trades(n: int, *, win: float = 20.0, loss: float = -10.0) -> list[dict]:
    trades: list[dict] = []
    for i in range(n):
        trades.append(_trade(win if i % 2 == 0 else loss))
    return trades


def test_all_criteria_met_is_eligible() -> None:
    status = lane_promotion_status(
        _winning_trades(30), _vals("2026-05-01"), today=TODAY
    )
    assert status["eligible"] is True
    assert status["missing"] == []
    assert status["realized_trades"] == 30
    assert status["days_active"] == 81
    assert status["profit_factor"] == pytest.approx(2.0)


def test_each_missing_criterion_is_named() -> None:
    # 10 trades, young lane, net negative
    trades = [_trade(-5.0)] * 10
    status = lane_promotion_status(trades, _vals("2026-07-01"), today=TODAY)
    assert status["eligible"] is False
    joined = " ".join(status["missing"])
    assert "10/30" in joined  # trades
    assert "20/60" in joined  # days
    assert "Netto-P&L" in joined
    assert "Profit-Faktor" in joined


def test_open_buys_do_not_count_as_realized() -> None:
    trades = [_trade(None)] * 40  # buys carry realized_pnl None
    status = lane_promotion_status(trades, _vals("2026-05-01"), today=TODAY)
    assert status["realized_trades"] == 0
    assert status["eligible"] is False


def test_no_losses_needs_wins_to_prove_anything() -> None:
    status = lane_promotion_status(
        [_trade(50.0)] * 30, _vals("2026-05-01"), today=TODAY
    )
    assert status["eligible"] is True  # all wins: profit factor unbounded, evidence stands

    empty = lane_promotion_status([], _vals("2026-05-01"), today=TODAY)
    assert empty["eligible"] is False
    assert empty["profit_factor"] is None


def test_config_thresholds_are_respected() -> None:
    cfg = PromotionConfig(min_trades=5, min_days_active=10, min_profit_factor=1.0)
    status = lane_promotion_status(
        _winning_trades(6), _vals("2026-07-01"), cfg, today=TODAY
    )
    assert status["eligible"] is True


def test_trailing_net_pnl_only_counts_the_window() -> None:
    from equity_scout.promotion import trailing_net_pnl

    trades = [
        {"executed_at": "2026-03-01T10:00", "realized_pnl": 500.0},  # outside 60d
        {"executed_at": "2026-07-01T10:00", "realized_pnl": -30.0},
        {"executed_at": "2026-07-10T10:00", "realized_pnl": 10.0},
        {"executed_at": "2026-07-15T10:00", "realized_pnl": None},  # open buy
    ]
    assert trailing_net_pnl(trades, today=TODAY) == pytest.approx(-20.0)
