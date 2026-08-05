"""Round-trip tests for insights_storage.py against a temp SQLite file."""
from __future__ import annotations

from equity_scout.insights_storage import (
    init_insights_db,
    load_insights,
    load_price_series,
    save_insight,
    save_price_series,
)


def test_save_and_load_one_insight(tmp_path):
    db = str(tmp_path / "t.db")
    save_insight(
        db, ticker="MU", generated_at="2026-08-05T18:00:00+00:00",
        business="Micron baut Speicherchips.",
        news_summary="Micron hebt die Prognose an.",
        headlines=["Micron raises guidance"], model="qwen2.5:7b",
    )
    rows = load_insights(db)
    assert set(rows) == {"MU"}
    assert rows["MU"]["business"] == "Micron baut Speicherchips."
    assert rows["MU"]["headlines"] == ["Micron raises guidance"]
    assert rows["MU"]["model"] == "qwen2.5:7b"


def test_saving_the_same_ticker_twice_replaces_it(tmp_path):
    db = str(tmp_path / "t.db")
    for text in ("alt", "neu"):
        save_insight(
            db, ticker="MU", generated_at="2026-08-05T18:00:00+00:00",
            business=text, news_summary=None, headlines=[], model="qwen2.5:7b",
        )
    rows = load_insights(db)
    assert len(rows) == 1
    assert rows["MU"]["business"] == "neu"


def test_a_null_text_survives_the_round_trip(tmp_path):
    # A failed LLM call stores an honest null, and the card says so — it must not come
    # back as the string "None".
    db = str(tmp_path / "t.db")
    save_insight(
        db, ticker="AIRT", generated_at="2026-08-05T18:00:00+00:00",
        business=None, news_summary=None, headlines=[], model="qwen2.5:7b",
    )
    assert load_insights(db)["AIRT"]["business"] is None


def test_save_and_load_a_price_series(tmp_path):
    db = str(tmp_path / "t.db")
    save_price_series(
        db, ticker="MU", as_of="2026-08-05T18:00:00+00:00",
        first_date="2025-08-05", last_date="2026-08-05", closes=[10.0, 11.0, 12.5],
    )
    series = load_price_series(db)
    assert series["MU"]["closes"] == [10.0, 11.0, 12.5]
    assert series["MU"]["first_date"] == "2025-08-05"


def test_loading_from_a_fresh_db_returns_empty_dicts(tmp_path):
    # The API must survive a DB written before this migration existed.
    db = str(tmp_path / "fresh.db")
    assert load_insights(db) == {}
    assert load_price_series(db) == {}


def test_init_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    init_insights_db(db)
    init_insights_db(db)
    assert load_insights(db) == {}
