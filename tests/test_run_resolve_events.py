"""Resolve-CLI tests for the event-reaction study (Strang B4): queue new classified
events, resolve due ones via an injected price fetch, leave fresh ones pending."""
from __future__ import annotations

import sys

import pandas as pd

import scripts.run_resolve_events as resolve_mod
from equity_scout.evidence.event_classifier import ClassifiedEvent
from equity_scout.evidence.event_reactions import aggregate_reactions, pending_reactions
from equity_scout.evidence.event_storage import save_classified_events
from equity_scout.market import PricePanel
from scripts.run_resolve_events import main, run_resolve_events

# Post-close (after 16:00 ET on 2026-01-05) so 2026-01-05's close is a settled anchor
# and its full 5d forward window sits inside the panel below.
SEEN_AT_OLD = "2026-01-05T22:00:00+00:00"
SEEN_AT_FRESH = "2026-06-01T09:00:00+00:00"  # panel below has no future data past this


def _panel() -> PricePanel:
    idx = pd.bdate_range("2026-01-05", periods=30)
    closes = pd.Series([100.0 + i for i in range(len(idx))], index=idx)
    return PricePanel(pd.DataFrame({"AAA": closes}))


def _fetch(panel: PricePanel):
    return lambda tickers, start: panel


def _event(**overrides) -> ClassifiedEvent:
    base = dict(
        ticker="AAA", event_type="beat", source="news",
        published_at="2026-01-05T08:00:00+00:00", detail="AAA beats estimates",
        event_key="news-AAA-k1",
    )
    base.update(overrides)
    return ClassifiedEvent(**base)


def test_resolve_cli_queues_and_resolves_a_due_event(tmp_path):
    db = str(tmp_path / "ev.db")
    save_classified_events(db, [_event()], seen_at=SEEN_AT_OLD)

    result = run_resolve_events(db, fetch_prices=_fetch(_panel()))

    assert result["resolved"] == 1
    assert result["still_pending"] == 0
    agg = aggregate_reactions(db)
    assert agg["n_resolved"] == 1
    assert agg["by_event_type"]["beat"]["5d"]["n"] == 1


def test_resolve_cli_leaves_fresh_event_pending(tmp_path):
    db = str(tmp_path / "ev.db")
    save_classified_events(
        db, [_event(event_key="k2")], seen_at=SEEN_AT_FRESH
    )

    result = run_resolve_events(db, fetch_prices=_fetch(_panel()))

    assert result["resolved"] == 0
    assert result["still_pending"] == 1
    assert len(pending_reactions(db)) == 1


def test_resolve_cli_skips_non_directional_events(tmp_path):
    db = str(tmp_path / "ev.db")
    save_classified_events(
        db, [_event(event_key="k3", event_type="unknown")], seen_at=SEEN_AT_OLD
    )
    result = run_resolve_events(db, fetch_prices=_fetch(_panel()))
    assert result == {"resolved": 0, "still_pending": 0}


def test_resolve_main_happy_path_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "ev.db")
    save_classified_events(db, [_event()], seen_at=SEEN_AT_OLD)
    monkeypatch.setattr(resolve_mod, "_fetch_price_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(sys, "argv", ["run_resolve_events.py", "--db", db])

    assert main() == 0
    assert aggregate_reactions(db)["n_resolved"] == 1
    assert "Event-Reaktionen" in capsys.readouterr().out
