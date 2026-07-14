"""Persistent instrument metadata: sectors discovered live must survive cache hits."""
from equity_scout.data.universe_storage import (
    init_universe_db,
    load_instrument_meta,
    upsert_instrument_meta,
)


def test_upsert_and_load_roundtrip(tmp_path):
    db = tmp_path / "u.db"
    init_universe_db(db)
    upsert_instrument_meta(db, {"AAPL": "Technology", "KO": "Consumer Defensive"},
                           source="yfinance.info", updated_at="2026-07-14")
    assert load_instrument_meta(db) == {"AAPL": "Technology", "KO": "Consumer Defensive"}


def test_upsert_overwrites_and_empty_dict_is_noop(tmp_path):
    db = tmp_path / "u.db"
    init_universe_db(db)
    upsert_instrument_meta(db, {}, source="s", updated_at="2026-07-14")
    upsert_instrument_meta(db, {"AAPL": "Tech"}, source="s", updated_at="2026-07-14")
    upsert_instrument_meta(db, {"AAPL": "Technology"}, source="s", updated_at="2026-07-15")
    assert load_instrument_meta(db) == {"AAPL": "Technology"}


def test_load_from_missing_table_returns_empty(tmp_path):
    assert load_instrument_meta(tmp_path / "missing.db") == {}
