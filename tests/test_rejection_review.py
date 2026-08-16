"""Nightly resolution of the no-trade book: what would the rejected trades have done?"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from equity_scout.exits import ExitRules
from equity_scout.rejection_review import resolve_swing_rejections

RULES = ExitRules(profit_target=0.05, stop_loss=0.03, max_holding_days=7)
NOW = datetime(2026, 8, 1, 2, 30, tzinfo=timezone.utc)


def _rejection(rid: int, ticker: str, seen_at: str) -> dict:
    return {"id": rid, "lane": "swing", "ticker": ticker, "seen_at": seen_at,
            "reason": "not_bullish", "ref_price": None, "detail": "unknown headline"}


def _closes(ticker_start: str, values: list[float]) -> pd.Series:
    index = pd.bdate_range(ticker_start, periods=len(values))
    return pd.Series(values, index=index)


def test_resolves_with_the_lanes_own_exit_rules() -> None:
    """Entry on the close AFTER the event (same convention as lane_tuning.evaluate),
    then the live exit rules decide — a profit run resolves as the target, a slide as
    the stop, with the simulated return attached."""
    rejections = [
        _rejection(1, "WIN", "2026-07-06T14:00:00+00:00"),
        _rejection(2, "LOSE", "2026-07-06T14:00:00+00:00"),
    ]
    closes = {
        # event lands 07-06 (Mon); entry next close 07-07 at 100
        "WIN": _closes("2026-07-06", [99.0, 100.0, 103.0, 106.0, 106.0]),
        "LOSE": _closes("2026-07-06", [99.0, 100.0, 98.0, 96.0, 96.0]),
    }
    resolved = {r["id"]: r for r in resolve_swing_rejections(rejections, closes, RULES, now=NOW)}
    assert resolved[1]["sim_return"] == pytest.approx(0.06)
    assert resolved[1]["sim_exit_reason"].startswith("Kursziel")
    assert resolved[2]["sim_return"] == pytest.approx(-0.04)
    assert resolved[2]["sim_exit_reason"].startswith("Stop-Loss")
    assert resolved[1]["resolved_at"] == NOW.isoformat(timespec="seconds")


def test_young_rejection_without_a_fired_exit_stays_open() -> None:
    """A series that has not yet hit any rule is not resolved early — cutting it off
    would systematically truncate exactly the trades that run longest."""
    rejections = [_rejection(1, "FLAT", "2026-07-29T14:00:00+00:00")]
    closes = {"FLAT": _closes("2026-07-29", [100.0, 100.2, 100.1])}
    assert resolve_swing_rejections(rejections, closes, RULES, now=NOW) == []


def test_old_rejection_resolves_even_without_an_exit_or_data() -> None:
    """Past the grace window a rejection must close: with the last observation if a
    series exists, as 'keine Daten' if none ever appeared (delisted, never quoted)."""
    rejections = [
        _rejection(1, "STUCK", "2026-07-01T14:00:00+00:00"),
        _rejection(2, "GONE", "2026-07-01T14:00:00+00:00"),
    ]
    closes = {"STUCK": _closes("2026-07-01", [100.0, 100.0, 101.0])}
    resolved = {r["id"]: r for r in resolve_swing_rejections(rejections, closes, RULES, now=NOW)}
    assert resolved[1]["sim_return"] == pytest.approx(0.01)
    assert resolved[1]["sim_exit_reason"] == "Reihe zu Ende"
    assert resolved[2]["sim_return"] is None
    assert resolved[2]["sim_exit_reason"] == "keine Daten"


def test_event_from_tonight_waits_for_its_entry_close() -> None:
    """seen_at on the newest bar: the entry close does not exist yet — stay open."""
    rejections = [_rejection(1, "FRESH", "2026-07-31T20:00:00+00:00")]
    closes = {"FRESH": _closes("2026-07-29", [100.0, 100.0, 100.0])}  # last bar 07-31
    assert resolve_swing_rejections(rejections, closes, RULES, now=NOW) == []


def test_script_settles_open_rows_against_a_faked_panel(tmp_path, monkeypatch) -> None:
    """End to end: open st_rejections rows + a canned price panel -> resolved rows in the
    DB and an honest gross-only summary line."""
    import scripts.run_rejection_review as script
    from equity_scout.market import PricePanel
    from equity_scout.shortterm_storage import (
        load_open_rejections,
        load_resolved_rejections,
        record_rejections,
    )

    db = str(tmp_path / "shortterm.db")
    record_rejections(db, [
        {"lane": "swing", "ticker": "WIN", "seen_at": "2026-07-06T14:00:00+00:00",
         "reason": "not_bullish", "ref_price": None, "detail": "unknown headline"},
    ])
    index = pd.bdate_range("2026-07-06", periods=5)
    panel = PricePanel(pd.DataFrame({"WIN": [99.0, 100.0, 103.0, 106.0, 106.0]}, index=index))
    monkeypatch.setattr(script, "load_price_history", lambda *a, **k: panel)

    out = script.run_rejection_review(db, now=NOW)
    assert "1 von 1" in out
    assert "BRUTTO" in out
    assert load_open_rejections(db, "swing") == []
    resolved = load_resolved_rejections(db, "swing")
    assert resolved[0]["sim_return"] == pytest.approx(0.06)
