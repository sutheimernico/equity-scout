"""Point-in-time fundamentals from SEC EDGAR company facts — what was PUBLIC on a given day.

`fscore.py` answers "what is this company's F-Score now" and is right to key on fiscal year: it
serves a live annotation. Training on fundamentals asks a different question — "what could a model
have known on 2014-03-31" — and answering it with fiscal years builds look-ahead straight into the
sample. Measured on AAPL (2026-08-12): a 10-K's own fiscal year closes 34 days before the filing
lands, so a fiscal-year key hands the model a month of the future, every year, for free.

Two traps live in this payload, and both are silent:

1. **`fy` is the FILING's fiscal year, not the data's.** The FY2024 filing carries entries with
   `end` 2022-09-24, 2023-09-30 AND 2024-09-28 — all stamped `fy: 2024`, because a 10-K restates
   prior years as comparatives. Keying a time series on `fy` therefore mislabels comparatives as
   current-year figures. This module keys on `end` (the period the number describes) and uses
   `filed` (the day it became public) purely as the visibility gate.

2. **Restatements share an `end`.** The same period can appear in several filings with different
   values. As of any given day the honest answer is the LATEST filing available by then, so
   entries are sorted by `filed` and the last one visible wins — never the newest one overall,
   which is exactly the look-ahead being avoided.

Pure logic: the network lives in the caller, the payload comes in as a dict. That keeps the whole
point-in-time contract offline-testable, which matters because a look-ahead bug does not crash —
it just quietly produces a good backtest.
"""
from __future__ import annotations

# 10-K only, matching fscore.py: annual audited figures, no quarterly mixing.
_ANNUAL_FORM_PREFIX = "10-K"


def visible_annual_series(
    payload: dict,
    tags: list[str],
    *,
    as_of: str,
    unit: str = "USD",
    taxonomy: str = "us-gaap",
) -> dict[str, float]:
    """`{period_end: value}` for every 10-K figure FILED on or before `as_of`.

    Keyed by period end (ISO date string), not by fiscal year — see the module docstring for why
    `fy` cannot carry a time series. `as_of` is an ISO date; an entry filed exactly on `as_of`
    counts as visible, because a filing is public the day it lands.

    Tag candidates are tried in order and the first one yielding at least two visible periods
    wins, mirroring `fscore.annual_series` so the two paths agree on which concept they measure.
    Returns {} when no candidate qualifies — an honest "not knowable then", never a guess.
    """
    for tag in tags:
        entries = (
            payload.get("facts", {}).get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit)
            or []
        )
        visible = [
            entry
            for entry in entries
            if str(entry.get("form", "")).startswith(_ANNUAL_FORM_PREFIX)
            and entry.get("val") is not None
            and entry.get("end")
            and entry.get("filed")
            and str(entry["filed"]) <= as_of
        ]
        if not visible:
            continue
        # Sort by filing date so that, per period, the last write is the newest filing that was
        # available by `as_of` — a later restatement must not leak backwards.
        visible.sort(key=lambda entry: str(entry["filed"]))
        series: dict[str, float] = {}
        for entry in visible:
            series[str(entry["end"])] = float(entry["val"])
        if len(series) >= 2:
            return dict(sorted(series.items()))
    return {}


def latest_two_periods(series: dict[str, float]) -> tuple[tuple[str, float], tuple[str, float]] | None:
    """The two most recent periods of a `visible_annual_series`, oldest first, or None.

    Piotroski compares a year against its predecessor, so the pair is the unit of work. Returns
    None below two periods rather than padding — a comparison against a missing year is not a
    weaker signal, it is no signal.
    """
    if len(series) < 2:
        return None
    items = sorted(series.items())
    return items[-2], items[-1]


def filing_lag_days(payload: dict, tag: str, *, unit: str = "USD", taxonomy: str = "us-gaap") -> list[int]:
    """Days between period end and filing date for each 10-K entry.

    Read the MINIMUM, not the mean. Because a 10-K restates prior years, most entries are
    comparatives whose period closed one or two years before the filing: on real AAPL data the
    median lag is 396 days while the current-period lag is 30. Only the minimum describes the
    look-ahead a fiscal-year key would introduce — the mean describes the shape of the payload.

    Diagnostic, so a backfill can state the risk it avoids instead of asserting it. Entries whose
    dates do not parse are skipped, not guessed.
    """
    from datetime import date

    lags: list[int] = []
    entries = (
        payload.get("facts", {}).get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit) or []
    )
    for entry in entries:
        if not str(entry.get("form", "")).startswith(_ANNUAL_FORM_PREFIX):
            continue
        try:
            end = date.fromisoformat(str(entry["end"]))
            filed = date.fromisoformat(str(entry["filed"]))
        except (KeyError, TypeError, ValueError):
            continue
        lags.append((filed - end).days)
    return lags
