"""Pure tests for insights.py — no network, no DB, no Ollama."""
from __future__ import annotations

from datetime import datetime

import pytest

from equity_scout.insights import (
    BUSINESS_QUESTION,
    NEWS_QUESTION,
    clean_llm_text,
    downsample_closes,
    fact_context,
    news_context,
)


# --- clean_llm_text ---------------------------------------------------------------

def test_clean_strips_a_chatty_preamble():
    # qwen2.5 likes to announce what it is about to do; the card has no room for it.
    raw = "Hier ist die Zusammenfassung: Das Unternehmen baut Speicherchips."
    assert clean_llm_text(raw) == "Das Unternehmen baut Speicherchips."


def test_clean_strips_markdown_and_bullets():
    raw = "**Zusammenfassung:**\n- Das Unternehmen baut Speicherchips.\n"
    assert clean_llm_text(raw) == "Das Unternehmen baut Speicherchips."


def test_clean_keeps_a_plain_sentence_untouched():
    raw = "Micron Technology stellt DRAM- und NAND-Speicher her."
    assert clean_llm_text(raw) == raw


def test_clean_truncates_at_a_sentence_boundary():
    raw = "Satz eins ist kurz. Satz zwei ist auch kurz. Satz drei fällt weg."
    # max_chars lands inside sentence three -> cut after sentence two, never mid-word.
    assert clean_llm_text(raw, max_chars=45) == "Satz eins ist kurz. Satz zwei ist auch kurz."


def test_clean_falls_back_to_a_hard_cut_when_one_sentence_is_too_long():
    raw = "Ein einziger sehr langer Satz ohne jeden Punkt darin"
    out = clean_llm_text(raw, max_chars=20)
    assert len(out) <= 21  # 20 + the ellipsis character
    assert out.endswith("…")


def test_clean_returns_none_for_empty_or_whitespace():
    assert clean_llm_text("") is None
    assert clean_llm_text("   \n  ") is None


# --- prompts ---------------------------------------------------------------------

def test_business_question_forbids_forecasts():
    # Same guardrail as pitch.py: the LLM interprets, it never predicts.
    assert "Prognose" in BUSINESS_QUESTION
    assert "Kursziel" in BUSINESS_QUESTION


def test_news_question_demands_a_no_news_answer():
    # An LLM handed zero headlines will otherwise invent some.
    assert "keine" in NEWS_QUESTION.lower()


def test_fact_context_carries_the_numbers_and_no_verdict():
    ctx = fact_context(
        ticker="MU", name="Micron Technology", sector="Technology",
        industry="Semiconductors", price=893.19, currency="USD",
    )
    assert "Micron Technology" in ctx
    assert "MU" in ctx
    assert "Semiconductors" in ctx
    assert "893" in ctx
    # No entry advice may leak into the business description's context.
    assert "Einstieg" not in ctx


def test_news_context_numbers_the_headlines():
    ctx = news_context(["Micron raises guidance", "Analysts lift target"])
    assert "1. Micron raises guidance" in ctx
    assert "2. Analysts lift target" in ctx


def test_news_context_is_empty_string_without_headlines():
    assert news_context([]) == ""


# --- downsample_closes -----------------------------------------------------------

def _series(n: int) -> tuple[list[datetime], list[float]]:
    dates = [datetime(2025, 1, 1) for _ in range(n)]
    return dates, [float(i) for i in range(n)]


def test_downsample_keeps_first_and_last_exactly():
    # The card computes the 1-year return from these endpoints — they must be the real ones.
    dates, closes = _series(250)
    out = downsample_closes(dates, closes, points=60)
    assert out["closes"][0] == closes[0]
    assert out["closes"][-1] == closes[-1]


def test_downsample_hits_the_requested_length():
    dates, closes = _series(250)
    assert len(downsample_closes(dates, closes, points=60)["closes"]) == 60


def test_downsample_passes_a_short_series_through_unchanged():
    dates, closes = _series(12)
    out = downsample_closes(dates, closes, points=60)
    assert out["closes"] == closes


def test_downsample_records_the_first_and_last_date():
    dates = [datetime(2025, 8, 5), datetime(2026, 8, 5)]
    out = downsample_closes(dates, [10.0, 12.0], points=60)
    assert out["first_date"] == "2025-08-05"
    assert out["last_date"] == "2026-08-05"


def test_downsample_rejects_an_empty_series():
    with pytest.raises(ValueError):
        downsample_closes([], [], points=60)


# --- NaN closes (live defect 2026-08-05) -----------------------------------------

def test_downsample_drops_non_finite_closes():
    """yfinance returns NaN for a day it has no close for (measured live on 9064.T and
    9022.T: the LAST point of the year was NaN). json.dumps happily writes `NaN`, which is
    invalid JSON, and only FastAPI's strict encoder then fails the whole /api/briefs
    response with a 500. A missing day is not a value — it is dropped."""
    dates = [datetime(2025, 8, 5), datetime(2025, 8, 6), datetime(2026, 8, 5)]
    out = downsample_closes(dates, [10.0, float("nan"), 12.0], points=60)
    assert out["closes"] == [10.0, 12.0]


def test_downsample_keeps_the_last_FINITE_close_as_the_endpoint():
    """The endpoint guarantee must survive the drop: with a trailing NaN the last real
    close becomes the endpoint, so the rendered 1-year return stays truthful."""
    dates = [datetime(2025, 8, 5), datetime(2026, 8, 4), datetime(2026, 8, 5)]
    out = downsample_closes(dates, [10.0, 12.0, float("nan")], points=60)
    assert out["closes"][-1] == 12.0


def test_downsample_rejects_a_series_that_is_all_nan():
    dates = [datetime(2025, 8, 5), datetime(2026, 8, 5)]
    with pytest.raises(ValueError):
        downsample_closes(dates, [float("nan"), float("inf")], points=60)


# --- dates for the chart's month axis (2026-08-05, Nicos Achsen-Wunsch) -----------

def test_downsample_returns_the_date_of_every_kept_point():
    """The chart's month ticks must sit on real trading days. Interpolating them from
    first/last would drift, because trading days are not evenly spaced."""
    dates = [datetime(2025, 8, 5), datetime(2025, 11, 5), datetime(2026, 8, 5)]
    out = downsample_closes(dates, [10.0, 11.0, 12.0], points=60)
    assert out["dates"] == ["2025-08-05", "2025-11-05", "2026-08-05"]


def test_downsample_keeps_dates_aligned_with_closes_when_sampling():
    dates = [datetime(2025, 1, 1 + (i % 28)) for i in range(250)]
    closes = [float(i) for i in range(250)]
    out = downsample_closes(dates, closes, points=60)
    assert len(out["dates"]) == len(out["closes"]) == 60
    # Sampling picks index pairs, so the first/last date must be the real endpoints.
    assert out["dates"][0] == dates[0].date().isoformat()
    assert out["dates"][-1] == dates[-1].date().isoformat()


def test_downsample_drops_the_date_of_a_dropped_nan_close():
    """A dropped NaN must take its date with it, or every later point shifts by one."""
    dates = [datetime(2025, 8, 5), datetime(2025, 8, 6), datetime(2026, 8, 5)]
    out = downsample_closes(dates, [10.0, float("nan"), 12.0], points=60)
    assert out["closes"] == [10.0, 12.0]
    assert out["dates"] == ["2025-08-05", "2026-08-05"]
