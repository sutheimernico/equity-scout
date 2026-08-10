"""Per-position exit levels for the phone depot card.

Nico 2026-08-06: "wenn ich dann auf diesen Trade klicke, das mir auch angezeigt wird, ab
wann Du verkaufen wirst, ab wann Du Verlust realisieren würdest". Each lane has its own
rules, so the levels are derived per lane and honestly absent where they are not a fixed
price.
"""
from __future__ import annotations

from equity_scout.shortterm_book import position_targets


def test_swing_targets_come_from_the_fixed_percentages():
    # st_swing: PROFIT_TARGET 5 %, STOP_LOSS 3 %, 7 calendar days.
    t = position_targets("swing", entry_price=100.0)
    assert round(t["target_price"], 2) == 105.0
    assert round(t["stop_price"], 2) == 97.0
    assert t["max_hold_days"] == 7
    assert "5" in t["rule"] and "3" in t["rule"]


def test_crypto_has_a_stop_but_a_signal_based_exit():
    # st_crypto: STOP_PCT 15 % since the 2026-08-10 move to daily bars (a 2 % stop sat inside
    # one daily bar's range), exit otherwise on a 10-day Donchian low — not a fixed price.
    t = position_targets("crypto", entry_price=200.0)
    assert round(t["stop_price"], 2) == 170.0
    assert t["target_price"] is None
    assert "Ausbruch" in t["rule"] or "Tief" in t["rule"]


def test_session_levels_depend_on_the_opening_range_and_are_not_stored():
    """The intraday lane sizes stop and target off that morning's opening range, which the
    book does not keep — so the card must say that rather than invent a price."""
    t = position_targets("session", entry_price=50.0)
    assert t["target_price"] is None
    assert t["stop_price"] is None
    assert "Eröffnungsspanne" in t["rule"]


def test_an_unknown_lane_yields_no_levels_instead_of_guessing():
    t = position_targets("nonexistent", entry_price=10.0)
    assert t["target_price"] is None and t["stop_price"] is None
