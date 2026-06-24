from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.storage import init_db, load_latest_run, save_run


def _run(ts):
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.6, "quality": 0.7, "momentum": 0.5, "growth": 0.5},
                thesis="ok")
    return RunResult(created_at=ts, universe_size=10,
                     gated_out={"BAD": "missing price history"},
                     buckets={"balanced": [pick]})


def test_save_and_load_latest_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    save_run(db, _run("2026-06-24T10:00:00"))
    save_run(db, _run("2026-06-24T12:00:00"))
    latest = load_latest_run(db)
    assert latest is not None
    assert latest.created_at == "2026-06-24T12:00:00"
    assert latest.buckets["balanced"][0].instrument.ticker == "AAPL"
    assert latest.gated_out["BAD"].startswith("missing")


def test_load_latest_returns_none_on_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    init_db(db)
    assert load_latest_run(db) is None
