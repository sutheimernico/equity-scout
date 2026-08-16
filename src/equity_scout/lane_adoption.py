"""Should the search's winner replace the running rules? (T12)

Nico approved automatic adoption on 2026-08-16 — no human has to confirm a change. That makes
the hurdle the only thing standing between a lucky grid cell and the live lane, so it is built
from the three lessons this project paid for:

1. **Compare on ONE sample.** The challenger and the incumbent are simulated over the SAME
   events and compared PAIRWISE. On 2026-08-11 an entry champion held its title for five weeks
   because a stored metric from 220 rows was compared against fresh metrics from 3 000 — two
   incomparable numbers that looked comparable.
2. **Count the trials.** Forty combinations against one dataset always produce a winner. The
   bar rises with the number of cells searched (Bonferroni), the same separation v14 introduced
   for the rule strategies.
3. **Change rarely.** One adoption per lane and calendar month (`lane_params.changed_this_month`).
   A rule that changes nightly never accumulates enough trades under any one version to be
   judged — the search would be measuring its own churn.

A verdict always carries its reason, including the negative case: "not adopted" has to be as
readable afterwards as "adopted", or nobody can tell a working brake from a broken search.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from equity_scout.exits import ExitRules
from equity_scout.lane_tuning import simulate_event

# Two-sided 5 % before the multiple-testing correction. Kept as a constant rather than a
# parameter: a caller that may lower the bar is a bar that will be lowered.
BASE_CRITICAL_T = 1.96


@dataclass(frozen=True)
class AdoptionVerdict:
    adopt: bool
    reason: str
    n_pairs: int
    mean_diff: float
    paired_t: float | None
    hurdle_t: float


def _returns(closes_by_ticker: dict[str, pd.Series],
             events: list[tuple[str, pd.Timestamp]],
             rules: ExitRules) -> dict[tuple[str, str], float]:
    """Per-event return under one rule set, keyed so both runs can be paired exactly."""
    out: dict[tuple[str, str], float] = {}
    for ticker, day in events:
        closes = closes_by_ticker.get(ticker)
        if closes is None or closes.empty:
            continue
        pos = closes.index.searchsorted(day)
        if pos + 1 >= len(closes):
            continue
        ret, _ = simulate_event(closes, pos + 1, rules)
        out[(ticker, str(day)[:10])] = ret
    return out


def critical_t(n_trials: int) -> float:
    """Bonferroni-style bar: the more cells searched, the higher the winner must clear.

    Approximated by scaling the two-sided 5 % z-value with sqrt(2 ln n) — exact quantiles would
    need scipy at import time for a number whose job is to be conservative anyway.
    """
    if n_trials <= 1:
        return BASE_CRITICAL_T
    import math

    return max(BASE_CRITICAL_T, math.sqrt(2 * math.log(n_trials)) + 0.6)


def evaluate_adoption(
    closes_by_ticker: dict[str, pd.Series],
    events: list[tuple[str, pd.Timestamp]],
    *,
    challenger: ExitRules,
    incumbent: ExitRules,
    n_trials: int,
    already_changed_this_month: bool = False,
) -> AdoptionVerdict:
    """The full gate. Returns a verdict with its reasoning, never a bare boolean."""
    hurdle = critical_t(n_trials)
    if challenger == incumbent:
        return AdoptionVerdict(False, "Herausforderer ist die laufende Einstellung.", 0, 0.0,
                               None, hurdle)
    if already_changed_this_month:
        return AdoptionVerdict(False, "Diesen Monat wurde bereits angepasst — höchstens eine "
                               "Änderung je Lane und Monat.", 0, 0.0, None, hurdle)

    a = _returns(closes_by_ticker, events, challenger)
    b = _returns(closes_by_ticker, events, incumbent)
    shared = sorted(set(a) & set(b))
    diffs = [a[k] - b[k] for k in shared]
    n = len(diffs)
    if n < 30:
        return AdoptionVerdict(False, f"Zu wenige gemeinsame Ereignisse ({n} < 30).", n, 0.0,
                               None, hurdle)

    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    if var <= 0:
        # Two distinguishable cases that must not share a message: either the rules genuinely
        # tie, or every event produced the SAME difference — which means the sample carries no
        # information about the spread, not that the challenger is safe. Both refuse; only the
        # second one is a warning about the data.
        detail = ("Beide Regeln liefern identische Ergebnisse."
                  if abs(mean) < 1e-12
                  else f"Alle {n} Ereignisse zeigen exakt denselben Unterschied "
                       f"({mean * 100:+.2f} pp) — keine Streuung, also kein Test möglich.")
        return AdoptionVerdict(False, detail, n, mean, None, hurdle)
    t = mean / ((var / n) ** 0.5)
    if t <= hurdle:
        return AdoptionVerdict(
            False,
            f"Vorsprung nicht belastbar: t = {t:.2f} gegen Hürde {hurdle:.2f} "
            f"bei {n_trials} geprüften Kombinationen.",
            n, mean, t, hurdle,
        )
    return AdoptionVerdict(
        True,
        f"Übernommen: t = {t:.2f} über Hürde {hurdle:.2f}, Vorsprung "
        f"{mean * 100:+.2f} pp je Trade über {n} gemeinsame Ereignisse.",
        n, mean, t, hurdle,
    )
