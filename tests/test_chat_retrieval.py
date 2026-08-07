"""tests/test_chat_retrieval.py — deterministic retrieval in front of the LLM."""
from __future__ import annotations

from equity_scout.chat_retrieval import is_advice_question


def test_advice_questions_are_detected():
    for q in [
        "Soll ich Micron kaufen?",
        "soll ich jetzt bei ITC einsteigen",
        "Würdest du Yamato verkaufen?",
        "Lohnt es sich, Petrobras zu kaufen?",
        "Was soll ich kaufen?",
    ]:
        assert is_advice_question(q), q


def test_data_questions_are_not_advice():
    for q in [
        "Was macht Micron und warum ist die Aktie im Radar?",
        "Wie steht mein Auto-Depot im Vergleich zum Markt?",
        "Was bedeutet die Einstiegszone?",
        "Wer hat zuletzt Intel gekauft?",  # Frage über KÄUFE Dritter, kein Rat
    ]:
        assert not is_advice_question(q), q
