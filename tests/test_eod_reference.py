"""Independent EOD reference: only finished days count, absence is never agreement."""
from datetime import date

from equity_scout.data.eod_reference import parse_daily_closes

PAYLOAD = {
    "bars": {
        "SPY": [
            {"t": "2026-08-13T04:00:00Z", "c": 777.84},
            {"t": "2026-08-14T04:00:00Z", "c": 776.30},
            {"t": "2026-08-17T04:00:00Z", "c": 773.12},  # today, still running
        ],
        "GLD": [{"t": "2026-08-14T04:00:00Z", "c": 401.45}],
    }
}


def test_newest_finished_day_wins():
    result = parse_daily_closes(PAYLOAD, today=date(2026, 8, 17))
    assert result["SPY"] == ("2026-08-14", 776.30)
    assert result["GLD"] == ("2026-08-14", 401.45)


def test_a_symbol_without_a_finished_bar_is_absent():
    payload = {"bars": {"SPY": [{"t": "2026-08-17T04:00:00Z", "c": 773.12}]}}
    assert parse_daily_closes(payload, today=date(2026, 8, 17)) == {}


def test_empty_and_malformed_payloads_yield_nothing():
    assert parse_daily_closes({}, today=date(2026, 8, 17)) == {}
    assert parse_daily_closes({"bars": None}, today=date(2026, 8, 17)) == {}
    assert parse_daily_closes({"bars": {"SPY": []}}, today=date(2026, 8, 17)) == {}
    broken = {"bars": {"SPY": [{"t": "2026-08-14T04:00:00Z", "c": None}]}}
    assert parse_daily_closes(broken, today=date(2026, 8, 17)) == {}
    zero = {"bars": {"SPY": [{"t": "2026-08-14T04:00:00Z", "c": 0.0}]}}
    assert parse_daily_closes(zero, today=date(2026, 8, 17)) == {}
