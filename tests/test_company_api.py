"""Company-profile router: F-Score + next earnings per ticker, standalone include_router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from equity_scout.company_api import build_company_router
from equity_scout.earnings_storage import save_earnings_dates
from equity_scout.fscore import save_f_score


def make_client(tmp_path, today: str = "2026-08-07") -> tuple[str, TestClient]:
    db = str(tmp_path / "es.db")
    app = FastAPI()
    app.include_router(
        build_company_router(db, cache_db=str(tmp_path / "cache.db"), today_fn=lambda: today)
    )
    return db, TestClient(app)


def test_company_returns_fscore_and_next_earnings(tmp_path):
    db, client = make_client(tmp_path)
    save_f_score(
        db,
        "MU",
        {"score": 7, "evaluable": 9, "fiscal_year": 2025, "criteria": {"roa_positive": True}},
        computed_on="2026-08-06",
    )
    save_earnings_dates(db, "MU", ["2026-09-25"], fetched_on="2026-08-07T06:00:00+00:00")

    body = client.get("/api/company/MU").json()

    assert body["ticker"] == "MU"
    assert body["f_score"]["score"] == 7
    assert body["f_score"]["criteria"] == {"roa_positive": True}
    assert body["next_earnings"] == "2026-09-25"


def test_company_normalises_ticker_case_and_whitespace(tmp_path):
    db, client = make_client(tmp_path)
    save_earnings_dates(db, "MU", ["2026-09-25"], fetched_on="2026-08-07T06:00:00+00:00")

    body = client.get("/api/company/ mu ").json()

    assert body["ticker"] == "MU"
    assert body["next_earnings"] == "2026-09-25"


def test_company_unknown_ticker_yields_honest_nulls(tmp_path):
    _db, client = make_client(tmp_path)

    body = client.get("/api/company/NVDA").json()

    assert body == {
        "ticker": "NVDA",
        "f_score": None,
        "next_earnings": None,
        "metrics": None,
        "metrics_fetched_on": None,
    }


def test_company_serves_key_figures_from_the_quote_cache(tmp_path):
    """Kennzahlen come from the scout's read-through quote cache (the chat assistant's
    source) — never a live fetch in the request path."""
    from equity_scout.data.cache import QuoteCache

    _db, client = make_client(tmp_path)
    QuoteCache(str(tmp_path / "cache.db")).put(
        "MU",
        {"trailing_pe": 12.1, "profit_margins": 0.28, "revenue_growth": 0.38},
        fetched_on="2026-08-06",
    )

    body = client.get("/api/company/MU").json()

    assert body["metrics"]["trailing_pe"] == 12.1
    assert body["metrics"]["revenue_growth"] == 0.38
    assert body["metrics_fetched_on"] == "2026-08-06"
