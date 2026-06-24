from equity_scout.buckets import BUCKET_WEIGHTS, assign_buckets
from equity_scout.models import FactorScore, Instrument


def _score(t, value, quality, momentum, growth):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return FactorScore(inst, value, quality, momentum, growth)


def test_buckets_present_and_ranked():
    scores = [
        _score("DEF", value=0.9, quality=0.9, momentum=0.1, growth=0.1),
        _score("AGG", value=0.1, quality=0.1, momentum=0.9, growth=0.9),
    ]
    out = assign_buckets(scores, top_n=2)
    assert set(out) == set(BUCKET_WEIGHTS)
    assert out["defensive"][0].instrument.ticker == "DEF"
    assert out["aggressive"][0].instrument.ticker == "AGG"
    assert out["defensive"][0].rank == 1


def test_top_n_truncates():
    scores = [_score(f"T{i}", 0.5, 0.5, i / 10, 0.5) for i in range(5)]
    out = assign_buckets(scores, top_n=3)
    assert len(out["aggressive"]) == 3
