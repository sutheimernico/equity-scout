"""Drift scan for voices' generic-word exposure (v13 Q4): exposed-word computation."""
from __future__ import annotations

from scripts.scan_generic_words import exposed_words


def test_exposed_words_flags_new_generic_candidates_and_respects_the_gate():
    universe = [
        ("PACB", "Pacific Biosciences of California, Inc."),  # PACIFIC: already blocked
        ("ZEN", "Zenith Corp"),  # fresh single-token name -> exposed, needs review
        ("MU", "Micron Technology, Inc."),  # one-owner first word -> exposed (legit)
        ("AAL", "American Airlines Group Inc."),  # two owners AND blocked
        ("AXP", "American Express Company"),
    ]
    words = exposed_words(universe)
    assert "ZENITH" in words  # the synthetic new word the scan must surface
    assert "MICRON" in words
    assert "PACIFIC" not in words  # blocked by _GENERIC_FIRST_WORDS
    assert "AMERICAN" not in words  # blocked, and not one-owner either


def test_exposed_words_ignores_shared_first_words_and_short_ones():
    universe = [
        ("AA", "Alpha Airlines Inc."),
        ("AB", "Alpha Beverages Inc."),  # ALPHA has two owners -> not trusted, not exposed
        ("ZDS", "Zip Delivery Systems Inc."),  # 3-char first word: channel never trusts it
    ]
    words = exposed_words(universe)
    assert "ALPHA" not in words
    assert "ZIP" not in words
