"""Plateaus: connected regions that survive their own neighbourhood, not winning cells."""
from equity_scout.matrix.plateau import (
    MIN_PLATEAU_CELLS,
    PLATEAU_T,
    find_plateaus,
    qualifying_cells,
)
from equity_scout.matrix.timeframes import TIME_SLICES


def _cell(signal, threshold, slice_label, hold_bars, cost_bps, net_bp, t, n=1000,
          asset_class="stock"):
    return {
        "signal": signal, "threshold": threshold, "slice": slice_label,
        "hold_bars": hold_bars, "cost_bps": cost_bps, "asset_class": asset_class,
        "net_bp": net_bp, "t": t, "n": n, "hit_rate": 0.5,
    }


def _find(cells):
    return find_plateaus(cells, slice_order=TIME_SLICES)


def test_an_isolated_winning_cell_is_not_a_plateau():
    assert _find([_cell("momentum_up", 0.005, "5min", 3, 4.0, 8.0, 4.0)]) == []


def test_a_connected_region_of_winners_is_a_plateau():
    # neighbours along the threshold axis AND the hold axis -> 4 connected cells
    cells = [
        _cell("reversal_down", 0.005, "5min", 2, 4.0, 6.0, 3.0),
        _cell("reversal_down", 0.005, "5min", 3, 4.0, 7.0, 3.5),
        _cell("reversal_down", 0.01, "5min", 2, 4.0, 5.5, 3.1),
        _cell("reversal_down", 0.01, "5min", 3, 4.0, 6.2, 3.3),
    ]
    found = _find(cells)
    assert len(found) == 1
    plateau = found[0]
    assert plateau["size"] == 4
    assert plateau["signal"] == "reversal_down"
    assert plateau["slices"] == ["5min"]
    assert plateau["thresholds"] == [0.005, 0.01]
    assert round(plateau["median_net_bp"], 2) == 6.10
    assert plateau["worst_t"] == 3.0
    assert plateau["total_trades"] == 4000


def test_cells_are_neighbours_across_adjacent_time_slices():
    # 15min and 30min are adjacent in TIME_SLICES; alphabetically they are not
    cells = [
        _cell("hammer", 2.0, "15min", 3, 4.0, 6.0, 3.0),
        _cell("hammer", 2.0, "30min", 3, 4.0, 6.5, 3.2),
        _cell("hammer", 3.0, "15min", 3, 4.0, 5.8, 2.9),
        _cell("hammer", 3.0, "30min", 3, 4.0, 6.1, 3.1),
    ]
    found = _find(cells)
    assert len(found) == 1 and found[0]["slices"] == ["15min", "30min"]


def test_daily_and_monthly_slices_are_not_neighbours():
    # 1D and 1M are two steps apart (1W between them) -> two singletons, no plateau
    cells = [
        _cell("gap_up", 0.005, "1D", 2, 4.0, 6.0, 3.0),
        _cell("gap_up", 0.005, "1M", 2, 4.0, 6.0, 3.0),
        _cell("gap_up", 0.01, "1D", 2, 4.0, 6.0, 3.0),
        _cell("gap_up", 0.01, "1M", 2, 4.0, 6.0, 3.0),
    ]
    assert _find(cells) == []


def test_different_signals_never_merge():
    cells = [
        _cell("hammer", 2.0, "5min", 3, 4.0, 6.0, 3.0),
        _cell("momentum_up", 0.005, "5min", 3, 4.0, 6.0, 3.0),
    ]
    assert _find(cells) == []


def test_different_asset_classes_never_merge():
    cells = [
        _cell("hammer", 2.0, "5min", 2, 4.0, 6.0, 3.0, asset_class="stock"),
        _cell("hammer", 2.0, "5min", 3, 4.0, 6.0, 3.0, asset_class="stock"),
        _cell("hammer", 2.0, "5min", 2, 4.0, 6.0, 3.0, asset_class="commodity"),
        _cell("hammer", 2.0, "5min", 3, 4.0, 6.0, 3.0, asset_class="commodity"),
    ]
    assert _find(cells) == []  # two pairs of two, each below the minimum


def test_different_cost_levels_never_merge():
    cells = [
        _cell("hammer", 2.0, "5min", 2, 2.0, 6.0, 3.0),
        _cell("hammer", 2.0, "5min", 3, 2.0, 6.0, 3.0),
        _cell("hammer", 2.0, "5min", 2, 4.0, 6.0, 3.0),
        _cell("hammer", 2.0, "5min", 3, 4.0, 6.0, 3.0),
    ]
    assert _find(cells) == []


def test_a_cell_below_the_t_bar_breaks_the_region():
    cells = [
        _cell("gap_up", 0.002, "5min", 2, 4.0, 6.0, 3.0),
        _cell("gap_up", 0.005, "5min", 2, 4.0, 6.0, 1.0),  # t too low -> not a member
        _cell("gap_up", 0.01, "5min", 2, 4.0, 6.0, 3.0),
    ]
    assert _find(cells) == []  # the middle cell separates two singletons


def test_a_negative_net_cell_cannot_qualify():
    assert qualifying_cells([_cell("hammer", 2.0, "5min", 2, 4.0, -1.0, 5.0)]) == []


def test_none_valued_cells_are_ignored_not_treated_as_zero():
    cells = [
        _cell("hammer", threshold, "5min", 2, 4.0, None, None, n=12)
        for threshold in (2.0, 3.0, 4.0)
    ]
    assert _find(cells) == []


def test_the_bars_are_the_documented_ones():
    assert MIN_PLATEAU_CELLS == 4
    assert PLATEAU_T == 2.0
