"""The message that tells Nico whether the session-lane rewrite is unblocked."""
from __future__ import annotations

import scripts.notify_alpaca_verify as notifier

SAMPLE = """Alpaca-Paper-Verifikation — 2026-08-06 18:00:00Z

[1/4] Paper-Credentials
  OK  Konto PA3SIKMAPF0N status=ACTIVE cash=100000 USD

[2/4] IEX-Bars (feed=iex) — der entscheidende Test

  15-Minuten-Bars — Basis der Opening Range, Frische unkritisch
    OK  MSFT  neuester Bar 17:45:00Z  Alter   15.2 min  (21 Bars)

  1-Minuten-Bars — Basis des Ausbruch-Triggers, hier entscheidet sich alles
    OK  MSFT  neuester Bar 17:59:00Z  Alter    1.2 min  (310 Bars, Dichte  100% OK)
    OK  AAPL  neuester Bar 17:59:00Z  Alter    1.2 min  (311 Bars, Dichte  100% OK)

  HINWEIS irgendwas

Alle geprueften Annahmen halten.
"""


def test_it_quotes_the_one_minute_ages_not_the_fifteen_minute_ones() -> None:
    """The 1-minute ages are the measurement; the 15-minute block is context. Quoting the
    wrong block would show numbers that were never in question."""
    lines = notifier.freshness_lines(SAMPLE)
    assert len(lines) == 2
    assert all("Dichte" in line for line in lines)
    assert not any("(21 Bars)" in line for line in lines)


def test_a_pass_says_the_rewrite_is_unblocked() -> None:
    message = notifier.build_message(passed=True, output=SAMPLE)
    assert "bestanden" in message
    assert "Tasks 6" in message
    assert "1.2 min" in message


def test_a_failure_names_the_fallback_instead_of_just_reporting_doom() -> None:
    """A red message that does not say what happens next invites a panicked 23:00 debug
    session. The plan already has an answer — say it in the message."""
    message = notifier.build_message(passed=False, output=SAMPLE)
    assert "fehlgeschlagen" in message
    assert "Auflösung" in message


def test_an_unrecognised_format_still_produces_a_message() -> None:
    """If the check's output format drifts, the notification must degrade to "here are the
    last lines", never to silence — silence is indistinguishable from "never ran"."""
    message = notifier.build_message(passed=False, output="völlig anderer Text\nzweite Zeile")
    assert "zweite Zeile" in message


def test_html_special_characters_in_the_output_are_escaped() -> None:
    message = notifier.build_message(passed=False, output="Fehler: a < b & c > d")
    assert "&lt; b &amp; c &gt;" in message
