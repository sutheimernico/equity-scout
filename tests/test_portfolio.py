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
                    now="d1", position_fraction=0.05, fee_rate=0.001, slippage_bps=0.0)
    # target value 5000, fee 5 → cash 100000 - 5005
    assert abs(pf.cash - 94_995.0) < 1e-6
    assert abs(pf.positions["HOT"].shares - 50.0) < 1e-9  # 5000 / 100, no slippage


def test_mark_to_market_tracks_gain_and_benchmark():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, benchmark_price=400.0, slippage_bps=0.0)
    # price doubles → position worth 10000 (was 5000), benchmark flat
    val = mark_to_market(pf, {"HOT": 200.0}, benchmark_price=400.0)
    assert abs(val.positions_value - 10_000.0) < 1e-6
    assert val.total_return > 0  # gained 5000 minus fee
    assert abs(val.benchmark_return) < 1e-9  # benchmark price unchanged
    assert val.open_positions == 1


def test_buy_pays_slippage_above_the_quote():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, fee_rate=0.0, slippage_bps=10.0)
    # fill = 100 * 1.001 = 100.1, so fewer shares than the 50.0 a frictionless fill would give
    assert abs(pf.positions["HOT"].cost_basis - 100.1) < 1e-9
    assert pf.positions["HOT"].shares < 50.0


def test_sells_holding_when_composite_drops_below_exit_threshold():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0}, now="d1", threshold=0.70)
    assert "HOT" in pf.positions
    # Composite collapses below the exit threshold → position is sold.
    pf, trades = advance(pf, [_pick("HOT", 0.40)], {"HOT": 100.0},
                         now="d2", threshold=0.70, exit_threshold=0.55)
    assert "HOT" not in pf.positions
    assert any(t.startswith("SELL HOT") for t in trades)


def test_sells_holding_that_dropped_out_of_the_screen():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0}, now="d1", threshold=0.70)
    # HOT no longer in the picks at all → treated as composite 0 → sold (price still needed to value it).
    pf, trades = advance(pf, [], {"HOT": 100.0}, now="d2")
    assert "HOT" not in pf.positions
    assert any(t.startswith("SELL HOT") for t in trades)


def test_sell_proceeds_pay_slippage_and_fee():
    # Buy frictionlessly so cash is exactly known, then sell with friction and check the proceeds.
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, fee_rate=0.0, slippage_bps=0.0)
    cash_after_buy = pf.cash  # 95_000, holding 50 shares at 100
    pf, _ = advance(pf, [_pick("HOT", 0.40)], {"HOT": 100.0},
                    now="d2", exit_threshold=0.55, fee_rate=0.001, slippage_bps=10.0)
    # fill = 100 * (1 - 0.001) = 99.9; proceeds = 50 * 99.9 * (1 - 0.001) = 4_990.005
    assert "HOT" not in pf.positions
    assert abs((pf.cash - cash_after_buy) - 4_990.005) < 1e-6


def test_holds_when_composite_stays_above_exit_threshold():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0}, now="d1", threshold=0.70)
    # Composite eased to 0.60 — above the 0.55 exit floor, so hysteresis keeps the position.
    pf, trades = advance(pf, [_pick("HOT", 0.60)], {"HOT": 100.0},
                         now="d2", threshold=0.70, exit_threshold=0.55)
    assert "HOT" in pf.positions
    assert trades == []


def test_missing_price_defers_the_sale():
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0}, now="d1", threshold=0.70)
    # No price for HOT this advance and it dropped out — we cannot value a sale, so we hold.
    pf, trades = advance(pf, [], {}, now="d2")
    assert "HOT" in pf.positions
    assert trades == []


def test_new_buy_sized_larger_after_big_gain():
    # Baseline: fresh account buys HOT at 100, sized off 100_000 starting equity.
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, fee_rate=0.001, slippage_bps=0.0)
    baseline_shares = pf.positions["HOT"].shares  # 5000 stake / 100 = 50 shares

    # HOT quadruples (100 -> 400) and is still held (composite stays above exit_threshold),
    # ballooning account equity well above the 100_000 starting capital. A fresh pick MORE
    # should now be sized off that larger current equity, not the stale initial capital.
    pf, trades = advance(pf, [_pick("HOT", 0.85), _pick("MORE", 0.85)],
                         {"HOT": 400.0, "MORE": 100.0},
                         now="d2", position_fraction=0.05, fee_rate=0.001, slippage_bps=0.0)
    assert "MORE" in pf.positions
    assert pf.positions["MORE"].shares > baseline_shares


def test_new_buy_sized_smaller_after_big_loss():
    # Baseline: fresh account buys HOT at 100, sized off 100_000 starting equity.
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("HOT", 0.85)], {"HOT": 100.0},
                    now="d1", position_fraction=0.05, fee_rate=0.001, slippage_bps=0.0)
    baseline_shares = pf.positions["HOT"].shares  # 5000 stake / 100 = 50 shares

    # HOT craters (100 -> 20) and is still held (composite stays above exit_threshold),
    # shrinking account equity below the 100_000 starting capital. A fresh pick LESS should
    # now be sized off that smaller current equity, not the stale initial capital.
    pf, trades = advance(pf, [_pick("HOT", 0.85), _pick("LESS", 0.85)],
                         {"HOT": 20.0, "LESS": 100.0},
                         now="d2", position_fraction=0.05, fee_rate=0.001, slippage_bps=0.0)
    assert "LESS" in pf.positions
    assert pf.positions["LESS"].shares < baseline_shares
