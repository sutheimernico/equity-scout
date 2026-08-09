"""Insider-cluster shadow detection: the live 3-distinct-insider rule, PIT t0, no duplicates."""
from __future__ import annotations

from equity_scout.evidence.base import SOURCE_CONGRESS, SOURCE_INSIDER, SOURCE_INSIDER_SHADOW
from equity_scout.evidence.insider_shadow import (
    SHADOW_HORIZON_TRADING_DAYS,
    STUDY_PRIOR,
    detect_clusters,
    shadow_events,
)


def _insider_event(ticker: str, insider: str, filing_date: str, key: str) -> dict:
    """One stored evidence_events row as events_in_window hands it back."""
    return {
        "source": SOURCE_INSIDER,
        "ticker": ticker,
        "event_key": key,
        "event_date": filing_date,
        "details": {"insider": insider, "filing_date": filing_date, "role": "director"},
    }


def _cluster_rows(ticker: str = "AAA", n: int = 3) -> list[dict]:
    return [
        _insider_event(ticker, f"Insider {i}", f"2026-08-0{i + 1}", f"acc{i}-2026-08-0{i + 1}")
        for i in range(n)
    ]


def test_two_insiders_are_not_a_cluster():
    assert detect_clusters({"AAA": _cluster_rows(n=2)}) == []


def test_three_distinct_insiders_are_a_cluster():
    clusters = detect_clusters({"AAA": _cluster_rows(n=3)})
    assert [c.ticker for c in clusters] == ["AAA"]
    assert clusters[0].insiders == ("Insider 0", "Insider 1", "Insider 2")


def test_same_insider_filing_three_times_is_not_a_cluster():
    """Three filings by ONE person is routine accumulation, not independent conviction."""
    rows = [
        _insider_event("AAA", "Solo Buyer", f"2026-08-0{i + 1}", f"acc{i}") for i in range(3)
    ]
    assert detect_clusters({"AAA": rows}) == []


def test_other_sources_never_count_toward_the_cluster():
    rows = _cluster_rows(n=2) + [
        {
            "source": SOURCE_CONGRESS,
            "ticker": "AAA",
            "event_key": "c1",
            "event_date": "2026-08-04",
            "details": {"politician": "Jane Doe"},
        }
    ]
    assert detect_clusters({"AAA": rows}) == []


def test_t0_is_the_latest_filing_date_in_the_cluster():
    """Only when the LAST buy was filed was the full cluster knowable (P2a PIT rule)."""
    clusters = detect_clusters({"AAA": _cluster_rows(n=3)})
    assert clusters[0].t0 == "2026-08-03"


def test_shadow_event_carries_the_pre_registered_horizon():
    events = shadow_events(detect_clusters({"AAA": _cluster_rows(n=3)}))
    assert len(events) == 1
    event = events[0]
    assert event.source == SOURCE_INSIDER_SHADOW
    assert event.ticker == "AAA"
    assert event.event_key == "2026-08-03-cluster3"
    assert event.event_date == "2026-08-03"
    assert event.details["horizon_trading_days"] == SHADOW_HORIZON_TRADING_DAYS
    assert event.details["n_insiders"] == 3
    assert event.details["shadow_only"] is True


def test_a_grown_cluster_gets_a_distinct_event_key():
    """A fourth buyer is a different fact; the ledger's UNIQUE key must be able to see it."""
    three = shadow_events(detect_clusters({"AAA": _cluster_rows(n=3)}))[0]
    four = shadow_events(detect_clusters({"AAA": _cluster_rows(n=4)}))[0]
    assert three.event_key != four.event_key


def test_tickers_with_an_open_prediction_are_skipped():
    """One open shadow prediction per ticker: re-registering the same signal would inflate
    n with two almost perfectly correlated outcomes."""
    clusters = detect_clusters({"AAA": _cluster_rows(n=3), "BBB": _cluster_rows("BBB", 3)})
    events = shadow_events(clusters, skip_tickers=frozenset({"AAA"}))
    assert [e.ticker for e in events] == ["BBB"]


def test_prior_is_the_measured_study_cell():
    """The forward track must never be readable without the prior it exists to test."""
    assert STUDY_PRIOR["n_measured"] == 13694
    assert STUDY_PRIOR["mean_relative_return"] == 0.0255
    assert STUDY_PRIOR["stderr"] == 0.0067
    assert STUDY_PRIOR["hit_rate_validate"] == 0.4292
    # The out-of-sample pair is the reason this is a shadow lane: +0.77% +/- 0.79pp.
    assert STUDY_PRIOR["validate_mean_relative_return"] < STUDY_PRIOR["validate_stderr"]
    assert "Ausreißern" in STUDY_PRIOR["caveat"]
