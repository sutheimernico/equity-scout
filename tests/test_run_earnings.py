"""Earnings-refresh CLI: tracked tickers -> fetched (faked) earnings dates -> persisted."""
from __future__ import annotations

import sys

import scripts.run_earnings as run_earnings_mod
from equity_scout.earnings_storage import earnings_within
from equity_scout.lane_storage import save_lane_portfolio
from equity_scout.lanes import LANE_NICO
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position
from scripts.run_earnings import main, run_earnings

NOW = "2026-07-15T06:00:00+00:00"


def _seed_lane_ticker(db: str, ticker: str) -> None:
    save_lane_portfolio(
        db, LANE_NICO,
        Portfolio(
            initial_capital=10_000.0, cash=0.0,
            positions={
                ticker: Position(
                    instrument=Instrument(ticker, ticker, "NASDAQ", "US", "USD", "Tech"),
                    shares=1.0, cost_basis=100.0, opened_at=NOW,
                )
            },
        ),
        updated_at=NOW,
    )


def test_run_earnings_fetches_and_persists_each_tracked_ticker(tmp_path):
    db = str(tmp_path / "run.db")
    _seed_lane_ticker(db, "AAPL")

    def fake_fetch(ticker: str) -> list[str]:
        return ["2026-07-22"] if ticker == "AAPL" else []

    known = run_earnings(db, {"AAPL"}, fetched_on=NOW, fetch=fake_fetch)

    assert known == 1
    assert earnings_within(db, today="2026-07-15", days=30) == [
        {"ticker": "AAPL", "earnings_date": "2026-07-22"}
    ]


def test_run_earnings_counts_only_tickers_with_a_known_date(tmp_path):
    db = str(tmp_path / "run.db")

    def fake_fetch(ticker: str) -> list[str]:
        return ["2026-07-22"] if ticker == "AAPL" else []

    known = run_earnings(db, {"AAPL", "NODATA"}, fetched_on=NOW, fetch=fake_fetch)

    assert known == 1


def test_main_reports_nothing_to_do_without_tracked_tickers(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "fresh.db")
    monkeypatch.setattr(sys, "argv", ["run_earnings.py", "--db", db])

    assert main() == 0
    assert "nichts zu aktualisieren" in capsys.readouterr().out


def test_main_happy_path_reports_count(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "run.db")
    _seed_lane_ticker(db, "AAPL")
    monkeypatch.setattr(
        run_earnings_mod, "fetch_earnings_dates", lambda t: ["2026-07-22"] if t == "AAPL" else []
    )
    monkeypatch.setattr(sys, "argv", ["run_earnings.py", "--db", db])

    assert main() == 0

    out = capsys.readouterr().out
    assert "1/1" in out
    assert earnings_within(db, today="2026-07-15", days=30) == [
        {"ticker": "AAPL", "earnings_date": "2026-07-22"}
    ]
