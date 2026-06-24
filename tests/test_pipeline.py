from equity_scout.analysis import FakeAnalysis
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.models import Instrument
from equity_scout.pipeline import run_pipeline


def test_pipeline_end_to_end_with_fakes():
    universe = [
        Instrument("GOOD", "Good", "E", "US", "USD", "Tech"),
        Instrument("THIN", "Thin", "E", "EM", "XXX", "Misc"),
    ]
    provider = FakeProvider({
        "GOOD": dict(trailing_pe=10.0, price_to_book=2.0, return_on_equity=0.3,
                     profit_margins=0.2, revenue_growth=0.15, earnings_growth=0.2,
                     momentum_6m=0.1),
        "THIN": dict(trailing_pe=10.0),  # no momentum -> gated out
    })
    run = run_pipeline(universe, provider, analysis=FakeAnalysis(),
                       top_n=5, created_at="2026-06-24T00:00:00")
    assert run.universe_size == 2
    assert "THIN" in run.gated_out
    assert run.buckets["balanced"][0].instrument.ticker == "GOOD"
    assert run.buckets["balanced"][0].thesis is not None


def test_pipeline_without_llm_leaves_thesis_none():
    universe = [Instrument("GOOD", "Good", "E", "US", "USD", "Tech")]
    provider = FakeProvider({
        "GOOD": dict(trailing_pe=10.0, price_to_book=2.0, return_on_equity=0.3,
                     profit_margins=0.2, momentum_6m=0.1),
    })
    run = run_pipeline(universe, provider, analysis=None, top_n=5,
                       created_at="2026-06-24T00:00:00")
    assert run.buckets["balanced"][0].thesis is None
