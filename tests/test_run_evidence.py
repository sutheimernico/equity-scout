"""Evidence-CLI orchestration: store + ledger-log per collector, degrade per source."""
from __future__ import annotations

from equity_scout.evidence.base import (
    SOURCE_13F,
    SOURCE_CONGRESS,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    CollectorResult,
    EvidenceEvent,
)
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.storage import events_in_window
from scripts.run_evidence import run_evidence

NOW = "2026-07-05T12:00:00+00:00"


def _event(source: str, ticker: str, key: str) -> EvidenceEvent:
    return EvidenceEvent(
        source=source, ticker=ticker, event_key=key, event_date="2026-07-01",
        details={"politician": "Jane Doe", "filing_date": "2026-07-01"},
    )


def _ok(source: str, events: list[EvidenceEvent]) -> CollectorResult:
    return CollectorResult(source, STATUS_OK, events=events, detail="fixture")


def test_run_evidence_stores_and_ledgers_new_events(tmp_path):
    db = str(tmp_path / "ev.db")
    collectors = [
        lambda: _ok(SOURCE_CONGRESS, [_event(SOURCE_CONGRESS, "AAA", "k1")]),
        lambda: _ok(SOURCE_13F, [_event(SOURCE_13F, "BBB", "k2")]),
    ]
    result = run_evidence(db, collectors, now=NOW)
    assert result["new_events"] == 2
    assert result["ledgered"] == 2
    assert set(events_in_window(db, window_days=30, now=NOW)) == {"AAA", "BBB"}
    stats = stats_by_source(db)
    assert stats[SOURCE_CONGRESS]["n_open"] == 1
    assert stats[SOURCE_13F]["n_open"] == 1


def test_run_evidence_second_run_is_idempotent(tmp_path):
    """Re-collecting the same fact must inflate neither the store nor the ledger."""
    db = str(tmp_path / "ev.db")
    collectors = [lambda: _ok(SOURCE_CONGRESS, [_event(SOURCE_CONGRESS, "AAA", "k1")])]
    assert run_evidence(db, collectors, now=NOW)["new_events"] == 1
    again = run_evidence(db, collectors, now=NOW)
    assert again["new_events"] == 0
    assert again["ledgered"] == 0
    assert stats_by_source(db)[SOURCE_CONGRESS]["n_open"] == 1


def test_run_evidence_reports_failed_source_and_continues(tmp_path):
    db = str(tmp_path / "ev.db")
    collectors = [
        lambda: CollectorResult(SOURCE_CONGRESS, STATUS_FETCH_FAILED, detail="timeout"),
        lambda: _ok(SOURCE_13F, [_event(SOURCE_13F, "BBB", "k2")]),
    ]
    result = run_evidence(db, collectors, now=NOW)
    assert result["new_events"] == 1  # the healthy source still landed
    assert any("[fetch_failed]" in line and "timeout" in line for line in result["lines"])


def test_news_scope_is_the_tracked_tickers_union(monkeypatch) -> None:
    """Symmetry fix (2026-08-17): bullish events can ONLY come from news, but news was
    fetched for the 30-ticker watchlist snapshot while 8-K already used the broader
    tracked_tickers union. Measured cost: 15 beats in 29 days — the lane tuner needs 60."""
    import scripts.run_evidence as script

    calls: list[str] = []

    class FakeNews:
        def __init__(self, limit: int) -> None:
            self.limit = limit

        def news_for(self, ticker: str) -> list[dict]:
            calls.append(ticker)
            return [{"title": f"{ticker} headline"}]

    monkeypatch.setattr(script, "tracked_tickers", lambda db: {"AAPL", "HELD"})
    monkeypatch.setattr(script, "YFinanceNews", FakeNews)
    news = script._tracked_news("some.db")
    assert sorted(calls) == ["AAPL", "HELD"]
    assert set(news) == {"AAPL", "HELD"}


def test_news_scope_empty_union_yields_nothing(monkeypatch) -> None:
    import scripts.run_evidence as script

    monkeypatch.setattr(script, "tracked_tickers", lambda db: set())
    assert script._tracked_news("some.db") == {}
