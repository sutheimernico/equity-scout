"""Ein Titel, ein Kaufplan (Nachtschicht 2026-08-27).

Der gefährlichste Fehler auf dieser Karte wäre eine erfundene Zahl: ein Kauflimit, an dem
nichts mehr stützt, oder ein Kursziel, das keiner gerechnet hat. Die Tests zielen genau
dorthin — und auf die Stelle, an der ein hoher Score eine kaputte Kurslage überstimmen könnte.
"""
from __future__ import annotations

from equity_scout.buy_plan import (
    MAX_POSITION_SHARE_PCT,
    STANCE_AVOID,
    STANCE_FAR,
    STANCE_READY,
    STANCE_WAIT,
    TRADABILITY_EUROPE,
    TRADABILITY_HARD,
    TRADABILITY_HOME,
    TRADABILITY_US,
    build_plan,
    buy_limit_for,
    buyers_from_events,
    hold_note,
    relabel_tranches,
    sort_plans,
    stance_for,
    tradability,
    tranche_basis,
    why_lines,
)
from equity_scout.evidence.base import SOURCE_13F, SOURCE_CONGRESS, SOURCE_INSIDER
from equity_scout.exits import ExitRules


def _brief(**kwargs) -> dict:
    base: dict = {
        "ticker": "TEST", "name": "Test AG", "price": 100.0, "score": 60,
        "score_band": "mittel", "zone_low": 90.0, "zone_high": 110.0, "in_zone": True,
        "zone_gap_pct": 0.0, "currency": "EUR", "model_target": 120.0, "model_stop": 85.0,
        "target_source": "model", "analyst_target": 130.0, "analyst_count": 12,
        "insight": {"business": "Baut Dinge.", "headlines_de": ["Schlagzeile A"]},
    }
    base.update(kwargs)
    return base


# --- Haltung: die Kurslage entscheidet, nicht der Score --------------------------------------

def test_inside_the_zone_is_ready_to_buy():
    assert stance_for(in_zone=True, price=100.0, zone_low=90.0, zone_high=110.0) == STANCE_READY


def test_below_the_zone_is_avoid_even_with_a_top_score():
    """Der reale Fall ITC.NS am 2026-08-26: Score 69, und trotzdem kein Kauf."""
    plan = build_plan(
        _brief(score=69, price=271.4, zone_low=277.08, zone_high=312.2, in_zone=False),
        evidence_state="ungeprüft",
    )
    assert plan.entry.stance == STANCE_AVOID
    assert plan.score == 69  # der Score bleibt sichtbar — er überstimmt die Haltung nur nicht
    assert "gefallen" in plan.entry.stance_note


def test_just_above_the_zone_is_wait():
    assert stance_for(in_zone=False, price=112.0, zone_low=90.0, zone_high=110.0) == STANCE_WAIT


def test_far_above_the_zone_is_its_own_stance():
    """5 % ist die Grenze — darüber ist es kein „fast", sondern ein Lauf."""
    assert stance_for(in_zone=False, price=115.6, zone_low=90.0, zone_high=110.0) == STANCE_FAR
    assert stance_for(in_zone=False, price=115.5, zone_low=90.0, zone_high=110.0) == STANCE_WAIT


# --- Das Kauflimit: lieber keins als eins ohne Halt ------------------------------------------

def test_the_limit_inside_the_zone_is_the_current_price():
    assert buy_limit_for(STANCE_READY, price=100.0, zone_high=110.0) == 100.0


def test_the_limit_above_the_zone_is_the_zone_edge_not_the_price():
    """Wer über der Zone kauft, soll auf sie warten — das Limit ist die Kante."""
    assert buy_limit_for(STANCE_WAIT, price=112.0, zone_high=110.0) == 110.0
    assert buy_limit_for(STANCE_FAR, price=140.0, zone_high=110.0) == 110.0


def test_there_is_no_limit_below_a_broken_zone():
    """Eine Zahl hinzuschreiben täuschte einen Halt vor, den es nicht mehr gibt."""
    assert buy_limit_for(STANCE_AVOID, price=80.0, zone_high=110.0) is None


def test_the_broken_zone_plan_carries_no_limit():
    plan = build_plan(
        _brief(price=80.0, zone_low=90.0, zone_high=110.0, in_zone=False),
        evidence_state="ungeprüft",
    )
    assert plan.entry.limit is None


# --- Verkaufen und Nicht-Verkaufen -----------------------------------------------------------

def test_the_hold_band_names_both_edges_and_the_currency():
    note = hold_note(120.0, 85.0, "EUR")
    assert "85.00 EUR" in note and "120.00 EUR" in note
    assert "kein Verkaufsgrund" in note


def test_a_missing_target_falls_back_to_the_rules_never_to_a_made_up_price():
    note = hold_note(None, 85.0, "EUR")
    assert "Kein Modell-Kursziel" in note
    assert "20 %" in note and "15 %" in note  # die Regel, nicht eine erfundene Zahl


def test_the_exit_rules_travel_with_the_plan():
    plan = build_plan(_brief(), evidence_state="ungeprüft")
    assert plan.exit.profit_target_pct == 20.0
    assert plan.exit.stop_loss_pct == 15.0
    assert plan.exit.max_holding_days == 180


def test_custom_exit_rules_are_honoured_rather_than_hardcoded():
    plan = build_plan(
        _brief(), evidence_state="ungeprüft",
        rules=ExitRules(profit_target=0.3, stop_loss=0.1, max_holding_days=90),
    )
    assert plan.exit.profit_target_pct == 30.0
    assert plan.exit.max_holding_days == 90


def test_the_analyst_target_stays_separate_from_the_model_target():
    """Zwei verschiedene Behauptungen von zwei verschiedenen Quellen — nie ein Feld."""
    plan = build_plan(_brief(model_target=120.0, analyst_target=130.0), evidence_state="x")
    assert plan.exit.target == 120.0 and plan.exit.target_source == "model"
    assert plan.exit.analyst_target == 130.0 and plan.exit.analyst_count == 12


def test_a_missing_model_target_stays_empty_instead_of_borrowing_the_analyst_one():
    plan = build_plan(
        _brief(model_target=None, model_stop=None, target_source=None), evidence_state="x"
    )
    assert plan.exit.target is None and plan.exit.stop is None
    assert plan.exit.analyst_target == 130.0  # die fremde Zahl bleibt, wo sie hingehört


# --- Größe und Tranchen -----------------------------------------------------------------------

def test_the_position_cap_is_a_number_the_surface_can_compute_with():
    plan = build_plan(_brief(), evidence_state="x")
    assert plan.sizing.max_share_pct == MAX_POSITION_SHARE_PCT


def test_tranches_are_counted_and_named_in_the_note():
    tranches = [
        {"label": "Jetzt", "share": 1 / 3, "trigger_price": 100.0},
        {"label": "bei −7 %", "share": 1 / 3, "trigger_price": 93.0},
        {"label": "bei −15 %", "share": 1 / 3, "trigger_price": 85.0},
    ]
    plan = build_plan(_brief(), evidence_state="x", tranches=tranches)
    assert plan.sizing.tranche_count == 3
    assert "3 Schritte" in plan.sizing.note
    assert plan.entry.tranches[1]["trigger_price"] == 93.0


def test_without_tranches_the_note_does_not_claim_any():
    plan = build_plan(_brief(), evidence_state="x")
    assert plan.sizing.tranche_count == 0
    assert "Schritte" not in plan.sizing.note


# --- Warum, Geschäft, News, Käufer -----------------------------------------------------------

def test_the_why_lines_come_from_the_computed_breakdown_not_from_prose():
    lines = why_lines({"value": 0.9, "momentum": 0.7, "quality": 0.5, "size": 0.1})
    assert lines == ["value: 90/100", "momentum: 70/100", "quality: 50/100"]


def test_zero_and_negative_factors_are_not_sold_as_reasons():
    assert why_lines({"value": 0.0, "momentum": -0.2}) == []


def test_a_missing_breakdown_yields_no_reasons_rather_than_a_generic_one():
    assert why_lines(None) == []
    assert build_plan(_brief(), evidence_state="x").why == []


def test_the_original_headline_is_always_carried_next_to_the_translation():
    """Die lokale Übersetzung erfindet gelegentlich Inhalt — das Original ist die Prüfmarke."""
    brief = _brief(insight={"headlines": ["English one"], "headlines_de": ["Deutsche eins"]})
    news = build_plan(brief, evidence_state="x").news
    assert news == [{
        "headline": "English one", "de": "Deutsche eins",
        "translation_note": "maschinell übersetzt — Original daneben prüfen",
    }]


def test_a_headline_without_a_translation_still_shows_the_original():
    brief = _brief(insight={"headlines": ["English one"]})
    news = build_plan(brief, evidence_state="x").news
    assert news[0]["headline"] == "English one" and news[0]["de"] is None


def test_a_translation_without_an_original_is_never_shown_alone():
    """Ohne Quelle keine Anzeige: eine unbelegbare Zeile ist genau der Halluzinationsfall."""
    brief = _brief(insight={"headlines": [], "headlines_de": ["Erfundene Zeile"]})
    assert build_plan(brief, evidence_state="x").news == []


def test_the_ehld_case_keeps_its_own_source_visible():
    """Realfall 2026-08-26: aus „Stock Price, News & Analysis" wurde eine Tatsachenbehauptung."""
    brief = _brief(insight={
        "headlines": ["Euroholdings Ltd. (NASDAQ: EHLD) Stock Price, News & Analysis - Kalkine"],
        "headlines_de": ["EHLD profitiert von starker Nachfrage nach Elektrifizierung"],
    })
    item = build_plan(brief, evidence_state="x").news[0]
    assert "Stock Price, News & Analysis" in item["headline"]
    assert item["de"].startswith("EHLD profitiert")  # sichtbar, aber nie ohne die Quelle


def test_a_stock_without_insights_shows_empty_business_and_news():
    plan = build_plan(_brief(insight=None), evidence_state="x")
    assert plan.business is None and plan.news == []


def test_the_news_list_is_capped_so_one_card_cannot_become_a_feed():
    brief = _brief(insight={"headlines": [f"H{i}" for i in range(20)]})
    assert len(build_plan(brief, evidence_state="x").news) == 5


def test_buyers_are_passed_through_untouched():
    buyers = [{"person": "Ein Abgeordneter", "kind": "congress", "date": "2026-08-01"}]
    assert build_plan(_brief(), evidence_state="x", buyers=buyers).buyers == buyers


def test_no_buyers_is_an_empty_list_never_a_claim_of_none():
    assert build_plan(_brief(), evidence_state="x").buyers == []


# --- Herkunft und Bilanz ----------------------------------------------------------------------

def test_every_plan_states_what_is_known_about_its_source():
    plan = build_plan(_brief(), evidence_state="Rangliste: 12 Vorschläge, kein Befund")
    assert plan.evidence_state == "Rangliste: 12 Vorschläge, kein Befund"


def test_the_track_record_travels_with_the_plan_not_in_a_subpage():
    record = {"n_independent": 12, "mean_excess_pct": -1.4}
    assert build_plan(_brief(), evidence_state="x", track_record=record).track_record == record


def test_the_horizon_is_explicit_on_every_plan():
    assert build_plan(_brief(), evidence_state="x").horizon == "lang"
    assert build_plan(_brief(), horizon="kurz", evidence_state="x").horizon == "kurz"


# --- Reihenfolge ------------------------------------------------------------------------------

def test_ready_to_buy_sorts_above_a_higher_scoring_broken_one():
    ready = build_plan(_brief(ticker="READY", score=40), evidence_state="x")
    broken = build_plan(
        _brief(ticker="BROKEN", score=99, price=80.0, in_zone=False), evidence_state="x"
    )
    assert [p.ticker for p in sort_plans([broken, ready])] == ["READY", "BROKEN"]


def test_within_the_same_stance_the_higher_score_wins():
    low = build_plan(_brief(ticker="LOW", score=30), evidence_state="x")
    high = build_plan(_brief(ticker="HIGH", score=80), evidence_state="x")
    assert [p.ticker for p in sort_plans([low, high])] == ["HIGH", "LOW"]


def test_a_plan_serialises_to_plain_json_types():
    plan = build_plan(_brief(), evidence_state="x")
    as_dict = plan.to_dict()
    assert as_dict["entry"]["stance"] == STANCE_READY
    assert as_dict["exit"]["target"] == 120.0
    assert as_dict["sizing"]["max_share_pct"] == MAX_POSITION_SHARE_PCT


# --- Wer hat gekauft ---------------------------------------------------------------------------

def test_a_voice_in_the_news_is_not_a_buyer():
    """Am 2026-08-26 hing „Warren Buffett" an einer Meldung über Meteoritenfunde."""
    events = [{"source": "voice", "event_date": "2026-08-26",
               "details": {"speaker": "Warren Buffett", "kind": "context"}}]
    assert buyers_from_events(events) == []


def test_news_themes_and_filings_that_are_not_purchases_are_excluded():
    events = [
        {"source": "news_theme", "event_date": "2026-08-26", "details": {"theme": "inflation"}},
        {"source": "edgar_8k", "event_date": "2026-08-26", "details": {}},
    ]
    assert buyers_from_events(events) == []


def test_the_three_purchase_sources_are_recognised_by_their_shared_constants():
    """Gespiegelt aus evidence.base — ein getippter String wäre der people.ts-Fehler noch einmal."""
    events = [
        {"source": SOURCE_CONGRESS, "event_date": "2026-08-01",
         "details": {"politician": "Abgeordnete X", "filing_date": "2026-08-20"}},
        {"source": SOURCE_INSIDER, "event_date": "2026-08-02",
         "details": {"insider": "CFO Y", "filing_date": "2026-08-05"}},
        {"source": SOURCE_13F, "event_date": "2026-08-03",
         "details": {"fund": "Fonds Z", "filed_at": "2026-08-14", "change": "new"}},
    ]
    buyers = buyers_from_events(events)
    assert [b["kind"] for b in buyers] == ["Fonds (13F)", "Insider", "Kongress"]  # jüngste zuerst
    assert [b["person"] for b in buyers] == ["Fonds Z", "CFO Y", "Abgeordnete X"]


def test_the_reporting_delay_is_carried_so_the_card_cannot_fake_freshness():
    events = [{"source": SOURCE_CONGRESS, "event_date": "2026-07-01",
               "details": {"politician": "Abgeordnete X", "filing_date": "2026-08-14"}}]
    buyer = buyers_from_events(events)[0]
    assert buyer["event_date"] == "2026-07-01" and buyer["reported_at"] == "2026-08-14"


def test_a_purchase_without_a_named_person_says_unknown_rather_than_dropping_it():
    events = [{"source": SOURCE_CONGRESS, "event_date": "2026-08-01", "details": {}}]
    assert buyers_from_events(events)[0]["person"] == "unbekannt"


# --- Handelbarkeit: ein Plan für einen unkaufbaren Titel ist kein Plan ------------------------

def test_an_indian_listing_is_flagged_as_hard_to_reach():
    """Drei der Top-10 vom 2026-08-26 waren indische Werte."""
    result = tradability("ITC.NS")
    assert result["level"] == TRADABILITY_HARD
    assert "eigenen Depot prüfen" in result["note"]


def test_a_plain_symbol_is_treated_as_a_us_listing():
    assert tradability("MU")["level"] == TRADABILITY_US


def test_european_venues_are_their_own_level():
    for ticker in ("AGS.BR", "EZJ.L", "TEL2-B.ST"):
        assert tradability(ticker)["level"] == TRADABILITY_EUROPE


def test_a_german_listing_is_the_easiest_case():
    assert tradability("SAP.DE")["level"] == TRADABILITY_HOME


def test_an_unknown_venue_is_hard_not_assumed_fine():
    """Eine Unbekannte ist keine Freigabe."""
    assert tradability("FOO.XYZ")["level"] == TRADABILITY_HARD


def test_the_estimate_never_claims_to_have_checked_a_broker():
    """Welche Börsen Nicos Depot bedient, weiß nur er — die Karte darf es nicht behaupten."""
    assert tradability("ITC.NS")["checked_broker"] is False
    assert build_plan(_brief(), evidence_state="x").tradability["checked_broker"] is False


def test_tradability_travels_on_the_plan():
    plan = build_plan(_brief(ticker="ITC.NS"), evidence_state="x")
    assert plan.tradability["level"] == TRADABILITY_HARD
    assert plan.to_dict()["tradability"]["level"] == TRADABILITY_HARD


# --- Die Tranchenleiter darf dem Limit nicht widersprechen -------------------------------------

def test_the_ladder_starts_at_the_current_price_when_ready_to_buy():
    assert tranche_basis(STANCE_READY, price=100.0, limit=100.0) == 100.0


def test_the_ladder_starts_at_the_limit_when_waiting_not_at_the_price():
    """Realfall EHLD: Limit 7,56 und gleichzeitig „Tranche 1 jetzt bei 9,89" — ein Widerspruch."""
    assert tranche_basis(STANCE_WAIT, price=9.89, limit=7.56) == 7.56
    assert tranche_basis(STANCE_FAR, price=9.89, limit=7.56) == 7.56


def test_there_is_no_ladder_below_a_broken_zone():
    assert tranche_basis(STANCE_AVOID, price=80.0, limit=None) is None


def test_now_still_means_now_when_the_ladder_sits_on_the_current_price():
    ladder = [{"label": "Jetzt", "share": 1 / 3, "trigger_price": 100.0}]
    assert relabel_tranches(ladder, at_limit=False)[0]["label"] == "Jetzt"


def test_the_first_step_is_renamed_when_the_ladder_sits_on_the_limit():
    """„Jetzt bei 7,56" neben „warten" ist derselbe Widerspruch, nur in Worten."""
    ladder = [{"label": "Jetzt", "share": 1 / 3, "trigger_price": 7.56}]
    assert relabel_tranches(ladder, at_limit=True)[0]["label"] == "bei Limit"


def test_the_other_step_labels_and_all_prices_survive_the_rename():
    ladder = [
        {"label": "Jetzt", "share": 1 / 3, "trigger_price": 7.56},
        {"label": "bei −7 %", "share": 1 / 3, "trigger_price": 7.03},
    ]
    renamed = relabel_tranches(ladder, at_limit=True)
    assert renamed[1]["label"] == "bei −7 %"
    assert [t["trigger_price"] for t in renamed] == [7.56, 7.03]
