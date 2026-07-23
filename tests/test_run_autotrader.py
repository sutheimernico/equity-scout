"""Runner: end-to-end advance on a synthetic panel, allocation reuse, dry-run, idempotency."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_storage import (
    load_depot,
    load_latest_sleeve_weights,
    load_trades,
    load_valuations,
    save_sleeve_weights,
)
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight
import scripts.run_autotrader as runner
from scripts.run_autotrader import (
    advance_autotrader,
    depot_return_series,
    resolve_allocation,
)


class _Fixed:
    def __init__(self, name: str, targets: list[TargetWeight]) -> None:
        self.name = name
        self._targets = targets

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        return self._targets


def _panel(days: int = 6) -> PricePanel:
    index = pd.bdate_range("2026-07-06", periods=days)
    return PricePanel(
        pd.DataFrame(
            {"SPY": [100.0 + i for i in range(days)], "IEF": [50.0] * days}, index=index
        )
    )


@pytest.fixture
def dbs(tmp_path):
    return str(tmp_path / "autotrader.db"), str(tmp_path / "forward.db")


def test_advance_persists_account_valuation_trades_and_weights(dbs) -> None:
    autotrader_db, forward_db = dbs
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)]), _Fixed("b", [TargetWeight("IEF", 0.5)])]
    advance_autotrader(  # v13 O2: first advance only decides — the second fills
        _panel(5), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
    )
    account, valuation = advance_autotrader(
        _panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
    )
    assert valuation is not None
    assert load_depot(autotrader_db) == account
    assert len(load_valuations(autotrader_db)) == 2
    assert {t["ticker"] for t in load_trades(autotrader_db)} == {"SPY", "IEF"}
    assert {t["fill"] for t in load_trades(autotrader_db)} == {"close_fallback"}
    stored = load_latest_sleeve_weights(autotrader_db)
    # empty forward history -> honest anchor mode, equal sleeve weights
    assert {r["strategy_name"]: r["weight"] for r in stored} == {"a": 0.5, "b": 0.5}
    assert stored[0]["mode"] == "anchor"
    assert account.sleeve_mode == "anchor"


def test_second_advance_on_same_panel_is_idempotent(dbs) -> None:
    autotrader_db, forward_db = dbs
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]
    advance_autotrader(_panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db)
    _, second = advance_autotrader(
        _panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
    )
    assert second is None
    assert len(load_valuations(autotrader_db)) == 1


def test_dry_run_persists_nothing(dbs) -> None:
    autotrader_db, forward_db = dbs
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]
    _, valuation = advance_autotrader(
        _panel(), strategies, autotrader_db=autotrader_db, forward_db=forward_db, persist=False,
    )
    assert valuation is not None
    assert load_depot(autotrader_db) is None
    assert load_valuations(autotrader_db) == []


def test_resolve_allocation_reuses_same_month_same_sleeves(dbs) -> None:
    autotrader_db, forward_db = dbs
    as_of = pd.Timestamp("2026-07-13")
    stored = SleeveAllocation(weights={"a": 0.7, "b": 0.3}, mode="tilt", sharpes={"a": 1.0, "b": 0.1})
    save_sleeve_weights(autotrader_db, "2026-07", stored)
    allocation = resolve_allocation(autotrader_db, forward_db, ["a", "b"], as_of)
    assert allocation.weights == {"a": 0.7, "b": 0.3}
    assert allocation.mode == "tilt"


def test_resolve_allocation_recomputes_when_sleeve_set_changes(dbs) -> None:
    autotrader_db, forward_db = dbs
    as_of = pd.Timestamp("2026-07-13")
    save_sleeve_weights(
        autotrader_db, "2026-07", SleeveAllocation(weights={"a": 1.0}, mode="tilt")
    )
    allocation = resolve_allocation(autotrader_db, forward_db, ["a", "new_bot"], as_of)
    # no forward history in the tmp DB -> recompute lands on the honest anchor
    assert allocation.mode == "anchor"
    assert allocation.weights == {"a": 0.5, "new_bot": 0.5}
    assert {r["strategy_name"] for r in load_latest_sleeve_weights(autotrader_db)} == {"a", "new_bot"}


def test_depot_return_series_needs_two_valuations(dbs) -> None:
    autotrader_db, forward_db = dbs
    assert depot_return_series(autotrader_db) is None
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]
    advance_autotrader(_panel(5), strategies, autotrader_db=autotrader_db, forward_db=forward_db)
    advance_autotrader(_panel(6), strategies, autotrader_db=autotrader_db, forward_db=forward_db)
    series = depot_return_series(autotrader_db)
    assert series is not None and len(series) == 1


def test_ml_sleeve_holdings_reads_post_exit_forward_books(tmp_path) -> None:
    """R5/P1: only the ML bots' books are mirrored; zero-weight = not held; a bot without
    a forward account yet stays unfiltered (exit info honestly unavailable)."""
    from equity_scout.forward_paper import ForwardAccount
    from equity_scout.forward_storage import init_forward_db, save_account
    from scripts.run_autotrader import ml_sleeve_holdings

    forward_db = str(tmp_path / "forward.db")
    init_forward_db(forward_db)
    save_account(forward_db, ForwardAccount(
        strategy_name="ML Long Bot", initial_capital=10_000.0, equity=10_000.0,
        benchmark_ticker="SPY", benchmark_equity=10_000.0, last_as_of="2026-07-18",
        weights={"AAPL": 0.3, "MSFT": 0.0},
    ), updated_at="2026-07-18")

    holdings = ml_sleeve_holdings(forward_db, ["ML Long Bot", "ML Short Bot", "GEM"])
    assert holdings == {"ML Long Bot": {"AAPL"}}


def test_event_message_bundles_trades_and_risk_events() -> None:
    from equity_scout.autotrader_engine import AutoDepotValuation, TradeRecord
    from equity_scout.autotrader_protections import RiskEvent
    from scripts.run_autotrader import build_event_message

    valuation = AutoDepotValuation(
        created_at="2026-07-21", equity=100_000.0, total_return=0.0,
        benchmark_equity=100_000.0, benchmark_return=0.0,
        gross_exposure=0.8, drawdown=0.0,
        trades=(TradeRecord("2026-07-21", "SPY", 0.05, 5_000.0, 5.0),),
        risk_events=(RiskEvent("concentration_cap", "clip", "SPY auf 10% gekappt"),),
    )
    text = build_event_message(valuation)
    assert text is not None
    assert "KAUF SPY" in text and "SPY auf 10% gekappt" in text

    quiet = AutoDepotValuation(
        created_at="2026-07-21", equity=100_000.0, total_return=0.0,
        benchmark_equity=100_000.0, benchmark_return=0.0,
        gross_exposure=0.8, drawdown=0.0,
    )
    assert build_event_message(quiet) is None


def test_push_events_is_silent_and_env_gated(monkeypatch) -> None:
    from equity_scout.autotrader_engine import AutoDepotValuation, TradeRecord
    import scripts.run_autotrader as runner_mod

    valuation = AutoDepotValuation(
        created_at="2026-07-21", equity=100_000.0, total_return=0.0,
        benchmark_equity=100_000.0, benchmark_return=0.0,
        gross_exposure=0.8, drawdown=0.0,
        trades=(TradeRecord("2026-07-21", "SPY", 0.05, 5_000.0, 5.0),),
    )
    calls: list[dict] = []

    def fake_send(token, chat_id, text, keyboard=None, parse_mode=None, silent=False):
        calls.append({"silent": silent, "text": text})
        return 1

    monkeypatch.setattr(runner_mod, "send_message", fake_send)
    env = {"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "1"}

    assert runner_mod.push_events(valuation, env) is True
    assert calls[0]["silent"] is True  # 02:35 push must never wake anyone

    assert runner_mod.push_events(valuation, {**env, "COPILOT_TG_AUTOTRADER_EVENTS": "0"}) is False
    assert len(calls) == 1
    assert runner_mod.push_events(None, env) is False  # quiet advance -> no message


def _seed_lane(shortterm_db: str, *, winning: bool) -> None:
    from equity_scout.shortterm_book import LaneBook, LaneValuation, TradeFill
    from equity_scout.shortterm_storage import append_trades, append_valuation, save_book

    save_book(shortterm_db, LaneBook.fresh("crypto", benchmark_ticker="BTC"), updated_at="t")
    pnl_win, pnl_loss = (20.0, -10.0) if winning else (5.0, -40.0)
    fills = [
        TradeFill(lane="crypto", executed_at=f"2026-07-0{1 + i % 9}T{10 + i % 10}:0{i % 6}",
                  ticker=f"C{i}", side="sell", qty=1.0, price=100.0, fees=0.1,
                  reason="test", realized_pnl=pnl_win if i % 2 == 0 else pnl_loss)
        for i in range(34)
    ]
    append_trades(shortterm_db, fills)
    append_valuation(shortterm_db, LaneValuation(
        lane="crypto", created_at="2026-05-01T18:00", equity=10_000.0, total_return=0.0,
        cash=10_000.0, open_positions=0, benchmark_return=None,
    ))
    for i, day in enumerate(["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
                             "2026-07-10", "2026-07-13"]):
        append_valuation(shortterm_db, LaneValuation(
            lane="crypto", created_at=f"{day}T18:00", equity=10_000.0 + 50.0 * i,
            total_return=0.005 * i, cash=8_000.0, open_positions=1, benchmark_return=None,
        ))


def test_eligible_lane_is_promoted_into_the_depot(dbs, tmp_path) -> None:
    """I3: evidence in, capital out — the depot buys the lane's equity curve as a fund
    share; a promotion risk-event row is persisted."""
    from equity_scout.autotrader_storage import load_risk_events

    autotrader_db, forward_db = dbs
    shortterm_db = str(tmp_path / "shortterm.db")
    _seed_lane(shortterm_db, winning=True)
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]

    advance_autotrader(  # v13 O2: decide first, fill on the next advance
        _panel(5), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
        shortterm_db=shortterm_db,
    )
    account, valuation = advance_autotrader(
        _panel(6), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
        shortterm_db=shortterm_db,
    )
    assert account.promoted_lanes == ("crypto",)
    assert "Arena crypto" in account.sleeve_weights
    assert any(t["ticker"] == "ARENA_CRYPTO" for t in load_trades(autotrader_db))
    events = load_risk_events(autotrader_db)
    assert any(e["action"] == "promote" for e in events)


def test_losing_lane_stays_a_measurement_instrument(dbs, tmp_path) -> None:
    autotrader_db, forward_db = dbs
    shortterm_db = str(tmp_path / "shortterm.db")
    _seed_lane(shortterm_db, winning=False)
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]

    account, _ = advance_autotrader(
        _panel(6), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
        shortterm_db=shortterm_db,
    )
    assert account.promoted_lanes == ()
    assert "Arena crypto" not in account.sleeve_weights


def test_promoted_lane_is_demoted_when_trailing_pnl_turns_negative(dbs, tmp_path) -> None:
    from dataclasses import replace

    from equity_scout.autotrader_engine import AutoDepotAccount
    from equity_scout.autotrader_storage import load_risk_events, save_depot

    autotrader_db, forward_db = dbs
    shortterm_db = str(tmp_path / "shortterm.db")
    _seed_lane(shortterm_db, winning=False)  # trailing 60d net negative
    save_depot(autotrader_db, replace(AutoDepotAccount.fresh(), promoted_lanes=("crypto",)),
               updated_at="2026-07-01")
    strategies = [_Fixed("a", [TargetWeight("SPY", 0.5)])]

    account, _ = advance_autotrader(
        _panel(6), strategies, autotrader_db=autotrader_db, forward_db=forward_db,
        shortterm_db=shortterm_db,
    )
    assert account.promoted_lanes == ()
    assert any(e["action"] == "demote" for e in load_risk_events(autotrader_db))


def test_combined_panel_stock_subpanel_survives_a_young_ticker(monkeypatch) -> None:
    """R3: the stock subpanel must be gap-tolerant (clean_columns, no common-range trim) —
    a fresh IPO on the watchlist must not truncate an established ticker's history, the way
    load_etf_panel's clean_panel trim (dropna(how="any") over ALL bot tickers) used to."""
    from equity_scout.data.etf_panel import clean_columns, clean_panel

    old_index = pd.bdate_range("2024-01-02", periods=500)  # ~2 years
    young_index = old_index[-10:]  # joined 10 trading days ago
    raw_stocks = pd.DataFrame(index=old_index)
    raw_stocks["OLD"] = 100.0
    raw_stocks["YOUNG"] = float("nan")
    raw_stocks.loc[young_index, "YOUNG"] = 50.0

    etf_panel = PricePanel(pd.DataFrame({"SPY": 1.0}, index=old_index))

    def fake_load_etf_panel(tickers, **kwargs):  # noqa: ANN001, ANN201
        # Only the ETF universe call may still land here; if the stock subpanel is (still,
        # wrongly) routed through here too, it gets the old destructive common-range trim.
        if "OLD" in tickers:
            return clean_panel(raw_stocks)
        return etf_panel

    monkeypatch.setattr(runner, "load_etf_panel", fake_load_etf_panel)
    monkeypatch.setattr(runner, "load_price_history", lambda tickers, **kwargs: clean_columns(raw_stocks))
    monkeypatch.setattr(
        runner, "load_latest_watchlist",
        lambda main_db: {"entries": [{"ticker": "OLD"}, {"ticker": "YOUNG"}]},
    )

    panel = runner.combined_panel(
        start="2007-01-01", refresh=False, need_stocks=True, main_db="unused.db"
    )

    assert panel.closes["OLD"].notna().sum() == len(old_index)  # full history kept, not trimmed
    assert "YOUNG" in panel.tickers
    young = panel.closes["YOUNG"]
    assert young.notna().sum() == len(young_index)  # young ticker's own short history present
    assert young.isna().sum() == len(old_index) - len(young_index)  # gap tolerated, not dropped
