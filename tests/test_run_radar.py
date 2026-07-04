"""CLI end-to-end with fakes: stored run -> watchlist in DB + JSON artifact."""
from __future__ import annotations

import json

from equity_scout.radar_storage import load_latest_watchlist
from scripts.run_radar import _finalists_from_run, run_radar
from tests.test_signals import downtrend_history


def _stored_run() -> dict:
    def pick(ticker: str) -> dict:
        return {
            "instrument": {"ticker": ticker, "name": f"{ticker} Inc", "sector": "Tech"},
            "bucket": "core",
            "rank": 1,
            "composite": 0.8,
            "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.5, "growth": 0.6},
        }

    return {"created_at": "2026-07-04T06:00:00", "buckets": {"core": [pick("DIP")]}}


def test_finalists_from_run_flattens_buckets():
    finalists = _finalists_from_run(_stored_run())
    assert finalists == [
        {
            "ticker": "DIP",
            "name": "DIP Inc",
            "bucket": "core",
            "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.5, "growth": 0.6},
        }
    ]


def test_run_radar_writes_db_snapshot_and_json_artifact(tmp_path):
    db = str(tmp_path / "radar.db")
    out = tmp_path / "watchlist.json"
    count = run_radar(
        run=_stored_run(),
        db_path=db,
        json_out=str(out),
        created_at="2026-07-04T12:00:00",
        fetch_history=lambda ticker: downtrend_history(),
    )
    assert count == 1
    snapshot = load_latest_watchlist(db)
    assert snapshot["entries"][0]["ticker"] == "DIP"
    artifact = json.loads(out.read_text())
    assert artifact["created_at"] == "2026-07-04T12:00:00"
    assert artifact["entries"][0]["entry_zone_high"] > 0
