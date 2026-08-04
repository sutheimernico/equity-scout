"""Pure tests for briefs.py (no network) + one endpoint test with the fundamentals
seam monkeypatched, per the `tests/test_api.py` TestClient idiom."""
from __future__ import annotations

from fastapi.testclient import TestClient

from equity_scout.briefs import build_brief, rank_entries, score_band, zone_gap
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
    assert verdict == "73 % über der Zone — zu teuer"


def test_zone_gap_below_zone_rounds_against_zone_low():
    gap, verdict = zone_gap(50.0, 90.0, 110.0)
    assert gap == 44.0
    assert verdict == "44 % unter der Zone — noch günstiger"


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
    assert brief["zone_verdict"] == "73 % über der Zone — zu teuer"


def test_build_brief_analyst_upside_null_when_price_is_zero():
    fund = Fundamentals(trailing_pe=18.6, analyst_target=1507.79, analyst_count=43,
                         currency="USD")
    brief = build_brief(_entry(price=0.0), fund)
    assert brief["analyst_upside_pct"] is None


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

    monkeypatch.setattr(api_mod, "fetch_fundamentals", fake_fetch)

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
    monkeypatch.setattr(api_mod, "fetch_fundamentals",
                         lambda t: Fundamentals(None, None, None, None))

    client = TestClient(api_mod.create_app(str(db)))
    body = client.get("/api/briefs?limit=999").json()
    assert len(body["briefs"]) == 20  # hard-capped, never all 25
