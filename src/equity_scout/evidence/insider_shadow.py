"""Insider-cluster SHADOW lane (v15 P2): pre-registered predictions, never capital.

WHY A SHADOW LANE AND NOT A TRADING LANE. The P2a backfill measured 27,681 insider-
cluster events 2006->2026 (docs/research/history-study-report.json, post-fix rerun
2026-08-07). Insider clusters were the ONLY evidence class that survived full coverage:
r_3m +2.55% +/- 0.67pp on 13,694 measurements, r_1w +2.08% +/- 0.97pp. The same table
measured the reasons NOT to trade it yet:

  * out of sample (t0 > 2021-12-31) the r_3m cell shrinks from +3.13% to +0.77% +/-
    0.79pp on 3,355 events — below one stderr, i.e. the pooled effect is fit-period
    carried;
  * the validate-window hit rate at r_3m is 42.9% and decays 51.1 -> 32.9 from r_1w to
    r_12m, so a positive mean sits on a sub-coin-flip breadth (outliers, not edge);
  * the report gated 162 cell-horizons of which ~81 agreeing directions are expected
    from noise alone;
  * 13,837 of the 27,681 cluster tickers are no longer tradable at all (insider
    mortality is real), so every number above is an upper bound.

A positive mean on a sub-50% hit rate is exactly the shape that looks like an edge in a
study and feels like a losing streak in a depot.

So this module registers predictions and nothing else. No capital, no broker order, no
position, no promotion rule: promotion needs >= 60 days of forward shadow track and is
Nico's decision, deliberately not implemented anywhere in this code.

DETECTION USES THE LIVE PATH. Fresh Form 4 filings arrive through evidence/form4.py
(scripts/run_evidence.py -> evidence_events) and the cluster rule is
aggregate.MIN_INSIDERS (>= 3 distinct insiders), the same constant the live evidence
alert applies to the same rows. The P2a backfill collectors (evidence/backfill_form4.py,
SEC quarterly bulk ZIPs) are NOT used here: they measured the prior, this lane acts on
fresh filings. The universe is therefore whatever the live collector scans (the current
watchlist, form4.py's documented scope) — a coverage limit that is reported on the
status surface, not a bug.
"""
from __future__ import annotations

from dataclasses import dataclass

from equity_scout.evidence.aggregate import MIN_INSIDERS
from equity_scout.evidence.base import (
    SOURCE_INSIDER,
    SOURCE_INSIDER_SHADOW,
    EvidenceEvent,
)

# Pre-registered before the first prediction and frozen: 63 trading days = the study's
# r_3m cell (+2.55% +/- 0.67pp, ~3.8 stderr), the strongest surviving cell. ONE horizon
# on purpose — r_1w (+2.08% +/- 0.97pp, ~2.1 stderr) is deliberately NOT registered as a
# second hypothesis: two horizons per event double the tests for one signal and halve
# what a pass means. A second horizon may be added AFTER this one has a verdict, as a
# new registration with its own start date, never retro-fitted onto this track.
SHADOW_HORIZON_TRADING_DAYS = 63

# Trailing window of collected Form-4 events a cluster may span. 30 days mirrors BOTH
# the live alert window (scripts/run_notify.EVIDENCE_WINDOW_DAYS) and the collector's own
# filing bound (form4.DEFAULT_MAX_FILING_AGE_DAYS): a cluster the alert path could not
# see must not appear here either.
DEFAULT_WINDOW_DAYS = 30

# The prior this lane exists to test, verbatim from the P2a rerun table. Carried onto
# every surface so the forward track is never read without it.
STUDY_PRIOR = {
    "source": "docs/research/history-study-report.json (P2a post-fix rerun, 2026-08-07)",
    "cell": "insider clusters, r_3m (63 Handelstage)",
    "n_measured": 13694,
    "mean_relative_return": 0.0255,
    "stderr": 0.0067,
    "hit_rate_all": 0.4698,
    "hit_rate_fit": 0.483,
    "hit_rate_validate": 0.4292,
    # Out of sample (t0 > 2021-12-31) the same cell measures +0.77% +/- 0.79pp on 3,355
    # events — the pooled +2.55% is carried by the fit period and does not survive one
    # stderr in the validate window. This single pair of numbers is the reason the lane
    # is a shadow track and not a depot sleeve.
    "validate_mean_relative_return": 0.0077,
    "validate_stderr": 0.0079,
    "validate_n": 3355,
    "caveat": (
        "Positiver Mittelwert bei einer Trefferquote UNTER 50 % — der Effekt wird von "
        "wenigen Ausreißern getragen, nicht von der Breite. Out of Sample (ab 2022) "
        "schrumpft er von +3,13 % auf +0,77 % ± 0,79pp, bleibt also unter einer "
        "Standardabweichung. Die Trefferquote im Validierungsfenster fällt zusätzlich mit "
        "dem Horizont (51,1 % auf 1W → 32,9 % auf 12M). Dazu Survivorship: 13.837 der "
        "27.681 Cluster-Ticker sind nicht mehr handelbar, die gemessenen Werte sind eine "
        "Obergrenze."
    ),
}


@dataclass(frozen=True)
class ShadowCluster:
    """One ticker's insider cluster as it is visible TODAY: >= MIN_INSIDERS distinct
    named buyers among the Form-4 events inside the trailing window."""

    ticker: str
    insiders: tuple[str, ...]
    t0: str  # latest filing date in the cluster — only then was the full cluster knowable
    source_event_keys: tuple[str, ...]


def _insider_name(event: dict) -> str | None:
    return (event.get("details") or {}).get("insider")


def _filing_date(event: dict) -> str:
    return (event.get("details") or {}).get("filing_date") or event["event_date"]


def detect_clusters(
    events_by_ticker: dict[str, list[dict]], *, min_insiders: int = MIN_INSIDERS
) -> list[ShadowCluster]:
    """Tickers whose collected Form-4 events carry >= min_insiders DISTINCT named buyers.

    Same rule and same rows as aggregate.select_evidence_alerts' insider reason line
    (distinct `details["insider"]`, None dropped) — mirrored rather than shared because
    the two answer different questions: the alert asks "is this worth a look", this asks
    "what exactly am I measuring from when". A parser fallback name ("unbekannt") counts
    as one buyer here exactly as it does there; diverging would make the shadow track
    measure a different population than the alerts show.
    """
    clusters: list[ShadowCluster] = []
    for ticker, events in sorted(events_by_ticker.items()):
        insider_events = [e for e in events if e["source"] == SOURCE_INSIDER]
        names = sorted({_insider_name(e) for e in insider_events} - {None})
        if len(names) < min_insiders:
            continue
        clusters.append(
            ShadowCluster(
                ticker=ticker.upper(),
                insiders=tuple(names),
                t0=max(_filing_date(e) for e in insider_events),
                source_event_keys=tuple(sorted(e["event_key"] for e in insider_events)),
            )
        )
    return clusters


def shadow_events(
    clusters: list[ShadowCluster], *, skip_tickers: frozenset[str] = frozenset()
) -> list[EvidenceEvent]:
    """One prediction event per cluster, minus tickers that already carry an OPEN shadow
    prediction.

    The skip is what keeps the sample honest: re-detecting the same cluster tomorrow, or
    the same cluster grown by a fourth buyer, is the SAME signal on the same ticker over
    an overlapping window — two rows whose outcomes are almost perfectly correlated would
    inflate n without adding information. The event_key still encodes t0 and cluster size,
    so a genuinely new cluster on that ticker AFTER the open one resolves is a new row.
    """
    events: list[EvidenceEvent] = []
    for cluster in clusters:
        if cluster.ticker in skip_tickers:
            continue
        events.append(
            EvidenceEvent(
                source=SOURCE_INSIDER_SHADOW,
                ticker=cluster.ticker,
                event_key=f"{cluster.t0}-cluster{len(cluster.insiders)}",
                event_date=cluster.t0,
                details={
                    "insiders": list(cluster.insiders),
                    "n_insiders": len(cluster.insiders),
                    "horizon_trading_days": SHADOW_HORIZON_TRADING_DAYS,
                    "source_event_keys": list(cluster.source_event_keys),
                    "shadow_only": True,
                },
            )
        )
    return events
