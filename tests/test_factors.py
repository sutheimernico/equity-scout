from equity_scout.factors import score_factors
from equity_scout.models import Instrument, Quote


def _q(t, pe, roe, mom, growth):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return Quote(instrument=inst, trailing_pe=pe, price_to_book=None,
                 return_on_equity=roe, profit_margins=None,
                 revenue_growth=growth, earnings_growth=None, momentum_6m=mom)


def test_lower_pe_scores_higher_on_value():
    quotes = [_q("CHEAP", 5.0, 0.1, 0.0, 0.0), _q("RICH", 50.0, 0.1, 0.0, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["CHEAP"].value > scores["RICH"].value


def test_higher_momentum_scores_higher():
    quotes = [_q("UP", 10.0, 0.1, 0.5, 0.0), _q("DOWN", 10.0, 0.1, -0.2, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["UP"].momentum > scores["DOWN"].momentum


def test_missing_family_scores_zero():
    # neither quote has growth metrics present -> growth family score is 0.0
    quotes = [_q("A", 10.0, 0.1, 0.1, None), _q("B", 20.0, 0.2, 0.2, None)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["A"].growth == 0.0
    assert scores["B"].growth == 0.0
