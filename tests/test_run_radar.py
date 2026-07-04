"""CLI end-to-end with fakes: stored run -> watchlist in DB + JSON artifact."""
from __future__ import annotations

import json
import sys

import scripts.run_radar as run_radar_mod
from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.storage import init_db, save_run
from scripts.run_radar import _finalists_from_run, main, run_radar
from tests.test_signals import downtrend_history


def test_main_exits_1_with_hint_on_fresh_uninitialized_db(tmp_path, monkeypatch, capsys):
    """A DB run_scout.py never touched has no `runs` table — main() must hint, not crash."""
    db = str(tmp_path / "fresh.db")
    monkeypatch.setattr(sys, "argv", ["run_radar.py", "--db", db])
    assert main() == 1
    assert "No screener run found" in capsys.readouterr().err


def test_main_happy_path_writes_db_and_artifact(tmp_path, monkeypatch, capsys):
    """End-to-end through main(): seeded scout run -> exit 0 + JSON artifact, no network."""
    db = str(tmp_path / "run.db")
    out = tmp_path / "watchlist.json"
    init_db(db)
    inst = Instrument("DIP", "DIP Inc", "NASDAQ", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.8,
                {"value": 0.8, "quality": 0.9, "momentum": 0.5, "growth": 0.6})
    save_run(db, RunResult("2026-07-04T06:00:00", 10, {}, {"balanced": [pick]}))
    monkeypatch.setattr(run_radar_mod, "fetch_entry_history", lambda t: downtrend_history())
    monkeypatch.setattr(sys, "argv", ["run_radar.py", "--db", db, "--json-out", str(out)])
    assert main() == 0
    assert "Watchlist saved: 1 entries." in capsys.readouterr().out
    artifact = json.loads(out.read_text())
    assert artifact["entries"][0]["ticker"] == "DIP"
    assert load_latest_watchlist(db)["entries"][0]["ticker"] == "DIP"


def _stored_run(*tickers: str) -> dict:
    def pick(ticker: str) -> dict:
        return {
            "instrument": {"ticker": ticker, "name": f"{ticker} Inc", "sector": "Tech"},
            "bucket": "core",
            "rank": 1,
            "composite": 0.8,
            "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.5, "growth": 0.6},
        }

    return {
        "created_at": "2026-07-04T06:00:00",
        "buckets": {"core": [pick(t) for t in (tickers or ("DIP",))]},
    }


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


def test_run_radar_writes_db_snapshot_and_json_artifact(tmp_path, capsys):
    db = str(tmp_path / "radar.db")
    out = tmp_path / "watchlist.json"
    count = run_radar(
        run=_stored_run("DIP", "GONE"),
        db_path=db,
        json_out=str(out),
        created_at="2026-07-04T12:00:00",
        fetch_history=lambda ticker: downtrend_history() if ticker == "DIP" else ([], [], []),
    )
    assert count == 1
    snapshot = load_latest_watchlist(db)
    assert snapshot["entries"][0]["ticker"] == "DIP"
    assert snapshot["skipped"] == {"GONE": "keine verwertbare Kurshistorie"}
    artifact = json.loads(out.read_text())
    assert artifact["created_at"] == "2026-07-04T12:00:00"
    assert artifact["entries"][0]["entry_zone_high"] > 0
    # skipped tickers are reported honestly on stdout, with the German reason
    assert "skipped GONE: keine verwertbare Kurshistorie" in capsys.readouterr().out
