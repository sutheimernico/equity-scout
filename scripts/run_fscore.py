"""F-Score CLI: watchlist tickers -> EDGAR company facts -> Piotroski F-Scores.

Usage:
    python scripts/run_fscore.py [--db equity_scout.db]

Watchlist-only by design (a full-universe companyfacts sweep would be gigabytes);
scores land in the `f_scores` table and annotate pitches. Without EDGAR_USER_AGENT
this degrades to a polite "unconfigured" no-op, exactly like the 13F collector —
the SEC requires a contact in the User-Agent and we never fake one.
"""
from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.edgar import resolve_user_agent
from equity_scout.evidence.form4 import fetch_ticker_cik_map
from equity_scout.fscore import collect_f_scores
from equity_scout.radar_storage import load_latest_watchlist


def _http_get_with_agent(user_agent: str) -> Callable[[str], str]:
    def get(url: str) -> str:
        import httpx

        response = httpx.get(
            url, timeout=30.0, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response.text

    return get


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db) or {}
    tickers = [entry["ticker"] for entry in watchlist.get("entries", [])]
    if not tickers:
        print("Keine Watchlist — nichts zu tun (erst scripts/run_radar.py laufen lassen).")
        return 0

    agent = resolve_user_agent(dict(os.environ))
    if agent is None:
        print("EDGAR_USER_AGENT fehlt in .env — F-Scores bleiben unconfigured (kein Fake).")
        return 0

    http_get = _http_get_with_agent(agent)
    today = datetime.now(timezone.utc).date().isoformat()
    summary = collect_f_scores(
        args.db, tickers, today=today, http_get=http_get,
        cik_map=fetch_ticker_cik_map(http_get),
    )
    print(
        f"F-Scores: {summary['computed']} berechnet, {summary['fresh']} frisch übersprungen,"
        f" {summary['no_cik']} ohne CIK (nicht-US),"
        f" {summary['insufficient']} Datenbasis zu dünn (Banken/REITs),"
        f" {summary['failed']} fehlgeschlagen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
