from equity_scout.data.universe_storage import (
    init_universe_db,
    load_latest_universe_snapshot,
    load_universe_snapshot,
    save_universe_snapshot,
)
from equity_scout.models import Instrument

_AAPL = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Technology")
_SAP = Instrument("SAP.DE", "SAP", "XETRA", "EU", "EUR", "Software")


def test_save_and_load_latest_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    init_universe_db(db)
    save_universe_snapshot(db, as_of="2026-06-24", instruments=[_AAPL])
    save_universe_snapshot(db, as_of="2026-07-02", instruments=[_AAPL, _SAP])

    as_of, instruments = load_latest_universe_snapshot(db)
    assert as_of == "2026-07-02"
    assert [i.ticker for i in instruments] == ["AAPL", "SAP.DE"]


def test_older_snapshots_stay_recoverable_not_overwritten(tmp_path):
    """The whole point of historizing: refreshing today must not erase what the universe looked
    like on an earlier as_of date (survivorship-bias avoidance for later backtest/ML use)."""
    db = tmp_path / "t.db"
    init_universe_db(db)
    save_universe_snapshot(db, as_of="2026-06-24", instruments=[_AAPL])
    save_universe_snapshot(db, as_of="2026-07-02", instruments=[_AAPL, _SAP])

    old = load_universe_snapshot(db, "2026-06-24")
    assert [i.ticker for i in old] == ["AAPL"]


def test_resaving_same_as_of_date_replaces_not_duplicates(tmp_path):
    db = tmp_path / "t.db"
    init_universe_db(db)
    save_universe_snapshot(db, as_of="2026-07-02", instruments=[_AAPL])
    save_universe_snapshot(db, as_of="2026-07-02", instruments=[_AAPL, _SAP])  # re-run same day

    snapshot = load_universe_snapshot(db, "2026-07-02")
    assert [i.ticker for i in snapshot] == ["AAPL", "SAP.DE"]


def test_load_latest_returns_none_on_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    init_universe_db(db)
    assert load_latest_universe_snapshot(db) is None


def test_load_snapshot_returns_none_for_missing_date(tmp_path):
    db = tmp_path / "t.db"
    init_universe_db(db)
    save_universe_snapshot(db, as_of="2026-07-02", instruments=[_AAPL])
    assert load_universe_snapshot(db, "1999-01-01") is None
