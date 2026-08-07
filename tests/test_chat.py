"""Chatbot context builder — folds the dashboard numbers into a compact prompt snapshot."""
from __future__ import annotations

import pytest

from equity_scout.chat import (
    glossary_for,
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


def test_glossary_explains_the_key_figures_and_filings() -> None:
    for term in ("KGV", "Eigenkapitalrendite", "Nettomarge", "13F", "Form 4",
                 "Meldeverzug", "F-Score", "52-Wochen-Hoch", "Perzentil"):
        assert term in GLOSSARY, term
    # Jede Kennzahl kommt mit ihrer Grenze — sonst liest das Modell sie als Kaufgrund.
    assert "kein Kaufgrund" in GLOSSARY


def test_system_prompt_rules_comparisons_without_a_winner() -> None:
    assert "Kennzahl für Kennzahl" in SYSTEM_PROMPT
    assert "Sieger" in SYSTEM_PROMPT


def test_ask_ollama_keeps_the_model_warm_and_caps_length(monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"message": {"content": "ok"}}

    def fake_post(url, json=None, timeout=None):  # noqa: ANN001, ANN202
        captured.update(json)
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    from equity_scout.chat import ask_ollama

    ask_ollama("Frage?", "Kontext")
    assert captured["keep_alive"] == "24h"
    assert captured["options"]["num_predict"] == 400


def test_stream_ollama_yields_content_chunks(monkeypatch) -> None:
    import json as jsonlib

    class _StreamResp:
        def raise_for_status(self) -> None:
            pass

        def iter_lines(self):  # noqa: ANN202
            yield jsonlib.dumps({"message": {"content": "Hal"}, "done": False})
            yield jsonlib.dumps({"message": {"content": "lo"}, "done": True})

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *a) -> bool:  # noqa: ANN002
            return False

    import httpx

    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _StreamResp())
    from equity_scout.chat import stream_ollama

    assert list(stream_ollama("F?", "K")) == ["Hal", "lo"]


def test_stream_ollama_reports_an_unreachable_server(monkeypatch) -> None:
    import httpx

    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "stream", boom)
    from equity_scout.chat import ChatError, stream_ollama

    with pytest.raises(ChatError):
        list(stream_ollama("F?", "K"))


def test_warm_model_never_raises_when_ollama_is_down(monkeypatch) -> None:
    import httpx

    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "post", boom)
    from equity_scout.chat import warm_model

    assert warm_model() is False


def test_warm_model_requests_a_single_token(monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

    def fake_post(url, json=None, timeout=None):  # noqa: ANN001, ANN202
        captured.update(json)
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    from equity_scout.chat import warm_model

    assert warm_model() is True
    assert captured["options"]["num_predict"] == 1
    assert captured["keep_alive"] == "24h"


def test_ask_ollama_names_a_timeout_as_a_timeout(monkeypatch) -> None:
    import httpx

    def slow(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise httpx.ReadTimeout("too slow")

    monkeypatch.setattr(httpx, "post", slow)
    from equity_scout.chat import ChatError, ask_ollama

    with pytest.raises(ChatError, match="Kaltstart"):
        ask_ollama("Frage?", "Kontext")


def test_glossary_for_trims_sections_the_question_cannot_need() -> None:
    depot_only = glossary_for(["depots"], has_dossier=False)
    assert "Einstiegszone" in depot_only          # Hausbegriffe immer
    assert "KGV" not in depot_only                 # Kennzahlen nur bei Bedarf
    assert "13F" not in depot_only

    with_stock = glossary_for(["kennzahlen"], has_dossier=True)
    assert "KGV" in with_stock and "13F" in with_stock


def test_ask_ollama_sets_the_context_window_explicitly(monkeypatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"message": {"content": "ok"}}

    import httpx

    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: (
        captured.update(json), _Resp())[1])
    from equity_scout.chat import NUM_CTX, ask_ollama

    ask_ollama("Frage?", "Kontext")
    # Ollamas Default (4096) würde bei einem Vier-Aktien-Vergleich still abschneiden —
    # und zwar am Anfang, wo der System-Prompt mit den Guardrails steht.
    assert captured["options"]["num_ctx"] == NUM_CTX >= 8192
