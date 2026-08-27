"""Full-ranking persistence: ranking_sink seam + run_scores table roundtrip."""
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.models import Instrument, Pick
from equity_scout.pipeline import run_pipeline
from equity_scout.storage import init_db, load_run_scores, save_run, save_run_scores


def _inst(ticker: str, region: str = "US", sector: str = "Technology") -> Instrument:
    return Instrument(ticker=ticker, name=ticker, exchange="X", region=region,
                      currency="USD", sector=sector)


def _pick(ticker: str, bucket: str, rank: int, region: str = "EU") -> Pick:
    return Pick(instrument=_inst(ticker, region=region), bucket=bucket, rank=rank,
                composite=1.0 / rank, breakdown={"value": 0.5})


def test_pipeline_ranking_sink_gets_full_buckets_result_keeps_top_n():
    universe = [_inst(f"T{i:02d}") for i in range(30)]
    captured: dict = {}

    # Fester FX-Stub: sonst zieht der Investierbarkeitsfilter einen echten Wechselkurs.
    result = run_pipeline(universe, FakeProvider(), top_n=2, fx_rate=lambda c: 0.86,
                          ranking_sink=lambda full: captured.update(full))

    full_count = sum(len(picks) for picks in captured.values())
    kept_count = sum(len(picks) for picks in result.buckets.values())
    assert full_count >= kept_count
    for bucket, picks in result.buckets.items():
        assert len(picks) <= 2
        assert picks == captured[bucket][: len(picks)]  # sliced prefix, ranks preserved


def test_save_run_returns_id_and_run_scores_roundtrip(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    from equity_scout.models import RunResult
    run_id = save_run(db, RunResult(created_at="2026-07-15T00:00:00+00:00",
                                    universe_size=2, gated_out={}))
    assert isinstance(run_id, int) and run_id > 0

    buckets = {"defensive": [_pick("MC.PA", "defensive", 1), _pick("SAP.DE", "defensive", 2)],
               "aggressive": [_pick("NVDA", "aggressive", 1, region="US")]}
    save_run_scores(db, run_id, buckets)
    rows = load_run_scores(db, run_id)
    assert len(rows) == 3
    mc = next(r for r in rows if r["ticker"] == "MC.PA")
    assert mc["country"] == "FR" and mc["region"] == "EU" and mc["bucket"] == "defensive"
    assert mc["sector"] == "Technology" and mc["breakdown"] == {"value": 0.5}


def test_load_run_scores_empty_for_unknown_run(tmp_path):
    db = tmp_path / "runs.db"
    init_db(db)
    assert load_run_scores(db, 999) == []


def test_load_company_names_spans_all_runs_and_prefers_the_newest(tmp_path):
    from equity_scout.models import RunResult
    from equity_scout.storage import load_company_names

    db = tmp_path / "names.db"
    init_db(db)

    def _named(ticker: str, name: str) -> Pick:
        inst = Instrument(ticker=ticker, name=name, exchange="X", region="US",
                          currency="USD", sector="Technology")
        return Pick(instrument=inst, bucket="balanced", rank=1, composite=0.5,
                    breakdown={"value": 0.5})

    old = save_run(db, RunResult(created_at="2026-06-01T00:00:00+00:00",
                                 universe_size=2, gated_out={}))
    save_run_scores(db, old, {"balanced": [_named("MU", "Micron Technology"),
                                           _named("DROP", "Dropped Corp")]})
    new = save_run(db, RunResult(created_at="2026-07-01T00:00:00+00:00",
                                 universe_size=1, gated_out={}))
    save_run_scores(db, new, {"balanced": [_named("MU", "Micron Technology Inc")]})

    names = load_company_names(db)
    assert names["MU"] == "Micron Technology Inc"   # jüngster Lauf gewinnt
    assert names["DROP"] == "Dropped Corp"          # gefallene Titel bleiben fragbar


def test_load_company_names_is_empty_on_a_pre_feature_db(tmp_path):
    from equity_scout.storage import load_company_names

    assert load_company_names(tmp_path / "empty.db") == {}
