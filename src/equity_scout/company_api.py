"""Company-profile endpoint (``GET /api/company/{ticker}``) as a standalone APIRouter.

Deliberately NOT inline in api.py: that module is under heavy parallel edit, so new
profile-page data lives here and api.py only needs a two-line ``include_router``. Serves
what the phone profile page needs but no JSON endpoint exposes yet: the Piotroski F-Score
(computed nightly, previously pitch/chat-only) and the next earnings date. The model-or-
heuristic target/stop stays with ``/api/entry/{ticker}`` — one owner per number.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.earnings_storage import next_earnings
from equity_scout.fscore import load_f_score


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_company_router(
    db_path: str = DEFAULT_DB_PATH, *, today_fn: Callable[[], str] = _utc_today
) -> APIRouter:
    """Router factory mirroring create_app's db_path injection; ``today_fn`` is injectable
    so tests control the earnings cutoff."""
    router = APIRouter()

    @router.get("/api/company/{ticker}")
    def company(ticker: str) -> dict:
        t = ticker.strip().upper()
        return {
            "ticker": t,
            "f_score": load_f_score(db_path, t),
            "next_earnings": next_earnings(db_path, ticker=t, today=today_fn()),
        }

    return router
