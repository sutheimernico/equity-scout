from equity_scout.factors import score_factors
from equity_scout.models import Instrument, Quote


def _q(t, pe, roe, mom, growth, sector="Tech", vol=None, high_prox=None):
    inst = Instrument(t, t, "E", "US", "USD", sector)
    return Quote(instrument=inst, trailing_pe=pe, price_to_book=None,
                 return_on_equity=roe, profit_margins=None,
                 revenue_growth=growth, earnings_growth=None, momentum_6m=mom,
                 volatility_6m=vol, high_52w_proximity=high_prox)


def test_lower_pe_scores_higher_on_value():
    quotes = [_q("CHEAP", 5.0, 0.1, 0.0, 0.0), _q("RICH", 50.0, 0.1, 0.0, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["CHEAP"].value > scores["RICH"].value


def test_higher_momentum_scores_higher():
    quotes = [_q("UP", 10.0, 0.1, 0.5, 0.0), _q("DOWN", 10.0, 0.1, -0.2, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["UP"].momentum > scores["DOWN"].momentum


def test_52w_high_proximity_feeds_the_momentum_family():
    """v8 D1: with the 6m leg absent, the George/Hwang proximity alone carries the
    momentum family — NEAR at its 52w high must outrank FAR at 60 % of its high."""
    quotes = [
        _q("NEAR", 10.0, 0.1, None, 0.0, high_prox=0.99),
        _q("FAR", 10.0, 0.1, None, 0.0, high_prox=0.60),
    ]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["NEAR"].momentum > scores["FAR"].momentum


def test_momentum_degrades_to_6m_leg_without_proximity():
    """Pre-v8 cache rows have no proximity: the family averages what is present, so the
    6m return alone still ranks — never a crash, never a fake 0-proximity."""
    quotes = [_q("UP", 10.0, 0.1, 0.5, 0.0), _q("DOWN", 10.0, 0.1, -0.2, 0.0)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["UP"].momentum == 1.0
    assert scores["DOWN"].momentum == 0.0


def test_missing_family_scores_zero():
    # neither quote has growth metrics present -> growth family score is 0.0
    quotes = [_q("A", 10.0, 0.1, 0.1, None), _q("B", 20.0, 0.2, 0.2, None)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["A"].growth == 0.0
    assert scores["B"].growth == 0.0


def test_non_positive_pe_not_treated_as_cheap():
    # NEG has a negative P/E (loss-making) -> dropped, gets no value score;
    # POS has a valid P/E -> scores above NEG.
    quotes = [_q("NEG", -5.0, 0.1, 0.1, 0.1), _q("POS", 10.0, 0.1, 0.1, 0.1)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["POS"].value > scores["NEG"].value
    assert scores["NEG"].value == 0.0  # no valid value metric


def test_lower_volatility_scores_higher_on_low_vol():
    quotes = [_q("CALM", 10.0, 0.1, 0.1, 0.1, vol=0.01),
              _q("WILD", 10.0, 0.1, 0.1, 0.1, vol=0.5)]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["CALM"].low_vol > scores["WILD"].low_vol


def test_value_ranked_within_sector():
    # Same P/E pattern in two sectors. Sector-relative ranking scores each sector independently,
    # so the cheap one in each sector tops its own sector (global ranking would mix them).
    quotes = [
        _q("TA", 10.0, 0.1, 0.1, 0.1, sector="Tech"),
        _q("TB", 30.0, 0.1, 0.1, 0.1, sector="Tech"),
        _q("EA", 10.0, 0.1, 0.1, 0.1, sector="Energy"),
        _q("EB", 30.0, 0.1, 0.1, 0.1, sector="Energy"),
    ]
    scores = {s.instrument.ticker: s for s in score_factors(quotes)}
    assert scores["TA"].value == 1.0 and scores["EA"].value == 1.0  # cheap tops its sector
    assert scores["TB"].value == 0.0 and scores["EB"].value == 0.0


def test_clean_rejects_non_numeric_and_non_finite_values():
    from equity_scout.factors import _clean

    assert _clean("Infinity", False) is None  # yfinance string garbage (live crash 2026-07-14)
    assert _clean(True, False) is None  # bool is not a metric
    assert _clean(float("nan"), False) is None
    assert _clean(float("inf"), False) is None
    assert _clean(2.5, False) == 2.5
    assert _clean(-1.0, True) is None
