from equity_scout.history import pick_churn
from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.storage import init_db, load_run_summaries, save_run


def test_pick_churn_added_removed_stable():
    churn = pick_churn(["AAPL", "MSFT"], ["MSFT", "NVDA"])
    assert churn["added"] == ["NVDA"]
    assert churn["removed"] == ["AAPL"]
    assert churn["stable"] == ["MSFT"]


def _run(ts, ticker):
    inst = Instrument(ticker, ticker, "US", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5})
    return RunResult(ts, 10, {}, {"balanced": [pick]},
                     gate_stats={"total_gated": 0, "by_reason": {}, "by_region": {}})


def test_load_run_summaries_newest_first(tmp_path):
    db = tmp_path / "h.db"
    init_db(db)
    save_run(db, _run("2026-06-24T10:00:00", "AAPL"))
    save_run(db, _run("2026-06-24T12:00:00", "MSFT"))
    summaries = load_run_summaries(db, limit=10)
    assert len(summaries) == 2
    assert summaries[0]["created_at"] == "2026-06-24T12:00:00"  # newest first
    assert summaries[0]["picks"]["balanced"] == ["MSFT"]
    assert summaries[0]["total_gated"] == 0
