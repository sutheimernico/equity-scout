"""Evidence-resolve CLI: fill due rows from real forward prices, leave the rest open."""
from __future__ import annotations

import sys

import pandas as pd

import scripts.run_resolve_evidence as resolve_mod
from equity_scout.evidence.base import SOURCE_CONGRESS, EvidenceEvent
from equity_scout.evidence.ledger import log_evidence, stats_by_source
from equity_scout.market import PricePanel
from scripts.run_resolve_evidence import main, run_resolve_evidence

HORIZON = 20


def _event(ticker: str, key: str) -> EvidenceEvent:
    return EvidenceEvent(
        source=SOURCE_CONGRESS, ticker=ticker, event_key=key, event_date="2026-01-02",
        details={"politician": "Jane Doe"},
    )


def _panel() -> PricePanel:
    """AAA outruns SPY on every horizon → positive relative return, label 1."""
    idx = pd.bdate_range("2025-06-01", periods=400)
    n = len(idx)
    data = {
        "SPY": [100.0 * 1.0002**i for i in range(n)],
        "AAA": [100.0 * 1.0008**i for i in range(n)],
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def _fetch(panel: PricePanel):
    return lambda tickers, start: panel


def test_resolve_evidence_resolves_due_and_leaves_not_yet_due_open(tmp_path):
    db = str(tmp_path / "ev.db")
    # Due at run time (logged 2026-01-05, horizon 20d) ...
    log_evidence(db, [_event("AAA", "due")], now="2026-01-05T00:00:00+00:00",
                 horizon_days=HORIZON)
    # ... and one logged much later: not yet due.
    log_evidence(db, [_event("AAA", "later")], now="2026-05-01T00:00:00+00:00",
                 horizon_days=HORIZON)

    result = run_resolve_evidence(
        db, now="2026-03-01T00:00:00+00:00", fetch_prices=_fetch(_panel())
    )

    assert result == {"resolved": 1, "still_open": 1}
    stats = stats_by_source(db)[SOURCE_CONGRESS]
    assert stats["n_resolved"] == 1 and stats["n_open"] == 1
    assert stats["hit_rate"] == 1.0  # AAA beat SPY in the synthetic panel
    assert stats["mean_relative_return"] > 0


def test_resolve_evidence_leaves_unknown_ticker_open(tmp_path):
    """A ticker missing from the price panel resolves honestly LATER, never with a guess."""
    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event("ZZZ", "due")], now="2026-01-05T00:00:00+00:00",
                 horizon_days=HORIZON)
    result = run_resolve_evidence(
        db, now="2026-03-01T00:00:00+00:00", fetch_prices=_fetch(_panel())
    )
    assert result == {"resolved": 0, "still_open": 1}


def test_resolve_evidence_main_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event("AAA", "due")], now="2026-01-05T00:00:00+00:00",
                 horizon_days=HORIZON)
    monkeypatch.setattr(resolve_mod, "_fetch_price_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(sys, "argv", ["run_resolve_evidence.py", "--db", db])

    assert main() == 0
    assert stats_by_source(db)[SOURCE_CONGRESS]["n_resolved"] == 1
    assert "Evidenz aufgelöst: 1" in capsys.readouterr().out
