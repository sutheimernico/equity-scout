"""Per-source count report for universe refresh: a silent shrink must be loud."""
from equity_scout.data.constituents import source_count_report


def test_report_flags_sources_below_floor():
    counts = [("Hang Seng Index", 85, 60), ("CSI 300", 12, 250)]
    lines, warnings = source_count_report(counts)
    assert any("Hang Seng Index" in ln and "85" in ln for ln in lines)
    assert warnings == ["CSI 300: 12 rows < floor 250 — page layout may have changed"]


def test_report_no_warnings_when_all_healthy():
    _, warnings = source_count_report([("A", 100, 50)])
    assert warnings == []
