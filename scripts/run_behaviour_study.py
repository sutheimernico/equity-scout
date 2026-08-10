"""W0 — measure every behavioural indicator candidate against OUR OWN history.

Nico's instruction of 2026-08-10: no behavioural indicator goes into the traffic light, the
protection chain or a strategy before it has been measured here. Literature is a hypothesis, not
a result — this project already watched a well-documented US single-stock effect (the skip month)
lose on its own 21 index ETFs.

What this runs: every candidate from `docs/research/2026-08-11-behavioural-indicator-landscape.md`
that is reachable without a paid source, against three forward targets on SPY.

    uv run python scripts/run_behaviour_study.py            # uses the local snapshots
    uv run python scripts/run_behaviour_study.py --refresh  # re-fetches the VIX term structure

The honest-methodology decisions all live in `behaviour_study.py`; the two that matter for
reading the output:

* **Significance is decided on non-overlapping windows only.** Daily observations of a 63-day
  forward return share 62 of 63 days with their neighbour; treating them as independent inflates
  every t-statistic by roughly sqrt(horizon). So the n that carries a verdict is small — 30-odd
  windows at the long horizon on the 2018+ volume panel — and the report prints it next to every
  number so nobody reads 2000 rows of evidence into 30 observations.
* **Bonferroni across the whole grid.** This script runs dozens of tests at once; at alpha 0.05
  a couple of them look significant from noise alone. The corrected level is what the verdict
  uses, and the uncorrected p-value is printed alongside so the gap stays visible.

Volume signals are computed by calling the PRODUCTION `read_volume` once per day in a loop rather
than a vectorised reimplementation. It is slower and it is the point: a study that measures a
lookalike of the production signal answers a question nobody asked.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from equity_scout.behaviour_study import (  # noqa: E402
    SignalStudy,
    align,
    forward_drawdown,
    forward_return,
    forward_volatility,
    independent_subsample,
    minimum_detectable_effect,
    offset_robustness,
    residualise,
    study_signal,
)
from equity_scout.significance import bonferroni_alpha  # noqa: E402
from equity_scout.volume_signals import BEHAVIOUR_SLEEVE, read_volume  # noqa: E402

VIX_TICKERS = ("^VIX", "^VIX3M", "^VIX9D")
VIX_SNAPSHOT = "data/prices/vix_term.csv"
ETF_VOLUME = "data/prices/etf_volume.csv"
BOTS_PANEL = "data/prices/ml_bots_panel.csv"
RESULT_JSON = "data/behaviour_study.json"
# The production price panel (`etf_panel.csv`) starts in June 2018 because XLC was listed then
# and the panel drops rows where any column is missing — correct for a backtest that trades all
# 21 tickers, ruinous for a study, since it throws away eleven years the volume snapshot has.
# So the study keeps its own COLUMN-WISE price snapshot of the behaviour sleeve: each ticker
# carries its own history, and the production panel is left untouched.
SLEEVE_CLOSES = "data/prices/behaviour_sleeve_closes.csv"

# Horizons in trading days: ~1 week, ~1 month, ~3 months. Nothing shorter, because the decision
# raster of this system is one day and a 1-day forward return is mostly microstructure noise.
RETURN_HORIZONS = (5, 21, 63)
RISK_HORIZONS = (21, 63)
SMA_WINDOW = 200
VOLUME_BASELINE = 20
# What the traffic light (`regime.py`) already carries. A new candidate has to beat these, not
# merely agree with them — two fear gauges correlating is not news, and building the second one
# costs a data source and a maintenance surface for information already on the screen.
BASELINE_SIGNALS = ("VIX-Level", "Marktbreite (% über 200d)")


def _read_panel(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame.sort_index()


def load_vix_term(*, refresh: bool = False) -> pd.DataFrame:
    """The VIX term structure, snapshotted like every other panel in this project.

    Kept in this script rather than in `data/etf_panel.py` on purpose: W0 is a gate, and adding a
    production loader for a signal that has not passed it yet is exactly the shortcut the gate
    exists to prevent. It moves into the package if and when a VIX signal earns its place.
    """
    if not refresh and os.path.exists(VIX_SNAPSHOT):
        return _read_panel(VIX_SNAPSHOT)
    import yfinance as yf

    data = yf.download(list(VIX_TICKERS), start="2005-01-01", auto_adjust=True, progress=False)
    closes = data["Close"][list(VIX_TICKERS)]
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    os.makedirs(os.path.dirname(VIX_SNAPSHOT) or ".", exist_ok=True)
    closes.to_csv(VIX_SNAPSHOT)
    return closes.sort_index()


def volume_signal_series(closes: pd.Series, volumes: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Daily (ratio, obv_trend) by calling the production `read_volume` once per day.

    Day i is treated as "today": its close and its volume are both known after the session, and
    the study's forward window starts at i+1 — so the reading is knowable at decision time.
    """
    joined = pd.DataFrame({"close": closes, "volume": volumes}).dropna().sort_index()
    ratios: list[float | None] = []
    obv: list[float | None] = []
    c_list = [float(x) for x in joined["close"]]
    v_list = [float(x) for x in joined["volume"]]
    for i in range(len(joined)):
        start = max(0, i - VOLUME_BASELINE * 2)
        reading = read_volume("X", c_list[start : i + 1], v_list[start : i + 1])
        ratios.append(reading.ratio)
        obv.append(reading.obv_trend)
    return (
        pd.Series(ratios, index=joined.index, dtype=float),
        pd.Series(obv, index=joined.index, dtype=float),
    )


def sleeve_spike_share(closes: pd.DataFrame, volumes: pd.DataFrame) -> pd.Series:
    """Share of the asset-class sleeve showing a volume spike on the same day.

    One ticker spiking is a ticker story; five of seven spiking at once is the crowd moving, and
    that is the behavioural statement worth testing.
    """
    per_ticker: list[pd.Series] = []
    for ticker in BEHAVIOUR_SLEEVE:
        if ticker not in closes.columns or ticker not in volumes.columns:
            continue
        ratio, _ = volume_signal_series(closes[ticker], volumes[ticker])
        per_ticker.append((ratio >= 2.0).astype(float).where(ratio.notna()))
    if not per_ticker:
        return pd.Series(dtype=float)
    return pd.concat(per_ticker, axis=1).mean(axis=1, skipna=True) * 100.0


def breadth_series(panel: pd.DataFrame, window: int = SMA_WINDOW) -> pd.Series:
    """% of the panel's tickers above their own 200-day SMA, for every day in the history.

    Vectorised rather than looping `regime.compute_breadth`, which is a last-day-only function.
    `main` cross-checks the final value against it so the two definitions cannot drift apart.

    **Survivorship warning, and it is a real limit on what this can prove:** the panel holds the
    tickers this project tracks TODAY. Names that were delisted or dropped along the way are
    absent, so historical breadth is biased upward and the level is not comparable to a published
    breadth index. The RANKING across days — the only thing the study uses — is far less affected,
    but "less affected" is not "unaffected".
    """
    sma = panel.rolling(window, min_periods=window).mean()
    above = (panel > sma) & panel.notna() & sma.notna()
    evaluable = sma.notna() & panel.notna()
    counts = evaluable.sum(axis=1)
    return (above.sum(axis=1) / counts.where(counts > 0) * 100.0).dropna()


def load_sleeve_closes(*, refresh: bool = False) -> pd.DataFrame:
    """Closes for the behaviour sleeve, column-wise so each ticker keeps its own start date."""
    if not refresh and os.path.exists(SLEEVE_CLOSES):
        return _read_panel(SLEEVE_CLOSES)
    from equity_scout.data.etf_panel import load_price_history

    panel = load_price_history(
        list(BEHAVIOUR_SLEEVE), start="2007-01-01", snapshot=SLEEVE_CLOSES, refresh=True
    )
    return _read_panel(SLEEVE_CLOSES) if os.path.exists(SLEEVE_CLOSES) else panel.closes


def build_signals(*, refresh: bool) -> dict[str, tuple[pd.Series, str]]:
    """Every candidate, as (series, direction note). Direction matters for reading the spread:
    for some signals a high value means fear, for others it means health."""
    vix = load_vix_term(refresh=refresh)
    etf_closes = load_sleeve_closes(refresh=refresh)
    etf_volumes = _read_panel(ETF_VOLUME)
    bots = _read_panel(BOTS_PANEL)

    signals: dict[str, tuple[pd.Series, str]] = {}

    vix_close = vix["^VIX"].dropna()
    signals["VIX-Level"] = (vix_close, "hoch = Angst (Kontrollsignal, sitzt schon in der Ampel)")
    ts = (vix["^VIX"] / vix["^VIX3M"]).dropna()
    signals["VIX-Terminstruktur (VIX/VIX3M)"] = (
        ts, "hoch (>1) = Backwardation = akuter Stress; niedrig = Kontango = Ruhe"
    )
    short_ts = (vix["^VIX9D"] / vix["^VIX"]).dropna()
    signals["VIX kurz/mittel (VIX9D/VIX)"] = (short_ts, "hoch = akuter Kurzfrist-Stress")

    if "SPY" in etf_closes.columns and "SPY" in etf_volumes.columns:
        ratio, obv = volume_signal_series(etf_closes["SPY"], etf_volumes["SPY"])
        signals["SPY-Volumenratio"] = (
            ratio.dropna(), "hoch = ungewöhnlich viele handeln (richtungsfrei)"
        )
        signals["SPY-OBV-Trend"] = (
            obv.dropna(), "hoch = Akkumulation, niedrig = Abgabe (umgekehrte Richtung zu Stress)"
        )
    share = sleeve_spike_share(etf_closes, etf_volumes)
    if not share.empty:
        signals["Sleeve-Spike-Anteil"] = (
            share.dropna(), "hoch = breite Aufregung über Anlageklassen hinweg"
        )
    breadth = breadth_series(bots.drop(columns=["SPY"], errors="ignore"))
    if not breadth.empty:
        signals["Marktbreite (% über 200d)"] = (
            breadth, "hoch = gesund (umgekehrte Richtung zu Stress); survivorship-verzerrt"
        )
    return signals


def build_targets(spy: pd.Series) -> dict[str, tuple[pd.Series, int]]:
    targets: dict[str, tuple[pd.Series, int]] = {}
    for h in RETURN_HORIZONS:
        targets[f"SPY-Rendite {h}T"] = (forward_return(spy, h), h)
    for h in RISK_HORIZONS:
        targets[f"SPY-Vola {h}T"] = (forward_volatility(spy, h), h)
        targets[f"SPY-Drawdown {h}T"] = (forward_drawdown(spy, h), h)
    return targets


def _fmt(value: float | None, pct: bool = True) -> str:
    if value is None or not math.isfinite(value):
        return "  n/a"
    return f"{value:+7.2%}" if pct else f"{value:+7.4f}"


def _print_study(study: SignalStudy, uncorrected_alpha: float) -> None:
    marker = {"trägt": "TRÄGT", "instabil": "instabil", "kein Befund": "-",
              "offset-abhängig": "Artefakt", "zu wenig Historie": "zu kurz",
              "nicht messbar": "?"}.get(study.verdict, study.verdict)
    p_text = f"p={study.spread_p:.4f}" if study.spread_p is not None else "p=n/a"
    # The band between the corrected and the uncorrected level is where most "findings" in this
    # kind of study live. Naming it keeps the reader from having to compare two alphas in their
    # head - and from mistaking a near-miss for a result.
    naive = ""
    if study.spread_p is not None and study.alpha <= study.spread_p < uncorrected_alpha:
        naive = "  (wäre ohne Mehrfachtest-Korrektur signifikant)"
    print(
        f"    {study.target:<22} n={study.n_independent:>4}  Spread {_fmt(study.spread)}  "
        f"{p_text:<12} IC={_fmt(study.rank_ic_independent, pct=False)}  [{marker}]{naive}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-fetch the VIX term structure")
    parser.add_argument("--json", default=RESULT_JSON, help="where to write the machine-readable result")
    args = parser.parse_args()

    bots = _read_panel(BOTS_PANEL)
    if "SPY" not in bots.columns:
        print("SPY fehlt im ml_bots_panel — ohne Marktreihe kein Test.", file=sys.stderr)
        return 1
    spy = bots["SPY"].dropna()

    signals = build_signals(refresh=args.refresh)
    targets = build_targets(spy)
    candidates = [name for name in signals if name not in BASELINE_SIGNALS]
    # Both rounds count towards the correction. Running the incremental round on the level the
    # first round set would be searching twice and testing once.
    n_tests = (len(signals) + len(candidates)) * len(targets)
    alpha = bonferroni_alpha(n_tests)

    print("=" * 100)
    print("W0 — Verhaltensindikatoren gegen die eigene Historie")
    print("=" * 100)
    print(f"Marktreihe: SPY {spy.index[0].date()} bis {spy.index[-1].date()} ({len(spy)} Tage)")
    print(f"Runde 1: {len(signals)} Signale roh · Runde 2: {len(candidates)} Kandidaten nach Abzug")
    print(f"der Ampel-Bestandssignale ({', '.join(BASELINE_SIGNALS)}) · {len(targets)} Ziele")
    print(f"= {n_tests} Tests. Alpha unkorrigiert 0.05, Bonferroni-korrigiert {alpha:.5f} — der")
    print("Test entscheidet auf dem korrigierten Niveau, weil bei 0.05 und dieser Testzahl allein")
    print(f"aus Rauschen ~{n_tests * 0.05:.0f} Treffer zu erwarten wären.")
    print("n = UNABHÄNGIGE (nicht überlappende) Fenster — die Zahl, die eine Aussage trägt.")

    results: list[SignalStudy] = []

    print()
    print("-" * 100)
    print("RUNDE 1 — sagt das Signal überhaupt etwas voraus?")
    print("-" * 100)
    for signal_name, (series, direction) in signals.items():
        print()
        print(f"  {signal_name}")
        print(f"    Richtung: {direction}")
        print(f"    Historie: {series.index[0].date()} bis {series.index[-1].date()} ({len(series)} Tage)")
        for target_name, (target_series, horizon) in targets.items():
            study = study_signal(
                signal_name=signal_name,
                target_name=target_name,
                signal=series,
                target=target_series,
                horizon_days=horizon,
                alpha=alpha,
            )
            results.append(study)
            _print_study(study, uncorrected_alpha=0.05)

    print()
    print("-" * 100)
    print("RUNDE 2 — bleibt etwas übrig, wenn die Ampel-Bestandssignale abgezogen sind?")
    print("Das ist die Frage, an der eine Bau-Entscheidung hängt: ein Kandidat, der nur")
    print("wiederholt, was VIX-Level und Marktbreite schon sagen, kostet eine Datenquelle und")
    print("liefert keine neue Beobachtung.")
    print("-" * 100)
    controls = [signals[name][0] for name in BASELINE_SIGNALS if name in signals]
    incremental: list[SignalStudy] = []
    for signal_name in candidates:
        series, _ = signals[signal_name]
        residual = residualise(series, controls)
        print()
        print(f"  {signal_name} (Rest nach Abzug der Bestandssignale)")
        if residual.empty:
            print("    Zu wenig gemeinsame Historie mit den Bestandssignalen.")
            continue
        print(f"    Historie: {residual.index[0].date()} bis {residual.index[-1].date()} "
              f"({len(residual)} Tage)")
        for target_name, (target_series, horizon) in targets.items():
            study = study_signal(
                signal_name=f"{signal_name} [inkrementell]",
                target_name=target_name,
                signal=residual,
                target=target_series,
                horizon_days=horizon,
                alpha=alpha,
            )
            incremental.append(study)
            results.append(study)
            _print_study(study, uncorrected_alpha=0.05)

    carrying = [s for s in results if s.verdict == "trägt"]
    unstable = [s for s in results if s.verdict == "instabil"]
    artefacts = [s for s in results if s.verdict == "offset-abhängig"]
    carrying_incremental = [s for s in incremental if s.verdict == "trägt"]
    print()
    print("=" * 100)
    print(f"ERGEBNIS: {len(carrying)} von {n_tests} Tests tragen auf dem korrigierten Niveau.")
    print(f"Aussortiert: {len(unstable)} signifikant aber über die Zeit instabil, "
          f"{len(artefacts)} signifikant nur am gewählten Stichproben-Startpunkt.")
    print(f"Davon inkrementell (also mit eigenem Beitrag über die Ampel hinaus): "
          f"{len(carrying_incremental)}.")
    for study in artefacts:
        print(f"  ARTEFAKT  {study.signal} -> {study.target}: {study.note}")
    for study in carrying:
        print(f"  TRÄGT  {study.signal} -> {study.target}: {study.note}")
        for extreme in (study.high_extreme, study.low_extreme):
            if extreme is None or extreme.p_value is None:
                continue
            verdict = "wirkt" if extreme.p_value < study.alpha else "wirkt nicht"
            print(f"           Extrem {extreme.side} (n={extreme.n}): "
                  f"{extreme.mean_in_tail:+.2%} vs. Mitte {extreme.mean_middle:+.2%} "
                  f"(Differenz {extreme.difference:+.2%}, p={extreme.p_value:.4f}) — {verdict}")
    if not carrying:
        print("  Kein Kandidat hat das Gate passiert. Nullbefund — genauso gültig wie ein Treffer.")

    # A null result without these two numbers is unreadable: it could mean "no effect" or it
    # could mean "this sample could never have seen one". Printed for the return targets, since
    # that is where every test came back empty and the reader needs to know which case it is.
    print()
    print("-" * 100)
    print("WIE STARK MÜSSTE EIN EFFEKT SEIN, DAMIT DIESER TEST IHN SIEHT?")
    print("Kleinster Spitze-minus-Boden-Unterschied, den das Sample bei 80 % Testmacht noch")
    print("von Zufall trennen könnte. Liegt ein plausibler Markteffekt darunter, ist ein")
    print("Nullbefund aussagekräftig — liegt er darüber, war der Test von vornherein blind.")
    print("-" * 100)
    reference = next(iter(signals.values()))[0]
    for target_name, (target_series, horizon) in targets.items():
        frame = align(reference, target_series)
        mde = minimum_detectable_effect(independent_subsample(frame, horizon), alpha=alpha)
        mde_naive = minimum_detectable_effect(independent_subsample(frame, horizon), alpha=0.05)
        if mde is None:
            continue
        print(f"    {target_name:<22} korrigiert {mde:6.2%}   unkorrigiert {mde_naive:6.2%}")

    print()
    print("-" * 100)
    print("OFFSET-ROBUSTHEIT der tragenden Befunde")
    print("Die Stichprobe unabhängiger Fenster kann an horizon+1 verschiedenen Stellen beginnen.")
    print("Ein Befund, den nur ein einziger Startpunkt zeigt, ist ein Artefakt dieser Wahl.")
    print("-" * 100)
    for study in carrying:
        source = signals.get(study.signal.replace(" [inkrementell]", ""))
        if source is None:
            continue
        target_series, horizon = targets[study.target]
        robustness = offset_robustness(source[0], target_series, horizon, alpha=alpha)
        share = robustness["share_significant"]
        agreement = robustness["sign_agreement"]
        if share is None:
            continue
        print(f"    {study.signal} -> {study.target}: "
              f"{share:.0%} der {robustness['n_offsets']} Startpunkte signifikant, "
              f"Vorzeichen einig zu {agreement:.0%}, Median p={robustness['median_p']:.4f}")

    payload = [
        {
            "signal": s.signal, "target": s.target, "horizon_days": s.horizon_days,
            "n_overlapping": s.n_overlapping, "n_independent": s.n_independent,
            "rank_ic_overlapping": s.rank_ic_overlapping,
            "rank_ic_independent": s.rank_ic_independent,
            "spread": s.spread, "spread_p": s.spread_p,
            "walk_forward_spreads": list(s.walk_forward_spreads),
            "buckets": [
                {"label": b.label, "n": b.n, "signal_lo": b.signal_lo, "signal_hi": b.signal_hi,
                 "mean_target": b.mean_target, "median_target": b.median_target}
                for b in s.buckets
            ],
            "offset_share_significant": s.offset_share_significant,
            "minimum_detectable": s.minimum_detectable,
            "high_extreme": None if s.high_extreme is None else {
                "n": s.high_extreme.n, "mean_in_tail": s.high_extreme.mean_in_tail,
                "mean_middle": s.high_extreme.mean_middle,
                "difference": s.high_extreme.difference, "p_value": s.high_extreme.p_value,
            },
            "low_extreme": None if s.low_extreme is None else {
                "n": s.low_extreme.n, "mean_in_tail": s.low_extreme.mean_in_tail,
                "mean_middle": s.low_extreme.mean_middle,
                "difference": s.low_extreme.difference, "p_value": s.low_extreme.p_value,
            },
            "alpha": s.alpha, "verdict": s.verdict, "note": s.note,
        }
        for s in results
    ]
    os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump({"n_tests": n_tests, "alpha": alpha, "studies": payload}, fh,
                  indent=2, ensure_ascii=False)
    print(f"\nDetails: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
