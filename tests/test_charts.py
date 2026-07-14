"""Chart rendering is pure: data in, PNG bytes out."""
from datetime import datetime, timedelta

import pytest

from equity_scout.charts import render_year_chart, year_return


def _series(values: list[float]) -> tuple[list[datetime], list[float]]:
    start = datetime(2025, 7, 15)
    return [start + timedelta(days=i) for i in range(len(values))], values


def test_render_year_chart_returns_png_bytes():
    dates, closes = _series([100.0 + i * 0.3 for i in range(250)])
    png = render_year_chart("NVDA", dates, closes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5000


def test_render_year_chart_rejects_empty_series():
    with pytest.raises(ValueError):
        render_year_chart("X", [], [])


def test_year_return():
    assert year_return([100.0, 138.0]) == pytest.approx(0.38)
    assert year_return([100.0]) is None
    assert year_return([]) is None
