from equity_scout.analysis import FakeAnalysis, attach_theses
from equity_scout.models import Instrument, Pick


def _pick(t):
    inst = Instrument(t, t, "E", "US", "USD", "Tech")
    return Pick(inst, "aggressive", 1, 0.8,
                {"value": 0.1, "quality": 0.1, "momentum": 0.9, "growth": 0.9})


def test_attach_theses_fills_thesis_for_each_pick():
    buckets = {"aggressive": [_pick("AGG")]}
    out = attach_theses(buckets, FakeAnalysis())
    thesis = out["aggressive"][0].thesis
    assert thesis is not None and "AGG" in thesis


def test_attach_theses_is_noop_when_provider_none():
    buckets = {"aggressive": [_pick("AGG")]}
    out = attach_theses(buckets, None)
    assert out["aggressive"][0].thesis is None
