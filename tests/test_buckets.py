from equity_scout.buckets import BUCKET_WEIGHTS, assign_buckets
from equity_scout.models import FactorScore, Instrument


def _score(t, value, quality, momentum, growth, low_vol=0.5):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return FactorScore(inst, value, quality, momentum, growth, low_vol)


def test_buckets_are_disjoint_and_by_character():
    scores = [
        _score("D1", value=0.9, quality=0.9, momentum=0.1, growth=0.1, low_vol=0.9),
        _score("D2", value=0.8, quality=0.8, momentum=0.2, growth=0.1, low_vol=0.8),
        _score("M1", value=0.5, quality=0.5, momentum=0.5, growth=0.5, low_vol=0.5),
        _score("M2", value=0.4, quality=0.5, momentum=0.5, growth=0.6, low_vol=0.5),
        _score("A1", value=0.1, quality=0.1, momentum=0.9, growth=0.9, low_vol=0.1),
        _score("A2", value=0.2, quality=0.1, momentum=0.8, growth=0.9, low_vol=0.1),
    ]
    out = assign_buckets(scores, top_n=10)
    assert set(out) == set(BUCKET_WEIGHTS)

    # disjoint: no ticker appears in more than one bucket
    tickers = [p.instrument.ticker for picks in out.values() for p in picks]
    assert len(tickers) == len(set(tickers))

    # by character: the defensive-tilted stocks land in defensive, offensive ones in aggressive
    assert {p.instrument.ticker for p in out["defensive"]} == {"D1", "D2"}
    assert {p.instrument.ticker for p in out["aggressive"]} == {"A1", "A2"}


def test_top_n_truncates_each_bucket():
    scores = [
        _score(f"S{i}", value=i / 30, quality=0.5, momentum=1 - i / 30, growth=1 - i / 30, low_vol=0.5)
        for i in range(30)
    ]
    out = assign_buckets(scores, top_n=4)
    assert all(len(picks) <= 4 for picks in out.values())
