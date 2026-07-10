"""Person-score CLI: backfill via filer files, own-store fund calls, persisted scores."""
from __future__ import annotations

import sys

import pandas as pd

import scripts.run_person_scores as scores_mod
from equity_scout.evidence.base import SOURCE_13F, SOURCE_CONGRESS, EvidenceEvent
from equity_scout.evidence.person_storage import load_person_scores
from equity_scout.evidence.storage import record_events
from equity_scout.market import PricePanel
from scripts.run_person_scores import main, run_person_scores

NOW = "2026-07-10T12:00:00+00:00"


def _seed_congress_event(db: str, filer_id: str = "house_jane_doe") -> None:
    record_events(
        db,
        [
            EvidenceEvent(
                source=SOURCE_CONGRESS, ticker="WIN",
                event_key=f"{filer_id}-2026-06-20-purchase", event_date="2026-06-25",
                details={"politician": "Jane Doe", "filer_id": filer_id,
                         "filing_date": "2026-06-25"},
            )
        ],
        now=NOW,
    )


def _seed_fund_events(db: str, n: int = 5) -> None:
    events = [
        EvidenceEvent(
            source=SOURCE_13F, ticker="WIN", event_key=f"scion-q{i}",
            event_date=f"2026-0{i + 1}-15",
            details={"fund": "Scion Asset Management", "change": "new",
                     "filed_at": f"2026-0{i + 1}-15"},
        )
        for i in range(n)
    ]
    record_events(db, events, now=NOW)


def _filer_payload(n_calls: int = 6) -> dict:
    days = pd.bdate_range("2025-07-01", periods=n_calls)
    return {
        "filer": {"full_name": "Jane Doe"},
        "trades": [
            {
                "transaction_type": "Purchase", "asset_type": "ST", "ticker": "WIN",
                "filing_date": d.date().isoformat(),
                "transaction_date": d.date().isoformat(),
            }
            for d in days
        ],
    }


def _panel() -> PricePanel:
    idx = pd.bdate_range("2025-06-01", periods=400)
    n = len(idx)
    return PricePanel(
        pd.DataFrame(
            {
                "SPY": [100.0 * 1.0002**i for i in range(n)],
                "WIN": [100.0 * 1.0008**i for i in range(n)],
            },
            index=idx,
        )
    )


def test_run_person_scores_backfills_scores_and_persists(tmp_path):
    db = str(tmp_path / "p.db")
    _seed_congress_event(db)
    result = run_person_scores(
        db, now=NOW,
        fetch_prices=lambda tickers, start: _panel(),
        fetch_filer=lambda filer_id: _filer_payload(),
    )
    assert result["persons"] == 1
    assert result["scoreable"] == 1
    assert result["backfill_calls"] == 6
    rows = load_person_scores(db)
    assert rows[0]["person"] == "Jane Doe"
    assert rows[0]["weighted_score"] > 0  # WIN beats SPY in the synthetic panel


def test_run_person_scores_scores_funds_from_own_store(tmp_path):
    db = str(tmp_path / "p.db")
    _seed_fund_events(db, n=5)
    result = run_person_scores(
        db, now=NOW,
        fetch_prices=lambda tickers, start: _panel(),
        fetch_filer=lambda filer_id: None,
    )
    assert result["fund_calls"] == 5
    rows = load_person_scores(db)
    assert rows[0]["person"] == "Scion Asset Management"
    assert rows[0]["source"] == SOURCE_13F


def test_run_person_scores_counts_failed_filer_fetches(tmp_path):
    db = str(tmp_path / "p.db")
    _seed_congress_event(db)
    result = run_person_scores(
        db, now=NOW,
        fetch_prices=lambda tickers, start: _panel(),
        fetch_filer=lambda filer_id: None,  # mirror file gone -> counted, not raised
    )
    assert result["filer_fetch_failed"] == 1
    assert result.get("persons", 0) == 0 or load_person_scores(db) == []


def test_run_person_scores_drops_and_counts_calls_older_than_lookback(tmp_path):
    db = str(tmp_path / "p.db")
    _seed_congress_event(db)
    old = {
        "filer": {"full_name": "Jane Doe"},
        "trades": [
            {
                "transaction_type": "Purchase", "asset_type": "ST", "ticker": "WIN",
                "filing_date": "2019-01-05", "transaction_date": "2019-01-02",
            }
        ],
    }
    result = run_person_scores(
        db, now=NOW,
        fetch_prices=lambda tickers, start: _panel(),
        fetch_filer=lambda filer_id: old,
        lookback_years=3,
    )
    assert result["too_old"] == 1
    assert result["calls"] == 0


def test_main_prints_summary(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "p.db")
    _seed_congress_event(db)
    monkeypatch.setattr(scores_mod, "_fetch_price_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(scores_mod, "fetch_filer_history", lambda filer_id: _filer_payload())
    monkeypatch.setattr(sys, "argv", ["run_person_scores.py", "--db", db])

    assert main() == 0
    out = capsys.readouterr().out
    assert "Personen bewertet: 1 (davon mit Score: 1)" in out


def test_run_person_scores_parses_filer_id_from_event_key_fallback(tmp_path):
    """Events collected before details carried filer_id: the event_key's embedded ISO
    date has dashes — a naive rsplit corrupted the id (13/13 fetch failures live)."""
    db = str(tmp_path / "p.db")
    record_events(
        db,
        [
            EvidenceEvent(
                source=SOURCE_CONGRESS, ticker="WIN",
                event_key="house_jane_doe-2026-06-20-purchase", event_date="2026-06-25",
                details={"politician": "Jane Doe", "filing_date": "2026-06-25"},
            )
        ],
        now=NOW,
    )
    requested: list[str] = []

    def spy_fetch(filer_id: str) -> dict:
        requested.append(filer_id)
        return _filer_payload()

    result = run_person_scores(
        db, now=NOW, fetch_prices=lambda tickers, start: _panel(), fetch_filer=spy_fetch
    )
    assert requested == ["house_jane_doe"]
    assert result["persons"] == 1
