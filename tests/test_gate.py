from equity_scout.gate import apply_gate
from equity_scout.models import Instrument, Quote

INST = Instrument("X", "X", "E", "US", "USD", "Tech")


def _quote(**kw):
    base = dict(trailing_pe=None, price_to_book=None, return_on_equity=None,
                profit_margins=None, revenue_growth=None, earnings_growth=None,
                momentum_6m=None)
    base.update(kw)
    return Quote(instrument=INST, **base)


def test_gate_rejects_when_too_few_metrics():
    q = _quote(trailing_pe=10.0)  # 1 metric, no momentum
    passed, rejected = apply_gate([q], min_metrics=4)
    assert passed == []
    assert "X" in rejected


def test_gate_rejects_when_missing_momentum():
    q = _quote(trailing_pe=10.0, return_on_equity=0.2, revenue_growth=0.1, profit_margins=0.15)
    passed, rejected = apply_gate([q], min_metrics=4)
    assert passed == []
    assert "momentum" in rejected["X"]


def test_gate_passes_with_enough_metrics_and_momentum():
    q = _quote(trailing_pe=10.0, return_on_equity=0.2, revenue_growth=0.1,
               profit_margins=0.15, momentum_6m=0.05)
    passed, rejected = apply_gate([q], min_metrics=4)
    assert [p.instrument.ticker for p in passed] == ["X"]
    assert rejected == {}
