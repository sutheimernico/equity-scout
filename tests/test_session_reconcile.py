"""Two books that can drift are two books that WILL drift. This compares them and says so
out loud; nothing here merges silently."""
from __future__ import annotations

from dataclasses import replace

from equity_scout.alpaca_broker import BrokerFill, BrokerPosition
from equity_scout.session_reconcile import BrokerExit, Divergence, reconcile, resolve_book_only
from equity_scout.shortterm_book import LaneBook, LanePosition


def _book(**positions: LanePosition) -> LaneBook:
    return replace(LaneBook.fresh("session"), positions=dict(positions))


def _pos(qty: float) -> LanePosition:
    return LanePosition(qty=qty, entry_price=300.0, opened_at="2026-08-04T09:45:00-04:00")


def test_matching_books_report_no_divergence() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    assert reconcile(_book(AAPL=_pos(3.0)), broker) == []


def test_position_only_at_the_broker_is_reported() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    result = reconcile(_book(), broker)
    assert result == [Divergence("AAPL", kind="broker_only", book_qty=0.0, broker_qty=3.0)]


def test_position_only_in_the_book_is_reported() -> None:
    result = reconcile(_book(AAPL=_pos(3.0)), {})
    assert result == [Divergence("AAPL", kind="book_only", book_qty=3.0, broker_qty=0.0)]


def test_quantity_mismatch_is_reported() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 2.0, 301.0)}
    result = reconcile(_book(AAPL=_pos(3.0)), broker)
    assert result == [Divergence("AAPL", kind="qty_mismatch", book_qty=3.0, broker_qty=2.0)]


def test_rounding_difference_below_one_share_is_not_a_divergence() -> None:
    """The book sizes fractionally, the broker fills whole shares — a sub-share gap is the
    designed consequence of rounding down, not a fault."""
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    assert reconcile(_book(AAPL=_pos(3.9)), broker) == []


def test_a_full_share_gap_is_a_divergence() -> None:
    """Not in the plan: the tolerance boundary itself. Rounding down can lose at most a
    fraction, so a gap of exactly one whole share is never explained by rounding — a book
    of 4.0 should have produced 4 shares, not 3.
    """
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    result = reconcile(_book(AAPL=_pos(4.0)), broker)
    assert result == [Divergence("AAPL", kind="qty_mismatch", book_qty=4.0, broker_qty=3.0)]


def test_a_sub_share_book_position_the_broker_never_took_is_not_a_divergence() -> None:
    """bracket_payload refuses anything below one share, so the book can legitimately hold
    a fraction the broker never received. That is the rounding rule working, not drift."""
    assert reconcile(_book(AAPL=_pos(0.4)), {}) == []


def test_divergences_describe_themselves_for_the_log() -> None:
    kinds = {
        "broker_only": Divergence("AAPL", kind="broker_only", book_qty=0.0, broker_qty=3.0),
        "book_only": Divergence("AAPL", kind="book_only", book_qty=3.0, broker_qty=0.0),
        "qty_mismatch": Divergence("AAPL", kind="qty_mismatch", book_qty=3.0, broker_qty=2.0),
    }
    assert "Broker haelt 3" in kinds["broker_only"].describe()
    assert "Buch haelt 3" in kinds["book_only"].describe()
    assert "Buch 3 vs Broker 2" in kinds["qty_mismatch"].describe()


def _fill(qty: float, price: float, at: str, *, side: str = "sell", ticker: str = "META",
          order_id: str = "o1", requested: float | None = None) -> BrokerFill:
    return BrokerFill(order_id=order_id, ticker=ticker, side=side, qty=qty, price=price, at=at,
                      requested_price=requested)


def test_the_exit_carries_what_the_leg_asked_for() -> None:
    """So the execution log can measure the stop against its own stop price instead of
    against a signal nobody sent."""
    divergence = Divergence("META", kind="book_only", book_qty=2.0, broker_qty=0.0)
    fills = [_fill(2.0, 591.965, "2026-08-07T17:03:11Z", requested=592.08)]
    exit_ = resolve_book_only(divergence, fills, opened_at="2026-08-07T10:45:00-04:00")
    assert exit_ is not None and exit_.requested_price == 592.08


def test_partials_from_legs_that_asked_for_different_prices_carry_no_expectation() -> None:
    """Two legs at two prices have no single expectation, and averaging them would invent
    one. No number beats a made-up number."""
    divergence = Divergence("AAPL", kind="book_only", book_qty=4.0, broker_qty=0.0)
    fills = [
        _fill(1.0, 312.0, "2026-08-07T15:34:39Z", ticker="AAPL", order_id="a", requested=312.5),
        _fill(3.0, 313.0, "2026-08-07T15:34:41Z", ticker="AAPL", order_id="b", requested=313.5),
    ]
    exit_ = resolve_book_only(divergence, fills, opened_at="2026-08-07T10:00:00-04:00")
    assert exit_ is not None and exit_.requested_price is None


def test_a_book_only_divergence_resolves_to_the_brokers_own_exit() -> None:
    """The 2026-08-07 META case: the bracket's stop leg filled at 591.965 in the market and
    nobody read it back, so the book closed itself at the signal price 0.14 higher. The exit
    the broker actually made is the one that belongs in the book."""
    divergence = Divergence("META", kind="book_only", book_qty=2.0, broker_qty=0.0)
    fills = [_fill(2.0, 591.965, "2026-08-07T17:03:11Z", order_id="stop")]
    assert resolve_book_only(divergence, fills, opened_at="2026-08-07T10:45:00-04:00") == (
        BrokerExit(ticker="META", qty=2.0, price=591.965, at="2026-08-07T17:03:11Z",
                   order_ids=("stop",))
    )


def test_a_fill_from_before_the_position_was_opened_is_not_its_exit() -> None:
    """The book stamps New York time, Alpaca answers UTC. Compared as strings, an 18:00Z fill
    looks later than a 15:45-04:00 entry while it is in fact four hours EARLIER — booking it
    would close today's position with yesterday's afternoon trade."""
    divergence = Divergence("META", kind="book_only", book_qty=2.0, broker_qty=0.0)
    fills = [_fill(2.0, 591.965, "2026-08-07T18:00:00Z")]
    assert resolve_book_only(divergence, fills, opened_at="2026-08-07T15:45:00-04:00") is None


def test_partial_exits_are_aggregated_at_their_weighted_price() -> None:
    """One share at a time is how 2026-08-06's MSFT divergence started."""
    divergence = Divergence("AAPL", kind="book_only", book_qty=4.0, broker_qty=0.0)
    fills = [
        _fill(1.0, 312.0, "2026-08-07T15:34:39Z", ticker="AAPL", order_id="a"),
        _fill(3.0, 313.0, "2026-08-07T15:34:41Z", ticker="AAPL", order_id="b"),
    ]
    exit_ = resolve_book_only(divergence, fills, opened_at="2026-08-07T10:00:00-04:00")
    assert exit_ is not None
    assert exit_.qty == 4.0
    assert exit_.price == (1.0 * 312.0 + 3.0 * 313.0) / 4.0
    assert exit_.at == "2026-08-07T15:34:41Z"  # the last one: that is when the book went flat
    assert exit_.order_ids == ("a", "b")


def test_fills_that_do_not_cover_the_book_position_resolve_to_nothing() -> None:
    """Half an exit is not an exit. Booking it as one would flatten a book position the
    broker only partly closed — the divergence stays reported instead of half-healed."""
    divergence = Divergence("AAPL", kind="book_only", book_qty=4.0, broker_qty=0.0)
    fills = [_fill(1.0, 312.0, "2026-08-07T15:34:39Z", ticker="AAPL")]
    assert resolve_book_only(divergence, fills, opened_at="2026-08-07T10:00:00-04:00") is None


def test_a_buy_fill_is_never_read_as_an_exit() -> None:
    divergence = Divergence("META", kind="book_only", book_qty=2.0, broker_qty=0.0)
    fills = [_fill(2.0, 597.67, "2026-08-07T14:45:07Z", side="buy")]
    assert resolve_book_only(divergence, fills, opened_at="2026-08-07T10:00:00-04:00") is None


def test_another_tickers_fill_is_never_read_as_an_exit() -> None:
    divergence = Divergence("META", kind="book_only", book_qty=2.0, broker_qty=0.0)
    fills = [_fill(2.0, 591.9, "2026-08-07T17:03:11Z", ticker="TSLA")]
    assert resolve_book_only(divergence, fills, opened_at="2026-08-07T10:00:00-04:00") is None


def test_only_a_book_only_divergence_is_healed() -> None:
    """`broker_only` means a position nobody in the book knows about — there is no fill to
    book, and adopting the position would be guessing. `qty_mismatch` means the broker still
    holds something. Both stay reported, per the broker-is-truth rule."""
    fills = [_fill(2.0, 591.965, "2026-08-07T17:03:11Z")]
    for kind, book_qty, broker_qty in (("broker_only", 0.0, 2.0), ("qty_mismatch", 3.0, 2.0)):
        divergence = Divergence("META", kind=kind, book_qty=book_qty, broker_qty=broker_qty)
        assert resolve_book_only(divergence, fills,
                                 opened_at="2026-08-07T10:00:00-04:00") is None


def test_a_naive_opened_at_is_not_guessed_at() -> None:
    """Every book timestamp comes from a tz-aware bar index (v12 R8). If one ever arrives
    without an offset, the window check cannot be made — and a healer that guesses the zone
    would book an exit that may predate the entry."""
    divergence = Divergence("META", kind="book_only", book_qty=2.0, broker_qty=0.0)
    fills = [_fill(2.0, 591.965, "2026-08-07T17:03:11Z")]
    assert resolve_book_only(divergence, fills, opened_at="2026-08-07T10:00:00") is None


def test_several_tickers_are_reported_in_a_stable_order() -> None:
    """The report goes into a log and a digest line; unstable ordering would make two
    identical states look like two different ones."""
    broker = {"TSLA": BrokerPosition("TSLA", 2.0, 330.0)}
    result = reconcile(_book(NVDA=_pos(5.0), AAPL=_pos(3.0)), broker)
    assert [d.ticker for d in result] == ["AAPL", "NVDA", "TSLA"]
