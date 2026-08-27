"""Chancen-Meldungen: Auswahl, Laientext, LLM-Schliff und seine Grenzen."""
from __future__ import annotations

from equity_scout.opportunity import (
    build_llm_prompt,
    build_opportunity,
    factor_sentence,
    parse_llm_reply,
    polish,
    score_words,
    select_opportunities,
)


def _plan(
    ticker="MSFT", score=72, stance="kaufbereit", level="US-Börse", price=100.0, buyers=None,
) -> dict:
    return {
        "ticker": ticker,
        "name": f"{ticker} Inc",
        "horizon": "lang",
        "score": score,
        "price": price,
        "currency": "USD",
        "entry": {
            "stance": stance,
            "stance_note": "Kurs steht im Stützbereich — der Einstieg ist jetzt möglich.",
            "limit": 98.0,
            "tranches": [{"label": "1"}, {"label": "2"}, {"label": "3"}],
        },
        "exit": {"target": 120.0, "stop": 92.0, "analyst_target": 118.0, "analyst_count": 12},
        "sizing": {"max_share_pct": 5.0},
        "why": ["value: 100/100"],
        "factors": [{"name": "value", "score": 100}, {"name": "quality", "score": 80}],
        "buyers": buyers or [],
        "tradability": {"level": level, "note": "US-Notierung."},
        "track_record": {"line": "15 Vorschläge, p=0.94 — von Zufall nicht unterscheidbar."},
    }


def test_only_actionable_stances_become_a_notification() -> None:
    """„warten" heißt: der Kurs steht nicht dort, wo der Plan ihn haben will. Das ist ein
    Merkzettel, keine Gelegenheit."""
    plans = [_plan("A", stance="kaufbereit"), _plan("B", stance="warten")]
    assert [p["ticker"] for p in select_opportunities(plans, today="2026-08-27")] == ["A"]


def test_an_untradable_name_is_not_an_opportunity() -> None:
    """ITC.NS war am 2026-08-27 der einzige kaufbereite Titel der Watchlist — und über ein
    deutsches Depot praktisch nicht zu kaufen. Eine Meldung darüber ist eine Enttäuschung
    mit Extraschritten."""
    plans = [_plan("ITC.NS", score=69, level="schwer zugänglich")]
    assert select_opportunities(plans, today="2026-08-27") == []
    assert len(select_opportunities(plans, today="2026-08-27", require_tradable=False)) == 1


def test_the_quality_threshold_holds() -> None:
    assert select_opportunities([_plan(score=30)], today="2026-08-27") == []


def test_the_cooldown_prevents_the_same_name_every_morning() -> None:
    plans = [_plan("MSFT")]
    recent = select_opportunities(
        plans, today="2026-08-27", last_notified=lambda t: "2026-08-25T06:00:00+00:00"
    )
    assert recent == []
    old = select_opportunities(
        plans, today="2026-08-27", last_notified=lambda t: "2026-08-01T06:00:00+00:00"
    )
    assert len(old) == 1


def test_ranking_is_by_score_and_capped() -> None:
    plans = [_plan("A", score=50), _plan("B", score=90), _plan("C", score=70)]
    chosen = select_opportunities(plans, today="2026-08-27", max_count=2)
    assert [p["ticker"] for p in chosen] == ["B", "C"]


def test_factor_sentences_replace_the_raw_percentile_line() -> None:
    """„value: 100/100" ist für einen Laien keine Information — der erste Trockenlauf am
    2026-08-27 ist genau daran durchgefallen."""
    opportunity = build_opportunity(_plan())
    joined = " ".join(opportunity.why_now)
    assert "100/100" not in joined
    assert "günstiger" in joined


def test_score_words_never_read_like_a_grade() -> None:
    """Der Score ist ein RANG im Screening. „72" darf sich nicht wie eine Schulnote lesen."""
    assert "Screening" in score_words(72)
    assert "Qualitätsschwelle" in score_words(46)


def test_an_unknown_factor_is_skipped_not_invented() -> None:
    assert factor_sentence({"name": "voodoo", "score": 99}) is None
    assert factor_sentence({"name": "value", "score": 0}) is None


def test_every_notification_carries_its_counter_argument() -> None:
    opportunity = build_opportunity(_plan())
    assert "92,00" in opportunity.risk  # der Stop, ab dem die Idee widerlegt ist
    assert "schlagen den Markt nicht zuverlässig" in opportunity.risk


def test_the_lock_screen_line_stays_short_and_concrete() -> None:
    line = build_opportunity(_plan()).one_liner
    assert "Kurs" in line and "Limit" in line and len(line) < 160


def test_buyers_change_the_verdict_not_the_facts() -> None:
    plain = build_opportunity(_plan())
    with_buyers = build_opportunity(_plan(buyers=[{"kind": "insider"}, {"kind": "politician"}]))
    assert plain.verdict != with_buyers.verdict
    assert "Manager des Unternehmens selbst" in " ".join(with_buyers.why_now)


def test_the_llm_only_reformulates_what_is_already_measured() -> None:
    prompt = build_llm_prompt(build_opportunity(_plan()))
    assert "Gegenrede" in prompt and "GRUND:" in prompt
    # Die Gegenrede steht als KONTEXT im Prompt, aber das Modell wird nicht gebeten, sie
    # umzuschreiben — sonst landet sie über parse_llm_reply doch wieder in der Meldung.
    assert "ABER:" not in prompt
    # Keine Rohzahlen, aus denen ein Modell etwas Neues ableiten könnte.
    assert "72" not in prompt.split("Gemessene Punkte:")[0]


def test_a_well_formed_reply_replaces_the_rule_text() -> None:
    reply = (
        "GRUND: Die Firma verdient seit Jahren verlässlich Geld.\n"
        "GRUND: Der Kurs steht auf einer alten Unterstützung.\n"
        "GRUND: Mehrere Insider haben zuletzt selbst gekauft.\n"
        "ABER: Solche Auswahlverfahren schlagen den Markt nicht zuverlässig."
    )
    original = build_opportunity(_plan())
    polished = polish(original, ask=lambda p, s: reply)
    assert polished.explained_by == "llm" and len(polished.why_now) == 3
    # Die Gegenrede bleibt die regelbasierte: sie trägt den Stop-Kurs, und genau den hat
    # das Modell im Live-Test vom 2026-08-27 verloren.
    assert polished.risk == original.risk and "92,00" in polished.risk


def test_a_recommendation_in_the_reply_is_discarded_whole() -> None:
    """Ein halb gefiltertes Kaufversprechen ist gefährlicher als gar keins."""
    reply = (
        "GRUND: Die Firma ist stark aufgestellt und der Kurs wird steigen.\n"
        "GRUND: Der Einstieg ist günstig.\n"
        "ABER: Es gibt Risiken."
    )
    assert parse_llm_reply(reply) == ([], None)
    fallback = polish(build_opportunity(_plan()), ask=lambda p, s: reply)
    assert fallback.explained_by == "regeln"


def test_a_dead_model_costs_no_notification() -> None:
    def broken(prompt: str, system: str) -> str:
        raise TimeoutError("ollama ist aus")

    result = polish(build_opportunity(_plan()), ask=broken)
    assert result.explained_by == "regeln" and result.why_now


def test_a_malformed_reply_falls_back() -> None:
    assert parse_llm_reply("Ich denke, das ist eine gute Aktie.") == ([], None)
    assert parse_llm_reply("GRUND: zu kurz\nGRUND: auch\nABER: nein") == ([], None)


# --- „Bald": melden, BEVOR der Kurs in der Zone steht ---------------------------------

def _waiting(ticker="SAP.DE", gap=3.0, score=60) -> dict:
    plan = _plan(ticker, score=score, stance="warten")
    plan["entry"]["gap_pct"] = gap
    plan["entry"]["stance_note"] = "Knapp über dem Stützbereich. Mit Limit auf die Zone warten."
    return plan


def test_a_name_just_above_its_zone_is_an_early_notification() -> None:
    """Ohne diese Klasse hätte das System am 2026-08-27 null Meldungen gehabt."""
    chosen = select_opportunities([_waiting()], today="2026-08-27")
    assert [p["notification_kind"] for p in chosen] == ["bald"]


def test_a_name_far_above_its_zone_is_not() -> None:
    assert select_opportunities([_waiting(gap=12.0)], today="2026-08-27") == []


def test_ready_names_always_outrank_approaching_ones() -> None:
    """Eine Meldung, auf die man heute reagieren kann, schlägt eine mit höherem Score, auf
    die man nur warten kann."""
    chosen = select_opportunities(
        [_waiting("SOON", gap=1.0, score=90), _plan("READY", score=50)],
        today="2026-08-27", max_count=2,
    )
    assert [p["ticker"] for p in chosen] == ["READY", "SOON"]


def test_approaching_names_are_ordered_by_distance_not_score() -> None:
    """Wer morgen greifen kann, ist die frühere Meldung wert."""
    chosen = select_opportunities(
        [_waiting("FAR", gap=4.5, score=90), _waiting("NEAR", gap=0.5, score=50)],
        today="2026-08-27", max_count=2,
    )
    assert [p["ticker"] for p in chosen] == ["NEAR", "FAR"]


def test_an_early_notification_says_limit_not_buy() -> None:
    chosen = select_opportunities([_waiting()], today="2026-08-27")
    opportunity = build_opportunity(chosen[0])
    assert opportunity.kind == "bald"
    assert "Noch nichts tun" in opportunity.plan_line and "Kauflimit" in opportunity.plan_line
    assert "keine Kaufmeldung" in opportunity.verdict
    assert "3 %" in opportunity.headline


def test_approaching_can_be_switched_off() -> None:
    assert select_opportunities([_waiting()], today="2026-08-27", include_approaching=False) == []
