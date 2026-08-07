"""Chatbot context builder — folds the dashboard numbers into a compact prompt snapshot."""
from __future__ import annotations

from equity_scout.chat import (
    GLOSSARY,
    REFUSAL_ANSWER,
    SYSTEM_PROMPT,
    build_dashboard_context,
)


def test_context_includes_key_numbers_from_each_section() -> None:
    strategies = [
        {
            "name": "60/40",
            "metrics": {"sharpe": 0.6, "cagr": 0.07, "max_drawdown": -0.30},
            "current_weights": {"SPY": 0.6, "IEF": 0.4},
        }
    ]
    ml = {"trained": True, "oos_hit_rate": 0.64, "n_bets": 140, "avg_exposure": 0.5}
    research = {
        "available": True,
        "n_trials": 1300,
        "champion": {"model": "elastic_net", "features": ["vol", "breadth"], "dsr": 0.99, "sharpe": 0.93},
        "pbo": {"pbo": 0.69},
    }
    forward = [{"strategy_name": "60/40", "total_return": -0.001, "benchmark_return": 0.0, "n_points": 1}]
    screener = {"Ausgewogen": [{"ticker": "AAPL", "name": "Apple", "region": "US", "composite": 88}]}

    ctx = build_dashboard_context(
        strategies=strategies, ml=ml, research=research, forward=forward, screener=screener
    )

    assert "60/40" in ctx
    assert "0.60" in ctx  # benchmark Sharpe
    assert "SPY 60%" in ctx  # current allocation is in the context now
    assert "64.0%" in ctx  # OOS hit rate
    assert "1300" in ctx  # trials
    assert "69.0%" in ctx  # PBO
    assert "FORWARD" in ctx
    assert "AAPL" in ctx and "Score 88" in ctx  # screener single-stock picks


def test_context_empty_when_no_data() -> None:
    assert build_dashboard_context(strategies=[], ml=None, research=None, forward=[]) == "Keine Daten verfügbar."


def test_refusal_answer_is_a_hard_no_without_numbers() -> None:
    assert "keine Anlageberatung" in REFUSAL_ANSWER
    assert "kaufen" in REFUSAL_ANSWER.lower()
    # Der feste Satz darf keine Platzhalter tragen, die je Frage variieren müssten.
    assert "{" not in REFUSAL_ANSWER


def test_system_prompt_forbids_guessing_and_advice() -> None:
    for required in (
        "nicht im Datenbestand",      # fehlende Daten benennen statt raten
        "keine Anlageberatung",
        "keine Kursprognosen",
        "erfinde",                     # "erfinde nichts"
    ):
        assert required in SYSTEM_PROMPT, required


def test_glossary_defines_the_house_terms() -> None:
    for term in ("Einstiegszone", "Einstiegs-Score", "Potenzial", "Signal-Filter"):
        assert term in GLOSSARY, term
