"""Ticker union: watchlist + main portfolio + both arena lanes."""
from __future__ import annotations

from equity_scout.lane_storage import save_lane_portfolio
from equity_scout.lanes import LANE_AUTOPILOT, LANE_NICO
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position
from equity_scout.portfolio_storage import init_portfolio_db, save_portfolio
from equity_scout.radar import Watchlist, WatchlistEntry
from equity_scout.radar_storage import save_watchlist
from equity_scout.signals import SignalReading
from equity_scout.tracked_tickers import tracked_tickers

NOW = "2026-07-15T12:00:00+00:00"


def _watchlist_entry(ticker: str) -> WatchlistEntry:
    return WatchlistEntry(
        ticker=ticker, name=f"{ticker} Corp", bucket="core", price=100.0,
        entry_zone_low=95.0, entry_zone_high=105.0, proximity=-0.05, in_zone=True,
        composite=0.6, readings=[SignalReading("dip_quality", 0.5, "Grund.")],
        zone_note="Kurs in der Entry-Zone (95.00–105.00).",
        breakdown={"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
    )


def _position(ticker: str) -> Position:
    return Position(
        instrument=Instrument(ticker, ticker, "NASDAQ", "US", "USD", "Tech"),
        shares=1.0, cost_basis=100.0, opened_at=NOW,
    )


def test_empty_db_returns_empty_set(tmp_path):
    db = str(tmp_path / "empty.db")
    assert tracked_tickers(db) == set()


def test_union_of_watchlist_main_portfolio_and_both_lanes(tmp_path):
    db = str(tmp_path / "tracked.db")
    save_watchlist(db, Watchlist(created_at=NOW, entries=[_watchlist_entry("WATCH")]))
    init_portfolio_db(db)
    save_portfolio(db, Portfolio(initial_capital=10_000.0, cash=0.0,
                                  positions={"MAIN": _position("MAIN")}))
    save_lane_portfolio(
        db, LANE_NICO,
        Portfolio(initial_capital=10_000.0, cash=0.0, positions={"NICO": _position("NICO")}),
        updated_at=NOW,
    )
    save_lane_portfolio(
        db, LANE_AUTOPILOT,
        Portfolio(initial_capital=10_000.0, cash=0.0, positions={"AUTO": _position("AUTO")}),
        updated_at=NOW,
    )

    assert tracked_tickers(db) == {"WATCH", "MAIN", "NICO", "AUTO"}


def test_overlapping_tickers_are_not_duplicated(tmp_path):
    db = str(tmp_path / "tracked.db")
    save_watchlist(db, Watchlist(created_at=NOW, entries=[_watchlist_entry("DUP")]))
    init_portfolio_db(db)
    save_portfolio(db, Portfolio(initial_capital=10_000.0, cash=0.0,
                                  positions={"DUP": _position("DUP")}))

    assert tracked_tickers(db) == {"DUP"}
