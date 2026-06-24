from equity_scout.models import Instrument, Quote


def test_instrument_and_quote_are_constructible():
    inst = Instrument(ticker="AAPL", name="Apple", exchange="NASDAQ",
                      region="US", currency="USD", sector="Tech")
    q = Quote(instrument=inst, trailing_pe=30.0, price_to_book=40.0,
              return_on_equity=1.5, profit_margins=0.25,
              revenue_growth=0.08, earnings_growth=0.10, momentum_6m=0.12)
    assert q.instrument.ticker == "AAPL"
    assert q.momentum_6m == 0.12
