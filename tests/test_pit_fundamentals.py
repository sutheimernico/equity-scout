"""Point-in-time fundamentals: what was PUBLIC on a day, never what was true in hindsight.

These tests carry more weight than their size suggests: a look-ahead bug here does not crash, it
produces a good backtest. The payload shapes mirror what EDGAR actually returns, including the two
traps measured on real data (2026-08-12) — `fy` being the FILING's year, and restatements sharing
a period end.
"""
from __future__ import annotations

from equity_scout.pit_fundamentals import (
    filing_lag_days,
    latest_two_periods,
    visible_annual_series,
)


def _payload(entries: list[dict], tag: str = "NetIncomeLoss") -> dict:
    return {"facts": {"us-gaap": {tag: {"units": {"USD": entries}}}}}


def _entry(end: str, filed: str, val: float, *, fy: int | None = None, form: str = "10-K") -> dict:
    return {"end": end, "filed": filed, "val": val, "form": form, "fp": "FY", "fy": fy or 0}


def test_a_figure_filed_after_the_as_of_date_is_invisible():
    """The whole point. On 2024-10-01 the FY2024 numbers existed but were not public — AAPL filed
    them on 2024-11-01, 34 days after the period closed."""
    payload = _payload([
        _entry("2023-09-30", "2023-11-03", 97.0),
        _entry("2024-09-28", "2024-11-01", 93.7),
    ])
    before = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2024-10-01")
    after = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2024-11-01")
    assert "2024-09-28" not in before
    assert "2024-09-28" in after  # filed ON the as_of date counts as public


def test_the_series_is_keyed_by_period_not_by_filing_fiscal_year():
    """Trap 1, measured on real data: one 10-K carries three periods, all stamped with the FILING's
    fy. Keying on fy would label 2022 comparatives as 2024 figures."""
    payload = _payload([
        _entry("2022-09-24", "2024-11-01", 99.8, fy=2024),
        _entry("2023-09-30", "2024-11-01", 97.0, fy=2024),
        _entry("2024-09-28", "2024-11-01", 93.7, fy=2024),
    ])
    series = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2025-01-01")
    assert sorted(series) == ["2022-09-24", "2023-09-30", "2024-09-28"]
    assert series["2022-09-24"] == 99.8 and series["2024-09-28"] == 93.7


def test_a_restatement_wins_only_once_it_is_filed():
    """Trap 2: the same period appears twice with different values. Before the restatement is
    filed, the ORIGINAL number is the honest answer."""
    payload = _payload([
        _entry("2023-09-30", "2023-11-03", 97.0),
        _entry("2023-09-30", "2024-11-01", 95.5),  # restated a year later
        _entry("2022-09-24", "2022-10-28", 99.8),
    ])
    early = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2024-01-01")
    late = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2025-01-01")
    assert early["2023-09-30"] == 97.0  # the restatement must not leak backwards
    assert late["2023-09-30"] == 95.5


def test_quarterly_and_other_forms_are_ignored():
    payload = _payload([
        _entry("2023-09-30", "2023-11-03", 97.0),
        _entry("2024-06-30", "2024-08-01", 21.0, form="10-Q"),
        _entry("2024-09-28", "2024-11-01", 93.7),
    ])
    series = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2025-01-01")
    assert "2024-06-30" not in series


def test_fewer_than_two_visible_periods_yields_nothing():
    """A Piotroski comparison needs a predecessor year. One period is not a weaker signal, it is
    no signal — and returning it would invite a silent single-year fallback."""
    payload = _payload([_entry("2024-09-28", "2024-11-01", 93.7)])
    assert visible_annual_series(payload, ["NetIncomeLoss"], as_of="2025-01-01") == {}


def test_tag_candidates_are_tried_in_order_and_the_first_usable_one_wins():
    payload = {
        "facts": {
            "us-gaap": {
                "Preferred": {"units": {"USD": [_entry("2024-09-28", "2024-11-01", 1.0)]}},
                "Fallback": {"units": {"USD": [
                    _entry("2023-09-30", "2023-11-03", 2.0),
                    _entry("2024-09-28", "2024-11-01", 3.0),
                ]}},
            }
        }
    }
    # "Preferred" has only one visible period, so the fallback tag supplies the series.
    series = visible_annual_series(payload, ["Preferred", "Fallback"], as_of="2025-01-01")
    assert series == {"2023-09-30": 2.0, "2024-09-28": 3.0}


def test_missing_or_malformed_entries_never_raise():
    payload = _payload([
        {"end": "2023-09-30", "filed": "2023-11-03", "val": None, "form": "10-K"},
        {"end": None, "filed": "2024-11-01", "val": 1.0, "form": "10-K"},
        {"filed": "2024-11-01", "val": 1.0, "form": "10-K"},
        _entry("2022-09-24", "2022-10-28", 99.8),
        _entry("2023-09-30", "2023-11-03", 97.0),
    ])
    series = visible_annual_series(payload, ["NetIncomeLoss"], as_of="2025-01-01")
    assert series == {"2022-09-24": 99.8, "2023-09-30": 97.0}


def test_latest_two_periods_returns_them_oldest_first():
    series = {"2022-09-24": 1.0, "2023-09-30": 2.0, "2024-09-28": 3.0}
    assert latest_two_periods(series) == (("2023-09-30", 2.0), ("2024-09-28", 3.0))
    assert latest_two_periods({"2024-09-28": 3.0}) is None


def test_filing_lag_reports_the_look_ahead_a_fiscal_year_key_would_add():
    """The diagnostic that lets a backfill state the risk it avoids. AAPL's real current-period
    lag is 34 days."""
    payload = _payload([
        _entry("2024-09-28", "2024-11-01", 93.7),
        _entry("2023-09-30", "2023-11-03", 97.0),
    ])
    lags = filing_lag_days(payload, "NetIncomeLoss")
    assert sorted(lags) == [34, 34]


def test_the_lag_minimum_is_the_meaningful_number_not_the_median():
    """Found while checking against real data: comparatives dominate the distribution. One 10-K
    carrying three periods yields lags of 34, 398 and 769 days — a median of 398 describes the
    payload's shape, only the minimum describes the look-ahead."""
    payload = _payload([
        _entry("2022-09-24", "2024-11-01", 99.8),
        _entry("2023-09-30", "2024-11-01", 97.0),
        _entry("2024-09-28", "2024-11-01", 93.7),
    ])
    lags = filing_lag_days(payload, "NetIncomeLoss")
    assert min(lags) == 34
    assert sorted(lags) == [34, 398, 769]


def test_filing_lag_skips_unparseable_dates_instead_of_guessing():
    payload = _payload([
        _entry("2024-09-28", "2024-11-01", 93.7),
        {"end": "not-a-date", "filed": "2024-11-01", "val": 1.0, "form": "10-K"},
    ])
    assert filing_lag_days(payload, "NetIncomeLoss") == [34]
