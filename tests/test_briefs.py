"""Pure tests for briefs.py (no network) + one endpoint test with the fundamentals
seam monkeypatched, per the `tests/test_api.py` TestClient idiom."""
from __future__ import annotations

from fastapi.testclient import TestClient

from equity_scout.briefs import (
    build_brief,
    pitch_market_context,
    rank_entries,
    score_band,
    zone_gap,
)
from equity_scout.fundamentals import Fundamentals
from equity_scout.radar import Watchlist, WatchlistEntry
from equity_scout.radar_storage import save_watchlist


def _entry(ticker="AAA", price=100.0, zone_low=90.0, zone_high=110.0,
           in_zone=True, composite=0.48) -> dict:
    return {
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "bucket": "balanced",
        "price": price,
        "entry_zone_low": zone_low,
        "entry_zone_high": zone_high,
        "proximity": 0.0,
        "in_zone": in_zone,
        "composite": composite,
        "readings": [],
        "zone_note": "",
        "breakdown": {},
        "tranches": [],
    }


# --- score_band -------------------------------------------------------------------

def test_score_band_boundaries():
    assert score_band(39) == "niedrig"
    assert score_band(40) == "mittel"
    assert score_band(69) == "mittel"
    assert score_band(70) == "hoch"


# --- zone_gap ----------------------------------------------------------------------

def test_zone_gap_inside_zone():
    assert zone_gap(100.0, 90.0, 110.0) == (0.0, "im Einstiegsbereich")


def test_zone_gap_above_zone_rounds_against_zone_high():
    gap, verdict = zone_gap(829.5, 462.31, 479.44)
    assert gap == 73.0
    # Wording changed 2026-08-06: "zu teuer" claimed a value judgement the support-band
    # geometry cannot make, and contradicted the analyst upside on the same card.
    assert verdict == "73 % über der Einstiegszone"


def test_zone_gap_below_zone_rounds_against_zone_low():
    gap, verdict = zone_gap(50.0, 90.0, 110.0)
    # Negative by design (2026-08-07): the sign carries the direction. Both sides used to
    # return positive gaps, so entry_note's below-zone branch never fired and a
    # broken-support stock read as sitting "über dem letzten Support".
    assert gap == -44.0
    # Never phrased as a bargain: below the zone every support has broken (see zone_gap).
    assert verdict == "44 % unter der Zone — Support gebrochen"
    assert "günstig" not in verdict


def test_entry_note_below_zone_names_the_broken_support():
    from equity_scout.briefs import entry_note

    note = entry_note(in_zone=False, gap_pct=-44.0, upside_pct=30.0)
    assert "Support-Levels sind gefallen" in note
    assert "44 %" in note
    # The wrong branch used to claim the price sat ABOVE the last support.
    assert "über dem letzten Support" not in note


def test_zone_gap_zero_or_negative_price_is_honest_none():
    assert zone_gap(0.0, 90.0, 110.0) == (None, "kein gültiger Kurs verfügbar")
    assert zone_gap(-5.0, 90.0, 110.0) == (None, "kein gültiger Kurs verfügbar")


# --- rank_entries --------------------------------------------------------------------

def test_rank_entries_in_zone_beats_higher_composite_out_of_zone():
    in_zone_low_score = _entry("LOW", in_zone=True, composite=0.30)
    out_zone_high_score = _entry("HIGH", in_zone=False, composite=0.90)
    ranked = rank_entries([out_zone_high_score, in_zone_low_score])
    assert [e["ticker"] for e in ranked] == ["LOW", "HIGH"]


# --- build_brief --------------------------------------------------------------------

def test_build_brief_without_fundamentals_has_null_fundamentals_fields():
    brief = build_brief(_entry(), fundamentals=None)
    assert brief["ticker"] == "AAA"
    assert brief["sector"] is None
    assert brief["industry"] is None
    assert brief["currency"] is None
    assert brief["trailing_pe"] is None
    assert brief["analyst_target"] is None
    assert brief["analyst_count"] is None
    assert brief["analyst_upside_pct"] is None
    assert brief["model_target"] is None
    assert brief["model_stop"] is None
    # zone/score fields stay populated even without fundamentals
    assert brief["score"] == 48
    assert brief["score_band"] == "mittel"
    assert brief["zone_low"] == 90.0
    assert brief["zone_high"] == 110.0
    assert brief["in_zone"] is True
    assert brief["zone_gap_pct"] == 0.0
    assert brief["zone_verdict"] == "im Einstiegsbereich"


def test_build_brief_analyst_upside_correct():
    fund = Fundamentals(
        trailing_pe=18.6, analyst_target=1507.79, analyst_count=43,
        currency="USD", sector="Technology", industry="Semiconductors",
    )
    entry = _entry(ticker="MU", price=829.5, zone_low=462.31, zone_high=479.44,
                    in_zone=False, composite=0.48)
    brief = build_brief(entry, fund)
    assert brief["sector"] == "Technology"
    assert brief["industry"] == "Semiconductors"
    assert brief["trailing_pe"] == 18.6
    assert brief["analyst_target"] == 1507.79
    assert brief["analyst_count"] == 43
    assert brief["analyst_upside_pct"] == 81.8
    assert brief["zone_gap_pct"] == 73.0
    # This assertion pair used to read "+81.8 % upside" and "zu teuer" in the same breath —
    # the contradiction Nico hit on the card, sitting unnoticed in a green test.
    assert brief["zone_verdict"] == "73 % über der Einstiegszone"
    assert "Wert" in brief["entry_note"] and "Zeitpunkt" in brief["entry_note"]


def test_build_brief_analyst_upside_null_when_price_is_zero():
    fund = Fundamentals(trailing_pe=18.6, analyst_target=1507.79, analyst_count=43,
                         currency="USD")
    brief = build_brief(_entry(price=0.0), fund)
    assert brief["analyst_upside_pct"] is None


# --- pitch_market_context (inbox enrichment, 2026-08-06) ------------------------------

def test_pitch_market_context_off_watchlist_degrades_to_none():
    # A ticker that dropped off the watchlist has no current price — every field is an
    # honest None, never the stale pitch-time numbers presented as today's view.
    context = pitch_market_context(None, None)
    assert all(value is None for value in context.values())


def test_pitch_market_context_builds_todays_view():
    fund = Fundamentals(trailing_pe=15.0, analyst_target=130.0, analyst_count=11,
                         currency="USD")
    entry = _entry(ticker="AAA", price=100.0, zone_low=90.0, zone_high=110.0,
                    in_zone=True, composite=0.5)
    context = pitch_market_context(entry, fund)
    assert context["bucket"] == "balanced"  # risk chip on the pitch card
    assert context["current_price"] == 100.0
    assert context["in_zone"] is True
    assert context["zone_verdict"] == "im Einstiegsbereich"
    assert context["analyst_upside_pct"] == 30.0
    assert context["analyst_count"] == 11
    assert "Wert" in context["entry_note"]


def test_pitch_market_context_without_fundamentals_keeps_zone_fields():
    entry = _entry(ticker="AAA", price=150.0, zone_low=90.0, zone_high=110.0,
                    in_zone=False, composite=0.5)
    context = pitch_market_context(entry, None)
    assert context["zone_verdict"] == "36 % über der Einstiegszone"
    assert context["analyst_upside_pct"] is None
    assert context["entry_note"]  # relates zone to the missing analyst view


# --- endpoint ------------------------------------------------------------------------

def _watchlist_entry(**kwargs) -> WatchlistEntry:
    defaults = dict(
        ticker="AAA", name="AAA Inc.", bucket="balanced", price=100.0,
        entry_zone_low=90.0, entry_zone_high=110.0, proximity=0.0, in_zone=True,
        composite=0.30, readings=[], zone_note="", breakdown={}, tranches=[],
    )
    defaults.update(kwargs)
    return WatchlistEntry(**defaults)


def test_briefs_endpoint_orders_and_survives_one_bad_ticker(tmp_path, monkeypatch):
    import equity_scout.api as api_mod

    db = tmp_path / "briefs.db"
    wl = Watchlist(
        created_at="2026-08-04T09:00:00",
        entries=[
            # out-of-zone, high composite -> must rank AFTER the in-zone entry despite
            # the higher score, same rule as the frontend's StockList.rank()
            _watchlist_entry(ticker="HIGH", name="High Corp", in_zone=False,
                              composite=0.90, price=200.0, entry_zone_low=150.0,
                              entry_zone_high=180.0),
            _watchlist_entry(ticker="AAA", name="AAA Inc.", in_zone=True,
                              composite=0.30, price=100.0),
            _watchlist_entry(ticker="BAD", name="Bad Ticker Inc.", in_zone=False,
                              composite=0.10, price=50.0, entry_zone_low=40.0,
                              entry_zone_high=60.0),
        ],
    )
    save_watchlist(str(db), wl)

    def fake_fetch(ticker: str) -> Fundamentals:
        if ticker == "AAA":
            return Fundamentals(trailing_pe=15.0, analyst_target=120.0,
                                 analyst_count=10, currency="USD",
                                 sector="Tech", industry="Semis")
        if ticker == "HIGH":
            return Fundamentals(None, None, None, "EUR")
        raise RuntimeError("yfinance boom")  # BAD ticker: fetch fails

    # The endpoint calls the CACHED wrapper (see fundamentals.fetch_fundamentals_cached);
    # patching the raw fetch would silently hit the network instead.
    monkeypatch.setattr(api_mod, "fetch_fundamentals_cached", fake_fetch)

    client = TestClient(api_mod.create_app(str(db)))
    resp = client.get("/api/briefs?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert "disclaimer" in body
    tickers = [b["ticker"] for b in body["briefs"]]
    # in-zone (AAA) first despite the lowest composite; HIGH/BAD follow by composite desc
    assert tickers == ["AAA", "HIGH", "BAD"]

    aaa = body["briefs"][0]
    assert aaa["sector"] == "Tech"
    assert aaa["analyst_target"] == 120.0

    bad = body["briefs"][2]
    assert bad["ticker"] == "BAD"
    assert bad["sector"] is None
    assert bad["trailing_pe"] is None
    assert bad["analyst_upside_pct"] is None
    # zone/score fields still populated for the failed-fundamentals ticker
    assert bad["zone_verdict"] == "im Einstiegsbereich"


def test_briefs_endpoint_limit_is_capped(tmp_path, monkeypatch):
    import equity_scout.api as api_mod

    db = tmp_path / "briefs2.db"
    wl = Watchlist(
        created_at="2026-08-04T09:00:00",
        entries=[_watchlist_entry(ticker=f"T{i}", composite=0.5 - i * 0.01)
                 for i in range(25)],
    )
    save_watchlist(str(db), wl)
    # The endpoint calls the CACHED wrapper, so that is the seam to patch.
    monkeypatch.setattr(api_mod, "fetch_fundamentals_cached",
                         lambda t: Fundamentals(None, None, None, None))

    client = TestClient(api_mod.create_app(str(db)))
    body = client.get("/api/briefs?limit=999").json()
    assert len(body["briefs"]) == 20  # hard-capped, never all 25


def test_inbox_endpoint_enriches_open_pitches_with_todays_context(tmp_path, monkeypatch):
    import equity_scout.api as api_mod
    from equity_scout.inbox_storage import create_pitch

    db = str(tmp_path / "inbox-context.db")
    wl = Watchlist(
        created_at="2026-08-06T09:00:00",
        entries=[_watchlist_entry(ticker="AAA", name="AAA Inc.", price=100.0,
                                    in_zone=True, composite=0.5)],
    )
    save_watchlist(db, wl)
    # ON the current watchlist -> gets today's zone/potential context
    on_list = create_pitch(
        db, ticker="AAA", watchlist_id=1, price=95.0, composite=0.5,
        zone_low=90.0, zone_high=110.0, pitch="P", created_at="2026-07-16T10:00:00+00:00",
    )
    # OFF the watchlist -> every context field is an honest None
    off_list = create_pitch(
        db, ticker="ZZZ", watchlist_id=1, price=50.0, composite=0.4,
        zone_low=40.0, zone_high=60.0, pitch="P", created_at="2026-07-16T10:00:00+00:00",
    )
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda t: Fundamentals(trailing_pe=None, analyst_target=130.0,
                                analyst_count=11, currency="USD"),
    )

    client = TestClient(api_mod.create_app(db))
    rows = {p["id"]: p for p in client.get("/api/inbox").json()["pitches"]}

    enriched = rows[on_list]
    assert enriched["name"] == "AAA Inc."
    assert enriched["current_price"] == 100.0  # today's price, not the 95.0 pitch price
    assert enriched["zone_verdict"] == "im Einstiegsbereich"
    assert enriched["analyst_upside_pct"] == 30.0
    assert enriched["entry_note"]

    bare = rows[off_list]
    assert bare["current_price"] is None
    assert bare["zone_verdict"] is None
    assert bare["analyst_upside_pct"] is None

    # A decided pitch needs no buying context — fields stay None after the decision.
    assert client.post(f"/api/inbox/{on_list}/decision", json={"action": "later"}).status_code == 200
    decided = {p["id"]: p for p in client.get("/api/inbox").json()["pitches"]}[on_list]
    assert decided["status"] == "later"
    assert decided["current_price"] is None


# ===== Fundamentals TTL cache (2026-08-04) =====
# /api/briefs is hit on every phone app open; without a cache that is `limit` live yfinance
# calls per visit against a free, rate-limited endpoint.

def test_cached_fundamentals_serves_the_second_call_from_memory():
    from equity_scout.fundamentals import Fundamentals, fetch_fundamentals_cached

    calls = []

    def fake(ticker: str) -> Fundamentals:
        calls.append(ticker)
        return Fundamentals(18.6, 1500.0, 43, "USD", "Technology", "Semiconductors")

    first = fetch_fundamentals_cached("CACHE_HIT", fetch=fake, now=1000.0)
    second = fetch_fundamentals_cached(
        "CACHE_HIT", fetch=lambda t: (_ for _ in ()).throw(AssertionError("refetched")),
        now=1000.0 + 60,
    )
    assert first == second
    assert calls == ["CACHE_HIT"]


def test_cached_fundamentals_refetches_after_the_ttl():
    from equity_scout.fundamentals import (
        FUNDAMENTALS_TTL_SECONDS,
        Fundamentals,
        fetch_fundamentals_cached,
    )

    calls = []

    def fake(ticker: str) -> Fundamentals:
        calls.append(ticker)
        return Fundamentals(1.0, None, None, "USD")

    fetch_fundamentals_cached("CACHE_TTL", fetch=fake, now=0.0)
    fetch_fundamentals_cached("CACHE_TTL", fetch=fake, now=FUNDAMENTALS_TTL_SECONDS + 1)
    assert len(calls) == 2


def test_cached_fundamentals_never_caches_an_empty_result():
    """An all-None result is what a rate-limited fetch looks like. Caching it would turn
    one bad moment into hours of empty cards (same rule as data/cache.py)."""
    from equity_scout.fundamentals import Fundamentals, fetch_fundamentals_cached

    calls = []

    def failing(ticker: str) -> Fundamentals:
        calls.append(ticker)
        return Fundamentals(None, None, None, None)

    fetch_fundamentals_cached("CACHE_EMPTY", fetch=failing, now=500.0)
    fetch_fundamentals_cached("CACHE_EMPTY", fetch=failing, now=501.0)
    assert len(calls) == 2  # retried, not replayed


# --- insight + chart pass-through (2026-08-05) ------------------------------------

def test_build_brief_passes_the_insight_through():
    brief = build_brief(
        _entry(), Fundamentals(None, None, None, None),
        insight={
            "generated_at": "2026-08-05T18:00:00+00:00",
            "business": "Baut Speicherchips.",
            "news_summary": "Prognose angehoben.",
            "headlines": ["Guidance raised"],
            "model": "qwen2.5:7b",
        },
        chart={
            "as_of": "2026-08-05T18:00:00+00:00",
            "first_date": "2025-08-05",
            "last_date": "2026-08-05",
            "closes": [10.0, 12.0],
        },
    )
    assert brief["insight"]["business"] == "Baut Speicherchips."
    assert brief["insight"]["headlines"] == ["Guidance raised"]
    assert brief["chart"]["closes"] == [10.0, 12.0]


def test_build_brief_without_an_insight_is_an_honest_null():
    # Nothing generated yet (fresh DB, or a stock outside the generator's top-N).
    brief = build_brief(_entry(), None)
    assert brief["insight"] is None
    assert brief["chart"] is None


def test_briefs_endpoint_serves_the_cached_insight(tmp_path, monkeypatch):
    """Same seams as test_briefs_endpoint_orders_and_survives_one_bad_ticker above:
    the `_watchlist_entry` helper, `api_mod.create_app(str(db))`, and the CACHED
    fundamentals wrapper patched so the test never touches the network."""
    import equity_scout.api as api_mod
    from equity_scout.insights_storage import save_insight, save_price_series

    db = tmp_path / "insights_api.db"
    save_watchlist(str(db), Watchlist(
        created_at="2026-08-05T20:30:00",
        entries=[_watchlist_entry(ticker="MU", name="Micron Technology", in_zone=True)],
    ))
    save_insight(
        str(db), ticker="MU", generated_at="2026-08-05T18:00:00+00:00",
        business="Baut Speicherchips.", news_summary="Prognose angehoben.",
        headlines=["Guidance raised"], model="qwen2.5:7b",
    )
    save_price_series(
        str(db), ticker="MU", as_of="2026-08-05T18:00:00+00:00",
        first_date="2025-08-05", last_date="2026-08-05", closes=[10.0, 12.0],
    )
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda ticker: Fundamentals(None, None, None, None),
    )

    client = TestClient(api_mod.create_app(str(db)))
    payload = client.get("/api/briefs").json()["briefs"]
    assert payload[0]["insight"]["business"] == "Baut Speicherchips."
    assert payload[0]["chart"]["closes"] == [10.0, 12.0]


def test_briefs_endpoint_serves_a_null_insight_for_an_ungenerated_stock(tmp_path, monkeypatch):
    """A stock outside the generator's top-N must not break the card."""
    import equity_scout.api as api_mod

    db = tmp_path / "no_insights.db"
    save_watchlist(str(db), Watchlist(
        created_at="2026-08-05T20:30:00",
        entries=[_watchlist_entry(ticker="AAA")],
    ))
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda ticker: Fundamentals(None, None, None, None),
    )

    client = TestClient(api_mod.create_app(str(db)))
    payload = client.get("/api/briefs").json()["briefs"]
    assert payload[0]["insight"] is None
    assert payload[0]["chart"] is None


# --- bucket + scout target (cockpit rebuild, 2026-08-07) --------------------------

def test_build_brief_carries_bucket_and_target_stop():
    brief = build_brief(
        _entry(), None,
        target_stop={"target": 141.2, "stop": 99.0, "sigma": 0.02,
                     "horizon_days": 20, "source": "heuristic_v1"},
    )
    assert brief["bucket"] == "balanced"
    assert brief["model_target"] == 141.2
    assert brief["model_stop"] == 99.0
    assert brief["target_source"] == "heuristic_v1"


def test_build_brief_without_target_stop_keeps_honest_nulls():
    brief = build_brief(_entry(), None)
    assert brief["model_target"] is None
    assert brief["model_stop"] is None
    assert brief["target_source"] is None


def test_briefs_endpoint_computes_scout_target_from_cached_series(tmp_path, monkeypatch):
    """The Scout-Ziel comes from the nightly-cached close series (no live fetch): with
    no entry_tb champion registered the provenance must say heuristic_v1."""
    import equity_scout.api as api_mod
    from equity_scout.insights_storage import save_price_series

    db = tmp_path / "briefs-target.db"
    save_watchlist(str(db), Watchlist(
        created_at="2026-08-07T09:00:00",
        entries=[_watchlist_entry(ticker="MU", name="Micron Technology")],
    ))
    # 60 mildly varying closes: enough history for the heuristic's 20-day vol window.
    closes = [100.0 + (i % 7) * 0.9 + i * 0.1 for i in range(60)]
    save_price_series(
        str(db), ticker="MU", as_of="2026-08-07T18:00:00+00:00",
        first_date="2026-05-01", last_date="2026-08-06", closes=closes,
    )
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda ticker: Fundamentals(None, None, None, None),
    )

    client = TestClient(api_mod.create_app(str(db)))
    brief = client.get("/api/briefs").json()["briefs"][0]
    assert brief["target_source"] == "heuristic_v1"
    assert brief["model_target"] > closes[-1] > brief["model_stop"]
    assert brief["bucket"] == "balanced"


def test_briefs_endpoint_single_ticker_param(tmp_path, monkeypatch):
    """?ticker= narrows to one card (profile deep link) — and an off-watchlist ticker
    yields an empty list, not an error."""
    import equity_scout.api as api_mod

    db = tmp_path / "briefs-one.db"
    save_watchlist(str(db), Watchlist(
        created_at="2026-08-07T09:00:00",
        entries=[_watchlist_entry(ticker="MU"), _watchlist_entry(ticker="ASML")],
    ))
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda ticker: Fundamentals(None, None, None, None),
    )

    client = TestClient(api_mod.create_app(str(db)))
    briefs = client.get("/api/briefs?ticker=mu").json()["briefs"]
    assert [b["ticker"] for b in briefs] == ["MU"]
    assert client.get("/api/briefs?ticker=ZZZ").json()["briefs"] == []


# --- entry_note: value vs. timing (2026-08-06) ------------------------------------

def test_zone_verdict_above_the_zone_no_longer_claims_the_stock_is_expensive():
    """"zu teuer" reads as a VALUE statement and collided head-on with a +69 % analyst
    upside on the same card (Nico: "Warum sollte die Aktie dann zu teuer sein, wenn noch
    so ein hohes Potenzial?"). The zone is a SUPPORT band, so being above it is a TIMING
    statement — same lesson as the 2026-08-04 "noch günstiger" correction on the low side.
    """
    _gap, verdict = zone_gap(200.0, 90.0, 110.0)
    assert "teuer" not in verdict
    assert "über der Einstiegszone" in verdict


def test_entry_note_names_both_perspectives_when_they_disagree():
    from equity_scout.briefs import entry_note

    note = entry_note(in_zone=False, gap_pct=69.0, upside_pct=69.0)
    # Both words must appear: the reader has to see that these are two different questions.
    assert "Wert" in note
    assert "Zeitpunkt" in note
    assert "69" in note


def test_entry_note_when_price_is_in_the_zone_and_analysts_see_room():
    from equity_scout.briefs import entry_note

    note = entry_note(in_zone=True, gap_pct=0.0, upside_pct=15.0)
    assert "Support" in note
    # Never a recommendation — the project makes no buy calls.
    assert "kaufen" not in note.lower()
    assert "einstieg" not in note.lower() or "Einstiegszone" in note


def test_entry_note_when_in_zone_but_analysts_see_no_upside():
    from equity_scout.briefs import entry_note

    note = entry_note(in_zone=True, gap_pct=0.0, upside_pct=-7.0)
    assert "kein" in note.lower()


def test_entry_note_below_the_zone_says_support_is_gone():
    from equity_scout.briefs import entry_note

    note = entry_note(in_zone=False, gap_pct=-12.0, upside_pct=40.0)
    assert "Support" in note


def test_entry_note_without_analyst_coverage_only_states_the_timing():
    from equity_scout.briefs import entry_note

    note = entry_note(in_zone=False, gap_pct=30.0, upside_pct=None)
    assert "Analyst" not in note or "keine" in note.lower()


def test_build_brief_carries_the_entry_note():
    fund = Fundamentals(trailing_pe=None, analyst_target=169.0, analyst_count=43,
                        currency="USD")
    brief = build_brief(_entry(price=100.0, zone_low=50.0, zone_high=60.0, in_zone=False), fund)
    assert "Wert" in brief["entry_note"]
    assert "Zeitpunkt" in brief["entry_note"]
