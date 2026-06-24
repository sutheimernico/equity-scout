from equity_scout.models import Instrument, Pick
from equity_scout.portfolio import advance, mark_to_market, new_portfolio


def _pick(ticker, composite):
    inst = Instrument(ticker, ticker, "US", "US", "USD", "Tech")
    return Pick(inst, "aggressive", 1, composite,
                {"value": 0.5, "quality": 0.5, "momentum": 0.9, "growth": 0.9})


def test_buys_only_picks_above_threshold():
    pf = new_portfolio(100_000.0)
    picks = [_pick("HOT", 0.85), _pick("MEH", 0.50)]
    prices = {"HOT": 100.0, "MEH": 50.0}
    pf, trades = advance(pf, picks, prices, now="2026-06-24T00:00:00", threshold=0.70)
    assert "HOT" in pf.positions
    assert "MEH" not in pf.positions  # below threshold
    assert len(trades) == 1


def test_does_not_rebuy_held_position():
    pf = new_portfolio(100_000.0)
    picks = [_pick("HOT", 0.85)]
    prices = {"HOT": 100.0}
    pf, _ = advance(pf, picks, prices, now="d1", threshold=0.70)
    pf, trades = advance(pf, picks, prices, now="d2", threshold=0.70)
    assert trades == []  # already held
    assert pf.positions["HOT"].opened_at == "d1"


def test_cash_decreases_by_cost_plus_fee():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, fee_rate=0.001)
    # target value 5000, fee 5 → cash 100000 - 5005
    assert abs(pf.cash - 94_995.0) < 1e-6
    assert abs(pf.positions["HOT"].shares - 50.0) < 1e-9  # 5000 / 100


def test_mark_to_market_tracks_gain_and_benchmark():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, benchmark_price=400.0)
    # price doubles → position worth 10000 (was 5000), benchmark flat
    val = mark_to_market(pf, {"HOT": 200.0}, benchmark_price=400.0)
    assert abs(val.positions_value - 10_000.0) < 1e-6
    assert val.total_return > 0  # gained 5000 minus fee
    assert abs(val.benchmark_return) < 1e-9  # benchmark price unchanged
    assert val.open_positions == 1
