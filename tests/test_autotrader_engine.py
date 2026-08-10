"""Engine: idempotency, look-ahead safety, netting, costs/trades, protections, margin floor."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_engine import (
    AutoDepotAccount,
    advance_depot,
    aggregate_targets,
)
from equity_scout.autotrader_protections import ConcentrationCap, DrawdownBreaker
from equity_scout.market import PricePanel
from equity_scout.strategies.base import TargetWeight


class _Fixed:
    """Canned strategy: always returns the same targets."""

    def __init__(self, name: str, targets: list[TargetWeight]) -> None:
        self.name = name
        self._targets = targets

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        return self._targets


class _Crashing:
    """Canned strategy whose decide() always raises — simulates a future feature-layout
    mismatch or data edge case blowing up ONE sleeve."""

    def __init__(self, name: str) -> None:
        self.name = name

    def decide(self, as_of, market):  # noqa: ANN001, ANN201 - Strategy protocol
        raise RuntimeError("boom")


class _Recorder(_Fixed):
    """Records what the MarketView let it see."""

    def __init__(self) -> None:
        super().__init__("recorder", [TargetWeight("SPY", 1.0)])
        self.seen_latest = None

    def decide(self, as_of, market):  # noqa: ANN001, ANN201
        self.seen_latest = market.latest_date
        return super().decide(as_of, market)


def _panel(days: int, prices: dict[str, list[float]] | None = None) -> PricePanel:
    index = pd.bdate_range("2026-06-01", periods=days)
    data = prices or {}
    if "SPY" not in data:
        data["SPY"] = [100.0 + i for i in range(days)]
    frame = pd.DataFrame({t: p[:days] for t, p in data.items()}, index=index)
    return PricePanel(frame)


def _allocation(weights: dict[str, float], mode: str = "anchor") -> SleeveAllocation:
    return SleeveAllocation(weights=weights, mode=mode)


def test_advance_without_new_date_is_idempotent() -> None:
    panel = _panel(5)
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account = AutoDepotAccount.fresh()
    account, first = advance_depot(account, [strategy], _allocation({"s": 1.0}), panel)
    assert first is not None
    account2, second = advance_depot(account, [strategy], _allocation({"s": 1.0}), panel)
    assert second is None
    assert account2 == account


def test_decide_never_sees_todays_own_close() -> None:
    panel = _panel(5)
    recorder = _Recorder()
    advance_depot(AutoDepotAccount.fresh(), [recorder], _allocation({"recorder": 1.0}), panel)
    assert recorder.seen_latest == panel.dates[-2]


def test_long_and_short_on_the_same_ticker_net_out() -> None:
    long_sleeve = _Fixed("long", [TargetWeight("AAPL", 1.0)])
    short_sleeve = _Fixed("short", [TargetWeight("AAPL", 1.0, side="short")])
    allocation = _allocation({"long": 0.5, "short": 0.5})
    decisions = {s.name: s.decide(None, None) for s in (long_sleeve, short_sleeve)}
    assert aggregate_targets(allocation, decisions) == {}


def test_look_through_scales_by_sleeve_weight() -> None:
    a = _Fixed("a", [TargetWeight("SPY", 1.0)])
    b = _Fixed("b", [TargetWeight("SPY", 0.5), TargetWeight("IEF", 0.5)])
    allocation = _allocation({"a": 0.6, "b": 0.4})
    decisions = {s.name: s.decide(None, None) for s in (a, b)}
    targets = aggregate_targets(allocation, decisions)
    assert targets["SPY"] == pytest.approx(0.6 + 0.4 * 0.5)
    assert targets["IEF"] == pytest.approx(0.4 * 0.5)


def test_advance_decides_pending_orders_and_the_next_advance_fills_them() -> None:
    """v13 O2: an advance no longer fills at the close it decided on — it persists pending
    orders; the NEXT advance books the trades and the turnover cost."""
    panel = _panel(5, {"SPY": [100, 101, 102, 103, 104], "IEF": [50, 50, 50, 50, 50]})
    strategy = _Fixed("s", [TargetWeight("SPY", 0.6), TargetWeight("IEF", 0.4)])
    account, first = advance_depot(
        AutoDepotAccount.fresh(initial_capital=100_000.0),
        [strategy], _allocation({"s": 1.0}), PricePanel(panel.closes.iloc[:4]),
        protections=[],
    )
    assert first is not None
    assert first.trades == ()  # decided, not filled
    assert first.equity == pytest.approx(100_000.0)  # no cost before the fill
    assert account.weights == {}
    assert account.pending_orders is not None
    assert account.pending_orders.targets == {
        "SPY": pytest.approx(0.6), "IEF": pytest.approx(0.4),
    }

    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), panel, protections=[],
    )
    assert valuation is not None
    # turnover 1.0 at 10 bps on 100k = 100 USD, charged at fill time
    assert valuation.equity == pytest.approx(100_000.0 - 100.0)
    tickers = {t.ticker: t for t in valuation.trades}
    assert tickers["SPY"].delta_weight == pytest.approx(0.6)
    assert tickers["SPY"].notional == pytest.approx(60_000.0)
    assert tickers["SPY"].cost + tickers["IEF"].cost == pytest.approx(100.0)
    assert tickers["SPY"].fill == "close_fallback"  # no OHLC world supplied
    assert tickers["SPY"].fill_price == pytest.approx(104.0)
    assert tickers["SPY"].decided_as_of == panel.dates[3].date().isoformat()
    assert valuation.gross_exposure == pytest.approx(1.0)
    assert account.weights == {"SPY": pytest.approx(0.6), "IEF": pytest.approx(0.4)}


def test_pending_orders_fill_at_the_open_with_intraday_attribution() -> None:
    """v13 O2: with an OHLC world, the fill prices at the day's open and the filled delta
    earns the open-to-close leg — decided at 103, filled at open 102, close 104."""
    panel = _panel(5, {"SPY": [100, 101, 102, 103, 104]})
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(initial_capital=100_000.0),
        [strategy], _allocation({"s": 1.0}), PricePanel(panel.closes.iloc[:4]),
        protections=[],
    )
    fill_day = panel.dates[-1]
    ohlc = {"SPY": pd.DataFrame(
        {"open": [102.0], "high": [105.0], "low": [101.0], "close": [104.0]},
        index=[fill_day],
    )}
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), panel, protections=[], ohlc=ohlc,
    )
    assert valuation is not None
    trade = valuation.trades[0]
    assert trade.fill == "open"
    assert trade.fill_price == pytest.approx(102.0)
    # cost first (10 bps on 100k), attribution on the open->close move of the +1.0 delta
    assert valuation.equity == pytest.approx(100_000.0 * (1.0 + (104.0 / 102.0 - 1.0)) - 100.0)
    # marks stay close-based: the new position's mark starts at today's close
    assert account.last_marks["SPY"] == (fill_day.date().isoformat(), 104.0)


def test_fill_cost_uses_the_corwin_schultz_floor_for_wide_ranges() -> None:
    """v13 O3: a thin name's fill pays half its estimated spread instead of the flat
    10 bps — constant H/L 102/100 estimates a 2*(0.02)/2.02 spread, ~99 bps half."""
    panel = _panel(5, {"SPY": [100.0] * 5})
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(initial_capital=100_000.0),
        [strategy], _allocation({"s": 1.0}), PricePanel(panel.closes.iloc[:4]),
        protections=[],
    )
    idx = pd.bdate_range(end=panel.dates[-1], periods=22)
    ohlc = {"SPY": pd.DataFrame(
        {"open": 100.0, "high": 102.0, "low": 100.0, "close": 100.0}, index=idx,
    )}
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), panel, protections=[], ohlc=ohlc,
    )
    half_spread = 2.0 * 0.02 / 2.02 / 2.0
    assert valuation.trades[0].cost == pytest.approx(100_000.0 * half_spread)
    assert valuation.trades[0].fill == "open"


def test_fill_cost_ignores_a_running_sessions_ohlc_row() -> None:
    """A live OHLC fetch can carry a row for a session still trading elsewhere (Tokyo at
    02:35 Berlin); its intraday range must not enter the spread median for today's fill."""
    panel = _panel(5, {"SPY": [100.0] * 5})
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(initial_capital=100_000.0),
        [strategy], _allocation({"s": 1.0}), PricePanel(panel.closes.iloc[:4]),
        protections=[],
    )
    idx = pd.bdate_range(end=panel.dates[-1], periods=22).append(
        pd.bdate_range(start=panel.dates[-1] + pd.Timedelta(days=1), periods=1)
    )
    frame = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
                         index=idx)
    frame.iloc[-1] = [100.0, 200.0, 100.0, 100.0]  # the running session's wild range
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), panel, protections=[],
        ohlc={"SPY": frame},
    )
    # zero-range history -> no CS estimate -> the flat 10 bps floor, future row ignored
    assert valuation.trades[0].cost == pytest.approx(100.0)
    assert valuation.trades[0].fill == "open"


def test_refilling_the_same_book_trades_nothing() -> None:
    """Pending targets equal to the drifted book must not book trades or costs."""
    panel = _panel(5, {"SPY": [100.0] * 5})
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account = AutoDepotAccount.fresh()
    for n in (3, 4):
        account, _ = advance_depot(
            account, [strategy], _allocation({"s": 1.0}), PricePanel(panel.closes.iloc[:n]),
            protections=[],
        )
    equity_after_fill = account.equity
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), panel, protections=[],
    )
    assert valuation is not None
    assert valuation.trades == ()
    assert valuation.equity == pytest.approx(equity_after_fill)


def test_protection_chain_shapes_the_final_book() -> None:
    panel = _panel(5)
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account, valuation = advance_depot(
        AutoDepotAccount.fresh(), [strategy], _allocation({"s": 1.0}),
        PricePanel(panel.closes.iloc[:4]), protections=[ConcentrationCap(cap=0.10)],
    )
    assert valuation is not None
    # the protection shapes the DECISION (v13 O2: filled at the next advance's open)
    assert account.pending_orders.targets == {"SPY": pytest.approx(0.10)}
    assert [e.protection for e in valuation.risk_events] == ["concentration_cap"]
    account, _ = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), panel,
        protections=[ConcentrationCap(cap=0.10)],
    )
    assert account.weights == {"SPY": pytest.approx(0.10)}


def test_drawdown_breaker_state_persists_into_the_account() -> None:
    falling = _panel(6, {"SPY": [100, 100, 100, 100, 100, 80]})
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    account = AutoDepotAccount.fresh()
    for n in (4, 5):  # decide, then fill at flat prices — position established pre-drop
        account, _ = advance_depot(
            account, [strategy], _allocation({"s": 1.0}),
            PricePanel(falling.closes.iloc[:n]), protections=[],
        )
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), falling,
        protections=[DrawdownBreaker(soft=0.10, hard=0.30)],
    )
    assert valuation is not None
    assert valuation.drawdown == pytest.approx(0.2, abs=0.01)
    assert account.breaker.stage == 1
    # the halved target is the DECISION — it fills at the next advance (v13 O2)
    assert account.pending_orders.targets["SPY"] == pytest.approx(0.5)


def test_short_book_wipe_floors_at_zero_and_stops_trading() -> None:
    prices = {"SPY": [100] * 6, "TSLA": [100, 100, 100, 100, 100, 250]}
    strategy = _Fixed("s", [TargetWeight("TSLA", 1.0, side="short")])
    account = AutoDepotAccount.fresh()
    for n in (4, 5):  # decide, then fill the short at flat prices
        account, _ = advance_depot(
            account, [strategy], _allocation({"s": 1.0}),
            _panel(n, {t: p[:n] for t, p in prices.items()}), protections=[],
        )
    account, valuation = advance_depot(
        account, [strategy], _allocation({"s": 1.0}), _panel(6, prices), protections=[],
    )
    assert valuation is not None
    assert account.equity == 0.0
    assert account.weights == {}
    assert valuation.total_return == -1.0
    _, after = advance_depot(account, [strategy], _allocation({"s": 1.0}), _panel(6, prices))
    assert after is None  # dead depot never trades again


def test_fx_rate_produces_eur_equity_and_absence_stays_none() -> None:
    panel = _panel(5)
    strategy = _Fixed("s", [TargetWeight("SPY", 1.0)])
    _, with_fx = advance_depot(
        AutoDepotAccount.fresh(), [strategy], _allocation({"s": 1.0}), panel, fx_rate=0.9,
    )
    assert with_fx is not None
    assert with_fx.equity_eur == pytest.approx(with_fx.equity * 0.9)
    _, without_fx = advance_depot(
        AutoDepotAccount.fresh(), [strategy], _allocation({"s": 1.0}), panel,
    )
    assert without_fx is not None
    assert without_fx.equity_eur is None and without_fx.fx_rate is None


def test_sleeve_holdings_mirror_drops_exited_tickers_without_redistributing() -> None:
    """R5/P1 (review 2026-07-20): the depot mirrors an ML sleeve's POST-exit forward book —
    a ticker the sleeve book no longer holds contributes 0; freed weight sits in cash."""
    panel = _panel(5, {"SPY": [100.0] * 5, "AAPL": [50.0] * 5, "MSFT": [60.0] * 5})
    sleeve = _Fixed("ml", [TargetWeight("AAPL", 0.5), TargetWeight("MSFT", 0.5)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(), [sleeve], _allocation({"ml": 1.0}), panel,
        protections=[], sleeve_holdings={"ml": {"AAPL"}},
    )
    targets = account.pending_orders.targets  # the decision — fills next advance (v13 O2)
    assert "MSFT" not in targets
    assert targets["AAPL"] == pytest.approx(0.5)  # not scaled up to fill the gap


def test_stale_series_books_zero_and_next_fresh_row_books_the_full_move() -> None:
    """Reviewer repro (v13 R2, the actual P0 fix): a lane's fresh price lands one panel date
    late (feed/chain timing). The window-based valuation used to resolve BOTH ends to the same
    stale row and silently lose the move forever — every following night booked 0.00. With
    per-position marks, the advance that still sees no price fresher than its mark books 0 and
    KEEPS the mark; the very next advance that finally sees the fresh row books the FULL move —
    nothing lost, just booked one day late."""
    nan = float("nan")
    prices = {
        "SPY": [100.0] * 7,
        "CRYPTO": [100.0, 100.0, 100.0, 100.0, 100.0, nan, 150.0],  # gap on day 6, +50% on day 7
    }
    full = _panel(7, prices)
    strategy = _Fixed("s", [TargetWeight("CRYPTO", 1.0)])
    allocation = _allocation({"s": 1.0})
    account = AutoDepotAccount.fresh()

    for n in range(1, 6):  # days 1-5: establish the position and its mark
        account, _ = advance_depot(
            account, [strategy], allocation, PricePanel(full.closes.iloc[:n]), protections=[],
        )
    equity_before_gap = account.equity
    mark_before_gap = account.last_marks["CRYPTO"]

    # day 6: CRYPTO's own feed has not updated (NaN) — no reading fresher than the mark exists.
    account, val6 = advance_depot(
        account, [strategy], allocation, PricePanel(full.closes.iloc[:6]), protections=[],
    )
    assert val6 is not None
    assert val6.equity == pytest.approx(equity_before_gap)  # booked zero this step
    assert account.last_marks["CRYPTO"] == mark_before_gap  # mark held untouched, not re-anchored

    # day 7: the fresh +50% row finally lands — the FULL move must book now.
    account, val7 = advance_depot(account, [strategy], allocation, full, protections=[])
    assert val7 is not None
    assert val7.equity == pytest.approx(equity_before_gap * 1.5)
    assert account.last_marks["CRYPTO"] == (full.dates[-1].date().isoformat(), 150.0)


def test_fresh_price_every_step_drifts_exactly_like_the_old_window_logic() -> None:
    """No staleness anywhere: the marks-based drift must reproduce the exact same arithmetic
    as the old [last, today] window resolution, day after day. Since v13 O2 the position
    exists from the SECOND advance (decide -> fill), so drift starts at the fill close."""
    panel = _panel(4, {"SPY": [100.0] * 4, "AAPL": [50.0, 52.0, 49.0, 55.0]})
    strategy = _Fixed("s", [TargetWeight("AAPL", 1.0)])
    allocation = _allocation({"s": 1.0})
    account = AutoDepotAccount.fresh(initial_capital=10_000.0)

    account, _ = advance_depot(account, [strategy], allocation, PricePanel(panel.closes.iloc[:1]),
                                protections=[])  # decision only (v13 O2)
    account, val2 = advance_depot(account, [strategy], allocation, PricePanel(panel.closes.iloc[:2]),
                                   protections=[])
    after_fill = val2.equity  # one-way turnover cost, position marked at the 52.0 close

    account, val3 = advance_depot(account, [strategy], allocation, PricePanel(panel.closes.iloc[:3]),
                                   protections=[])
    assert val3.equity == pytest.approx(after_fill * (49.0 / 52.0))

    account, val4 = advance_depot(account, [strategy], allocation, panel, protections=[])
    assert val4.equity == pytest.approx(after_fill * (55.0 / 52.0))
    assert account.last_marks["AAPL"] == (panel.dates[-1].date().isoformat(), 55.0)


def test_legacy_blob_without_marks_initialises_on_first_advance_then_uses_them() -> None:
    """Migration (v13 R2): an account that already holds a position but predates `last_marks`
    (loaded as {}) values its first advance exactly like the old window logic and initialises
    the mark; the SECOND advance then uses that mark, mark-return arithmetic."""
    from dataclasses import replace

    panel = _panel(3, {"SPY": [100.0] * 3, "AAPL": [50.0, 60.0, 66.0]})
    strategy = _Fixed("s", [TargetWeight("AAPL", 1.0)])
    allocation = _allocation({"s": 1.0})

    legacy = replace(
        AutoDepotAccount.fresh(initial_capital=10_000.0),
        equity=10_000.0, weights={"AAPL": 1.0},
        last_as_of=panel.dates[0].date().isoformat(), last_marks={},
    )

    account, val2 = advance_depot(legacy, [strategy], allocation,
                                   PricePanel(panel.closes.iloc[:2]), protections=[])
    assert val2.equity == pytest.approx(10_000.0 * (60.0 / 50.0))  # same as the old window return
    assert account.last_marks["AAPL"] == (panel.dates[1].date().isoformat(), 60.0)

    account, val3 = advance_depot(account, [strategy], allocation, panel, protections=[])
    assert val3.equity == pytest.approx(val2.equity * (66.0 / 60.0))  # now driven by the mark
    assert account.last_marks["AAPL"] == (panel.dates[2].date().isoformat(), 66.0)


def test_sleeve_holdings_only_filters_listed_sleeves() -> None:
    panel = _panel(5, {"SPY": [100.0] * 5, "AAPL": [50.0] * 5})
    rule = _Fixed("rule", [TargetWeight("AAPL", 0.8)])
    account, _ = advance_depot(
        AutoDepotAccount.fresh(), [rule], _allocation({"rule": 1.0}), panel,
        protections=[], sleeve_holdings={"ml": set()},
    )
    assert account.pending_orders.targets["AAPL"] == pytest.approx(0.8)


def test_advance_isolates_a_crashing_sleeve_and_still_decides_the_others(capsys) -> None:
    """Quality-review finding: one sleeve's decide() raising must not take the other, healthy
    sleeves' decisions down with it. The crashed sleeve is EXCLUDED from `decisions` for the
    day — the exact same fate `aggregate_targets` already gives a sleeve with a legitimate
    empty decide() ("sits in cash", see its docstring) — so the healthy sleeve's full share
    still lands in the day's decision and the advance completes."""
    panel = _panel(5)
    good = _Fixed("good", [TargetWeight("SPY", 1.0)])
    bad = _Crashing("bad")
    account, valuation = advance_depot(
        AutoDepotAccount.fresh(), [bad, good], _allocation({"bad": 0.5, "good": 0.5}),
        PricePanel(panel.closes.iloc[:4]), protections=[],
    )
    assert valuation is not None  # the advance completed despite the crash
    assert account.pending_orders is not None
    assert account.pending_orders.targets == {"SPY": pytest.approx(0.5)}
    err = capsys.readouterr().err
    assert "bad" in err
    assert "fehlgeschlagen" in err


def test_a_crashing_sleeve_does_not_disturb_an_already_filled_book() -> None:
    """The crash only affects the NEW decision for tomorrow's fill (v13 O2): a book already
    established from a PRIOR successful advance drifts and fills exactly as if nothing had
    crashed today — the failure cannot corrupt state that predates it."""
    panel = _panel(6, {"SPY": [100.0] * 6})
    good = _Fixed("good", [TargetWeight("SPY", 1.0)])
    account = AutoDepotAccount.fresh(initial_capital=100_000.0)
    for n in (4, 5):  # decide, then fill — a healthy book is already established
        account, _ = advance_depot(
            account, [good], _allocation({"good": 1.0}), PricePanel(panel.closes.iloc[:n]),
            protections=[],
        )
    assert account.weights == {"SPY": pytest.approx(1.0)}

    # today, the sleeve crashes — but the fill of YESTERDAY's pending order still runs first.
    account, valuation = advance_depot(
        account, [_Crashing("good")], _allocation({"good": 1.0}), panel, protections=[],
    )
    assert valuation is not None
    assert account.weights == {"SPY": pytest.approx(1.0)}  # yesterday's fill, untouched
    # cash for tomorrow: no successful decision today to persist as the next pending order.
    assert account.pending_orders.targets == {}
