"""Cell evaluation: honest statistics, costs as an axis, hard sample floor, no pyramiding."""
import pandas as pd

from equity_scout.matrix.grid import (
    COST_BPS,
    HOLD_BARS,
    HOLD_OUT_START,
    MIN_TRADES,
    evaluate_cell,
    pool_cells,
    split_periods,
)


def _bars(closes: list[float], day: str = "2024-01-02") -> pd.DataFrame:
    index = pd.date_range(f"{day}T14:30:00Z", periods=len(closes), freq="5min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [100] * len(closes)},
        index=index, dtype=float,
    )


def test_evaluate_cell_measures_the_forward_move_after_costs():
    # every signal bar is followed by exactly +100 bp; 10 bp roundtrip leaves 90 bp
    bars = _bars([100.0, 101.0] * 250)
    signal = pd.Series([True, False] * 250, index=bars.index)
    cell = evaluate_cell(bars, signal, hold_bars=1, cost_bps=10.0)
    assert cell["n"] == 250
    assert round(cell["gross_bp"]) == 100
    assert round(cell["net_bp"]) == 90
    assert cell["hit_rate"] == 1.0


def test_a_cell_below_the_sample_floor_reports_none_not_a_number():
    bars = _bars([100.0, 101.0])
    signal = pd.Series([True, False], index=bars.index)
    cell = evaluate_cell(bars, signal, hold_bars=1, cost_bps=10.0)
    assert cell["n"] == 1
    assert cell["net_bp"] is None and cell["t"] is None  # 1 < MIN_TRADES


def test_trades_never_run_past_the_end_of_the_series():
    bars = _bars([100.0] * 5)
    signal = pd.Series([False, False, False, False, True], index=bars.index)
    assert evaluate_cell(bars, signal, hold_bars=3, cost_bps=0.0)["n"] == 0


def test_a_bar_is_never_entered_twice_while_a_trade_is_open():
    # signals on every bar, hold 3 -> non-overlapping entries only, no pyramiding
    bars = _bars([100.0] * 30)
    signal = pd.Series([True] * 30, index=bars.index)
    assert evaluate_cell(bars, signal, hold_bars=3, cost_bps=0.0)["n"] == 9


def test_split_periods_keeps_the_hold_out_after_the_search_window():
    bars = pd.concat([_bars([100.0] * 3, day="2022-06-01"), _bars([100.0] * 3, day="2024-06-03")])
    in_sample, held_out = split_periods(bars)
    assert len(in_sample) == 3 and len(held_out) == 3
    assert str(held_out.index[0].date()) >= HOLD_OUT_START


def test_pool_cells_weights_by_trade_count_and_keeps_axes():
    per_ticker = [
        {"n": 300, "gross_bp": 10.0, "net_bp": 6.0, "t": 3.0, "hit_rate": 0.6},
        {"n": 100, "gross_bp": 2.0, "net_bp": -2.0, "t": -1.0, "hit_rate": 0.4},
    ]
    pooled = pool_cells(per_ticker, signal="hammer", cost_bps=4.0)
    assert pooled["signal"] == "hammer" and pooled["cost_bps"] == 4.0
    assert pooled["n"] == 400 and pooled["tickers_measurable"] == 2
    assert round(pooled["net_bp"], 3) == 4.0  # (6*300 + -2*100) / 400


def test_pool_cells_ignores_unmeasurable_tickers_without_treating_them_as_zero():
    per_ticker = [
        {"n": 300, "gross_bp": 10.0, "net_bp": 6.0, "t": 3.0, "hit_rate": 0.6},
        {"n": 5, "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None},
    ]
    pooled = pool_cells(per_ticker, signal="hammer")
    assert pooled["net_bp"] == 6.0  # not diluted toward zero by the thin ticker
    assert pooled["n"] == 305 and pooled["tickers_measurable"] == 1


def test_pool_of_only_unmeasurable_cells_stays_none():
    pooled = pool_cells([{"n": 3, "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None}])
    assert pooled["net_bp"] is None and pooled["t"] is None and pooled["n"] == 3


def test_the_axes_are_the_documented_ones():
    assert HOLD_BARS == (1, 2, 3, 6, 12)
    assert COST_BPS == (2.0, 4.0, 10.0, 20.0)
    assert MIN_TRADES == 200


def test_trade_returns_and_cell_from_returns_match_the_wrapper():
    from equity_scout.matrix.grid import cell_from_returns, trade_returns

    bars = _bars([100.0, 101.0] * 250)
    signal = pd.Series([True, False] * 250, index=bars.index)
    gross = trade_returns(bars, signal, hold_bars=1)
    assert len(gross) == 250
    direct = cell_from_returns(gross, cost_bps=10.0)
    assert direct == evaluate_cell(bars, signal, hold_bars=1, cost_bps=10.0)


def test_trade_returns_reuse_across_cost_levels_changes_only_the_net():
    from equity_scout.matrix.grid import cell_from_returns, trade_returns

    bars = _bars([100.0, 101.0] * 250)
    signal = pd.Series([True, False] * 250, index=bars.index)
    gross = trade_returns(bars, signal, hold_bars=1)
    cheap = cell_from_returns(gross, cost_bps=2.0)
    dear = cell_from_returns(gross, cost_bps=20.0)
    assert cheap["n"] == dear["n"] == 250
    assert cheap["gross_bp"] == dear["gross_bp"]
    assert round(cheap["net_bp"] - dear["net_bp"], 6) == 18.0


def test_trade_returns_skips_a_signal_while_a_position_is_open():
    from equity_scout.matrix.grid import trade_returns

    bars = _bars([100.0] * 30)
    signal = pd.Series([True] * 30, index=bars.index)
    assert len(trade_returns(bars, signal, hold_bars=3)) == 9
