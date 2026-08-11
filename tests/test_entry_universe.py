"""The entry model's training universe: fixed, ex ante, identical across runs.

Pins the property the whole module exists for — two nights must train on the SAME universe. Before
2026-08-11 the trainer took the current watchlist, so the sample changed almost nightly (n_train
swung 80..4806) and champion AUCs from different nights were compared as if commensurate.
"""
from __future__ import annotations

from equity_scout.ml.entry_universe import (
    TRAINING_REGION,
    TRAINING_UNIVERSE_AS_OF,
    training_universe,
)
from equity_scout.models import Instrument


def _inst(ticker: str, region: str = "US") -> Instrument:
    return Instrument(
        ticker=ticker, name=ticker, exchange="X", region=region, currency="USD", sector="Tech"
    )


def test_only_the_requested_region_survives():
    """The benchmark is SPY and the market-context features are US-derived, so a Tokyo listing is
    scored against a market it does not trade in."""
    got = training_universe([_inst("AAPL"), _inst("7203.T", "JP"), _inst("SAP.DE", "EU")])
    assert got == ["AAPL"]


def test_the_result_is_sorted_and_therefore_identical_across_runs():
    """THE property: byte-identical between nights. A set iteration order would silently reshuffle
    the universe and make two nights' metrics incomparable again."""
    a = training_universe([_inst("MSFT"), _inst("AAPL"), _inst("NVDA")])
    b = training_universe([_inst("NVDA"), _inst("AAPL"), _inst("MSFT")])
    assert a == b == ["AAPL", "MSFT", "NVDA"]


def test_duplicates_collapse():
    """The universe is a union of index sources, so one name can arrive twice — a duplicated ticker
    would double that name's weight in training."""
    assert training_universe([_inst("AAPL"), _inst("AAPL")]) == ["AAPL"]


def test_region_none_takes_everything():
    got = training_universe([_inst("AAPL"), _inst("7203.T", "JP")], region=None)
    assert got == ["7203.T", "AAPL"]


def test_an_empty_universe_yields_an_empty_list_not_an_error():
    """The caller decides what to do with 'no universe' (fall back to the watchlist); this function
    must not raise on it."""
    assert training_universe([]) == []
    assert training_universe([_inst("7203.T", "JP")]) == []


def test_the_snapshot_date_is_pinned_not_latest():
    """A 'latest snapshot' lookup would reintroduce exactly the night-to-night drift this module
    removes, so the date is a constant."""
    assert TRAINING_UNIVERSE_AS_OF == "2026-07-02"
    assert TRAINING_REGION == "US"
