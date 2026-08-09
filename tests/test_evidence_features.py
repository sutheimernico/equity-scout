"""PIT evidence-feature tests: what was knowable about insider clusters before `as_of`."""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from equity_scout.evidence.base import SOURCE_CONGRESS, SOURCE_INSIDER
from equity_scout.evidence.historical_storage import (
    HistoricalEvent,
    mark_resolved,
    mark_unresolvable,
    record_historical_events,
)
from equity_scout.ml.evidence_features import (
    EVIDENCE_FEATURE_COLUMNS,
    LONG_WINDOW_DAYS,
    SHORT_WINDOW_DAYS,
    EvidenceIndex,
    load_evidence_index,
)

NOW = "2026-08-07T12:00:00+00:00"


def _cluster(ticker: str, t0: str, n_insiders: int, *, source: str = SOURCE_INSIDER):
    return HistoricalEvent(
        source=source,
        person="",
        ticker=ticker,
        event_key=f"{ticker}-{t0}-cluster{n_insiders}",
        t0=t0,
        details={"n_insiders": n_insiders},
    )


def _index(*events) -> EvidenceIndex:
    """Index built straight from the dataclass, no DB — keeps the pure logic tests fast."""
    clusters: dict = {}
    for event in events:
        clusters.setdefault(event.ticker, []).append(
            (date.fromisoformat(event.t0), int(event.details["n_insiders"]))
        )
    for entries in clusters.values():
        entries.sort()
    return EvidenceIndex(clusters)


def _only_event_id(db: str) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT id FROM historical_events").fetchone()[0])


def test_unknown_ticker_is_all_zeros_never_none():
    """Absence of insider buying is a FACT, not a gap — the block never returns None (unlike
    `entry_features.build_feature_row`, whose None means 'cannot be computed honestly')."""
    features = _index().features("AAA", pd.Timestamp("2026-01-15"))
    assert list(features) == list(EVIDENCE_FEATURE_COLUMNS)
    assert set(features.values()) == {0.0}


def test_cluster_inside_the_short_window_sets_flag_size_and_count():
    index = _index(_cluster("AAA", "2026-01-02", 5))
    features = index.features("AAA", pd.Timestamp("2026-02-02"))
    assert features["ev_insider_cluster_91d"] == 1.0
    assert features["ev_insider_max_size_91d"] == 5.0
    assert features["ev_insider_count_365d"] == 1.0


def test_future_and_same_day_clusters_are_invisible():
    """Ruling 4: a filing stamped ON the decision date may have hit EDGAR after the close."""
    index = _index(_cluster("AAA", "2026-02-02", 4), _cluster("AAA", "2026-03-01", 9))
    assert index.features("AAA", pd.Timestamp("2026-02-02")) == {
        "ev_insider_cluster_91d": 0.0,
        "ev_insider_max_size_91d": 0.0,
        "ev_insider_count_365d": 0.0,
    }


def test_window_boundaries_are_half_open():
    """(as_of - window, as_of): a cluster exactly `window` days back is already out."""
    as_of = pd.Timestamp("2026-06-01")
    short_edge = (as_of - pd.Timedelta(days=SHORT_WINDOW_DAYS)).date().isoformat()
    long_edge = (as_of - pd.Timedelta(days=LONG_WINDOW_DAYS)).date().isoformat()
    index = _index(_cluster("AAA", short_edge, 6), _cluster("BBB", long_edge, 6))
    assert index.features("AAA", as_of)["ev_insider_cluster_91d"] == 0.0
    assert index.features("AAA", as_of)["ev_insider_count_365d"] == 1.0  # still inside the year
    assert index.features("BBB", as_of)["ev_insider_count_365d"] == 0.0


def test_max_size_is_the_max_inside_the_window_not_the_latest():
    index = _index(_cluster("AAA", "2026-01-05", 8), _cluster("AAA", "2026-02-05", 3))
    features = index.features("AAA", pd.Timestamp("2026-03-01"))
    assert features["ev_insider_max_size_91d"] == 8.0
    assert features["ev_insider_count_365d"] == 2.0


def test_tz_aware_as_of_raises_instead_of_silently_shifting_the_date():
    """A tz-aware timestamp maps to a different plain date depending on the zone — verified:
    2026-02-02 20:00 America/New_York is 2026-02-03 UTC. Picking one silently would make the
    same cluster visible or invisible depending on which zone happened to be passed in."""
    index = _index(_cluster("AAA", "2026-02-02", 4))
    tz_aware = pd.Timestamp("2026-02-02 20:00", tz="America/New_York")
    with pytest.raises(ValueError, match="tz-naive"):
        index.features("AAA", tz_aware)


def test_none_as_of_always_raises_regardless_of_ticker():
    """Same caller bug regardless of whether the ticker happens to have cluster history — before
    the fix, an unknown ticker's empty loop swallowed a None `as_of` into silent zeros while a
    known ticker raised TypeError deep inside a date comparison. Both paths must now raise
    ValueError up front."""
    index = _index(_cluster("AAA", "2026-01-02", 4))
    with pytest.raises(ValueError):
        index.features("AAA", None)
    with pytest.raises(ValueError):
        index.features("ZZZ", None)


def test_loader_reads_only_insider_clusters_from_the_store(tmp_path, capsys):
    db = str(tmp_path / "hist.db")
    record_historical_events(
        db,
        [
            _cluster("AAA", "2026-01-02", 4),
            _cluster("BBB", "2026-01-02", 7, source=SOURCE_CONGRESS),  # Non-Goal: never indexed
        ],
        now=NOW,
    )
    index = load_evidence_index(db)
    assert index.features("AAA", pd.Timestamp("2026-02-01"))["ev_insider_cluster_91d"] == 1.0
    assert index.features("BBB", pd.Timestamp("2026-02-01"))["ev_insider_cluster_91d"] == 0.0
    assert "WARNUNG" not in capsys.readouterr().out  # AAA is a real insider row — no false alarm


def test_missing_table_raises_instead_of_reading_as_nobody_ever_bought(tmp_path):
    """A path that was never backfilled must fail loudly, not silently produce an index that
    scores every ticker's insider evidence as zero."""
    db = str(tmp_path / "never_touched.db")
    with pytest.raises(ValueError, match="wrong db_path"):
        load_evidence_index(db)


def test_zero_insider_rows_warns_and_returns_empty_index(tmp_path, capsys):
    """Table exists (congress backfill ran) but has no insider rows at all — a real, if
    suspicious, situation: warn loudly instead of raising, then return the correctly empty
    index."""
    db = str(tmp_path / "hist.db")
    record_historical_events(
        db, [_cluster("BBB", "2026-01-02", 7, source=SOURCE_CONGRESS)], now=NOW
    )
    index = load_evidence_index(db)
    assert index.clusters == {}
    captured = capsys.readouterr()
    assert "WARNUNG" in captured.out
    assert "0 Insider-Cluster" in captured.out


def test_forward_returns_can_never_reach_a_feature(tmp_path):
    """Ruling 5 (leakage regression): r_* columns are measured AFTER t0. Writing an absurd
    forward return must not move a single feature value."""
    db = str(tmp_path / "hist.db")
    record_historical_events(db, [_cluster("AAA", "2026-01-02", 4)], now=NOW)
    as_of = pd.Timestamp("2026-02-01")
    before = load_evidence_index(db).features("AAA", as_of)
    assert mark_resolved(db, _only_event_id(db), {"r_1w": 999.0, "r_3m": -999.0}, now=NOW)
    assert load_evidence_index(db).features("AAA", as_of) == before


def test_unresolvable_rows_stay_in_the_index(tmp_path):
    """Ruling 6: a delisted name still had a real cluster at t0 — dropping it would rebuild
    the survivorship bias P2a exists to count."""
    db = str(tmp_path / "hist.db")
    record_historical_events(db, [_cluster("AAA", "2026-01-02", 4)], now=NOW)
    assert mark_unresolvable(db, _only_event_id(db), "no_price_history", now=NOW)
    features = load_evidence_index(db).features("AAA", pd.Timestamp("2026-02-01"))
    assert features["ev_insider_cluster_91d"] == 1.0


def test_malformed_rows_are_skipped_never_guessed(tmp_path, capsys):
    db = str(tmp_path / "hist.db")
    record_historical_events(
        db,
        [
            HistoricalEvent(SOURCE_INSIDER, "", "AAA", "k1", "not-a-date", {"n_insiders": 4}),
            HistoricalEvent(SOURCE_INSIDER, "", "BBB", "k2", "2026-01-02", {"insiders": ["x"]}),
            # A fractional insider count is a measurement error, not a cluster size — strict
            # `isinstance(int)` (excluding bool) must reject it, not silently truncate via int().
            HistoricalEvent(SOURCE_INSIDER, "", "CCC", "k3", "2026-01-02", {"n_insiders": 3.9}),
        ],
        now=NOW,
    )
    index = load_evidence_index(db)
    assert index.clusters == {}
    assert "3 von 3 Insider-Zeilen übersprungen" in capsys.readouterr().out
