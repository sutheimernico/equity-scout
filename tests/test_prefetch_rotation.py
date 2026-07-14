"""Prefetch rotation: deterministic per date, full coverage across a rotation cycle."""
from datetime import date

from equity_scout.data.fetch import rotation_segment


def test_same_date_same_segment():
    tickers = [f"T{i}" for i in range(100)]
    a = rotation_segment(tickers, segments=6, on=date(2026, 7, 14))
    b = rotation_segment(tickers, segments=6, on=date(2026, 7, 14))
    assert a == b and len(a) > 0


def test_six_consecutive_days_cover_everything():
    tickers = [f"T{i:03d}" for i in range(100)]
    covered: set[str] = set()
    for day in range(14, 20):
        covered.update(rotation_segment(tickers, segments=6, on=date(2026, 7, day)))
    assert covered == set(tickers)


def test_segments_are_disjoint():
    tickers = [f"T{i:03d}" for i in range(100)]
    seen: set[str] = set()
    for day in range(14, 20):
        seg = set(rotation_segment(tickers, segments=6, on=date(2026, 7, day)))
        assert not (seen & seg)
        seen |= seg
