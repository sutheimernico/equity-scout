from equity_scout.data_quality import build_data_quality_report
from equity_scout.data.yf_provider import FetchStats
from equity_scout.models import Instrument, Quote

INST = Instrument("X", "X", "E", "US", "USD", "Tech")


def _quote(**kw):
    base = dict(trailing_pe=None, price_to_book=None, return_on_equity=None,
                profit_margins=None, revenue_growth=None, earnings_growth=None,
                momentum_6m=None)
    base.update(kw)
    return Quote(instrument=INST, **base)


def test_report_without_fetch_stats_still_reports_missing_fields_and_gate_count():
    quotes = [_quote(trailing_pe=10.0, momentum_6m=0.05), _quote()]  # one full-ish, one empty
    report = build_data_quality_report(quotes, gated_out={"Y": "too few fundamentals (0/4)"})
    assert report["attempted"] == 0  # no FetchStats wired (e.g. fake provider)
    assert report["fetch_error_rate"] == 0.0
    assert report["missing_fields"]["trailing_pe"] == 1
    assert report["missing_fields"]["momentum_6m"] == 1
    assert report["gate_filtered"] == 1


def test_report_computes_fetch_error_rate_from_stats():
    stats = FetchStats()
    for _ in range(10):
        stats.record_attempt()
    stats.record_info_failure()
    stats.record_closes_failure()  # 2 failures out of 10 attempts

    report = build_data_quality_report([], gated_out={}, fetch_stats=stats)
    assert report["attempted"] == 10
    assert report["info_failed"] == 1
    assert report["closes_failed"] == 1
    assert report["fetch_error_rate"] == 0.2


def test_report_zero_attempts_does_not_divide_by_zero():
    stats = FetchStats()
    report = build_data_quality_report([], gated_out={}, fetch_stats=stats)
    assert report["fetch_error_rate"] == 0.0


def test_missing_fields_counts_across_all_seven_metric_fields():
    report = build_data_quality_report([_quote()], gated_out={})
    assert report["missing_fields"] == {
        "trailing_pe": 1, "price_to_book": 1, "return_on_equity": 1, "profit_margins": 1,
        "revenue_growth": 1, "earnings_growth": 1, "momentum_6m": 1,
    }
