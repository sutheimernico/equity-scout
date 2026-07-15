"""One shared helper for "every ticker we currently care about".

Watchlist candidates and portfolio holdings each accumulate their own ticker sets, and
several scripts (run_forward_paper.py, run_digest.py, run_lanes.py) already build their
own inline union of a subset of these for their own purposes. This module adds ONE small,
reusable union of ALL of them (watchlist + main paper portfolio + both arena lanes) for
callers that need the full set — first user is the earnings-calendar refresh (Strang B1).
The existing inline unions are intentionally left alone; this does not replace them.
"""
from __future__ import annotations

from equity_scout.lane_storage import load_lane_portfolio
from equity_scout.lanes import LANE_AUTOPILOT, LANE_NICO
from equity_scout.portfolio_storage import load_portfolio
from equity_scout.radar_storage import load_latest_watchlist


def tracked_tickers(db_path: str) -> set[str]:
    """Union of the latest watchlist's tickers, the main portfolio's holdings, and both
    arena lanes' holdings. Empty pieces (no watchlist yet, no positions) contribute
    nothing — never an error."""
    watchlist = load_latest_watchlist(db_path) or {}
    tickers = {entry["ticker"] for entry in watchlist.get("entries", [])}

    portfolio = load_portfolio(db_path)
    if portfolio is not None:
        tickers |= set(portfolio.positions)

    for lane in (LANE_NICO, LANE_AUTOPILOT):
        lane_portfolio = load_lane_portfolio(db_path, lane)
        if lane_portfolio is not None:
            tickers |= set(lane_portfolio.positions)

    return tickers
