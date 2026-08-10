"""Lane book: fills with costs, realized P&L, valuation vs benchmark, stats."""
from __future__ import annotations

import pytest

from equity_scout.shortterm_book import (
    LaneBook,
    TradeFill,
    buy,
    capture_benchmark,
    loss_anatomy,
    mark_to_market,
    sell,
    stats,
    valuation,
)


def test_buy_charges_slippage_and_reduces_cash() -> None:
    book = LaneBook.fresh("swing")
    book, fill = buy(book, "AAPL", 100.0, "2026-07-20", fraction=0.10, reason="event",
                     slippage_bps=10.0)
    assert fill is not None
    assert book.cash == pytest.approx(9_000.0)
    assert fill.price == pytest.approx(100.10)  # 10 bps worse than the observed price
    assert fill.qty == pytest.approx(1_000.0 / 100.10)
    assert fill.fees == pytest.approx(fill.qty * 0.10)  # slippage cost made explicit


def test_buy_is_refused_when_already_held_or_price_invalid() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "AAPL", 100.0, "t", fraction=0.1, reason="x")
    same_book, refused = buy(book, "AAPL", 100.0, "t", fraction=0.1, reason="x")
    assert refused is None and same_book == book
    _, bad_price = buy(book, "MSFT", 0.0, "t", fraction=0.1, reason="x")
    assert bad_price is None


def test_sell_realizes_pnl_after_costs() -> None:
    book = LaneBook.fresh("session")
    book, entry = buy(book, "SPY", 100.0, "t0", fraction=0.5, reason="orb", slippage_bps=0.0)
    book, exit_fill = sell(book, "SPY", 110.0, "t1", reason="target", slippage_bps=0.0)
    assert exit_fill is not None
    assert exit_fill.realized_pnl == pytest.approx(entry.qty * 10.0)
    assert book.positions == {}
    assert book.cash == pytest.approx(10_000.0 + exit_fill.realized_pnl)


def test_sell_without_position_is_a_no_op() -> None:
    book = LaneBook.fresh("crypto")
    same_book, fill = sell(book, "BTC", 50_000.0, "t", reason="stop")
    assert fill is None and same_book == book


def test_sizing_uses_book_value_not_just_cash() -> None:
    book = LaneBook.fresh("crypto")
    book, _ = buy(book, "BTC", 100.0, "t0", fraction=0.25, reason="don", slippage_bps=0.0)
    # book value still 10k (cash 7.5k + position 2.5k at entry) -> next 25% is again 2.5k
    book, second = buy(book, "ETH", 10.0, "t1", fraction=0.25, reason="don", slippage_bps=0.0)
    assert second is not None
    assert second.qty * second.price == pytest.approx(2_500.0)


def test_mark_to_market_falls_back_to_entry_price_without_a_mark() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "AAPL", 100.0, "t0", fraction=0.10, reason="x", slippage_bps=0.0)
    assert mark_to_market(book, {}) == pytest.approx(10_000.0)
    assert mark_to_market(book, {"AAPL": 120.0}) == pytest.approx(10_200.0)


def test_valuation_tracks_benchmark_from_first_captured_price() -> None:
    book = capture_benchmark(LaneBook.fresh("crypto", benchmark_ticker="BTC"), 50_000.0)
    later = capture_benchmark(book, 60_000.0)  # second capture must not overwrite
    assert later.benchmark_entry_price == 50_000.0
    snap = valuation(later, {}, 55_000.0, "2026-07-20")
    assert snap.benchmark_return == pytest.approx(0.10)
    assert snap.total_return == pytest.approx(0.0)


def test_stats_counts_wins_and_fees_across_fill_shapes() -> None:
    book = LaneBook.fresh("session")
    fills = []
    book, f1 = buy(book, "SPY", 100.0, "t0", fraction=0.3, reason="orb")
    book, f2 = sell(book, "SPY", 105.0, "t1", reason="target")
    book, f3 = buy(book, "QQQ", 50.0, "t2", fraction=0.3, reason="orb")
    book, f4 = sell(book, "QQQ", 48.0, "t3", reason="stop")
    fills = [f1, f2, f3, f4]
    result = stats(fills)
    assert result["n_trades"] == 2 and result["n_fills"] == 4
    assert result["win_rate"] == pytest.approx(0.5)
    assert result["fees_paid"] > 0
    # dict rows (storage shape) work too
    as_dicts = [f.__dict__ for f in fills]
    assert stats(as_dicts)["win_rate"] == pytest.approx(0.5)


def test_buy_books_a_known_quantity_instead_of_re_deriving_it() -> None:
    """A broker fill is a FACT. Re-deriving the size from `fraction` after the fill made the
    book hold 4.59188 TSLA against the broker's 4 (live run 2026-08-06) — Alpaca rounds a
    bracket order DOWN to whole shares, and the book has to book what actually happened."""
    book = LaneBook(lane="session", initial_capital=10_000.0, cash=10_000.0,
                    benchmark_ticker="SPY")
    booked, fill = buy(book, "TSLA", 321.11, "2026-08-06T10:34:00-04:00",
                       fraction=0.15, reason="ORB", qty=4.0, slippage_bps=0.0)
    assert booked.positions["TSLA"].qty == 4.0
    assert fill is not None and fill.qty == 4.0
    # cash reflects 4 shares plus fees, not the fractional size the ratio would have given
    assert booked.cash < 10_000.0 - 4 * 321.11 + 0.01


def test_an_explicit_quantity_of_zero_books_nothing() -> None:
    book = LaneBook(lane="session", initial_capital=10_000.0, cash=10_000.0,
                    benchmark_ticker="SPY")
    booked, fill = buy(book, "TSLA", 321.11, "t", fraction=0.15, reason="ORB", qty=0.0)
    assert fill is None and booked.positions == {}


def test_loss_anatomy_finds_the_bucket_that_dominates_the_result():
    """The 2026-08-10 case: the session lane looked like a failing strategy at -233, but five
    inherited-position force-flats carried -176.70 of it and the actual strategy was at -56.
    Grouping by exit reason is what turns one number into that conclusion."""
    trades = (
        [_sell("Altbestand (zwangsflat)", -35.34)] * 5      # -176.70, the real culprit
        + [_sell("Stop (0.5x Range)", -9.43)] * 16          # -150.88, the strategy working
        + [_sell("Ziel (1x Range)", 12.61)] * 6             # +75.66
    )
    rows = loss_anatomy(trades)
    assert [r["reason"] for r in rows][:2] == ["Altbestand (zwangsflat)", "Stop (0.5x Range)"]
    top = rows[0]
    assert top["n"] == 5
    assert top["total"] == pytest.approx(-176.70)
    assert top["avg"] == pytest.approx(-35.34)
    assert top["wins"] == 0
    # It carried the majority of the net result — that is the finding.
    assert top["share_of_total"] > 0.5


def test_loss_anatomy_ignores_buys_and_unrealised_rows():
    trades = [
        _sell("Ziel", 10.0),
        TradeFill(lane="session", executed_at="t", ticker="B", side="buy", qty=1.0,
                  price=100.0, fees=0.0, reason="ORB-Ausbruch"),  # no realized_pnl
    ]
    rows = loss_anatomy(trades)
    assert len(rows) == 1 and rows[0]["reason"] == "Ziel" and rows[0]["n"] == 1


def test_loss_anatomy_reports_no_share_when_the_net_is_zero():
    """Two offsetting buckets would each read as several hundred percent of a ~0 net."""
    rows = loss_anatomy([_sell("Ziel", 50.0), _sell("Stop", -50.0)])
    assert all(r["share_of_total"] is None for r in rows)


def test_loss_anatomy_of_an_empty_book_is_empty_not_an_error():
    assert loss_anatomy([]) == []


def _sell(reason: str, pnl: float) -> TradeFill:
    return TradeFill(lane="session", executed_at="2026-08-10T15:00", ticker="AAA", side="sell",
                     qty=1.0, price=100.0, fees=0.0, reason=reason, realized_pnl=pnl)
