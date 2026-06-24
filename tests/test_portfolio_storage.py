from equity_scout.models import Instrument, Pick
from equity_scout.portfolio import advance, mark_to_market, new_portfolio
from equity_scout.portfolio_storage import (
    append_valuation,
    init_portfolio_db,
    load_portfolio,
    load_valuations,
    save_portfolio,
)


def _pick(ticker, composite):
    inst = Instrument(ticker, ticker, "US", "US", "USD", "Tech")
    return Pick(inst, "balanced", 1, composite,
                {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5})


def test_portfolio_roundtrip_preserves_positions(tmp_path):
    db = tmp_path / "p.db"
    init_portfolio_db(db)
    pf = new_portfolio(100_000.0)
    pf, _ = advance(pf, [_pick("AAPL", 0.9)], {"AAPL": 150.0}, now="d1", benchmark_price=400.0)
    save_portfolio(db, pf)

    loaded = load_portfolio(db)
    assert loaded is not None
    assert "AAPL" in loaded.positions
    assert loaded.positions["AAPL"].instrument.ticker == "AAPL"
    assert abs(loaded.cash - pf.cash) < 1e-6
    assert loaded.benchmark_shares > 0


def test_save_portfolio_upserts_single_row(tmp_path):
    db = tmp_path / "p.db"
    init_portfolio_db(db)
    save_portfolio(db, new_portfolio(100_000.0))
    save_portfolio(db, new_portfolio(50_000.0))
    loaded = load_portfolio(db)
    assert loaded is not None and loaded.initial_capital == 50_000.0


def test_valuation_history_is_ordered(tmp_path):
    db = tmp_path / "p.db"
    init_portfolio_db(db)
    pf = new_portfolio(100_000.0)
    append_valuation(db, "d1", mark_to_market(pf, {}))
    append_valuation(db, "d2", mark_to_market(pf, {}))
    history = load_valuations(db)
    assert [v["created_at"] for v in history] == ["d1", "d2"]
