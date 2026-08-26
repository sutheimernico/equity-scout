#!/usr/bin/env python
"""Misst, ob die Vorschläge dieser Maschine je etwas getragen haben.

    .venv/bin/python scripts/run_suggestion_review.py            # messen und speichern
    .venv/bin/python scripts/run_suggestion_review.py --dry-run  # nur drucken

Netz: EIN yfinance-Batch über alle je vorgeschlagenen Titel plus die Heimatindizes,
split- und dividendenbereinigt (`auto_adjust=True`). Ohne diese Bereinigung ist jede
Rendite über einen Split falsch — die Matrix-Nacht am 2026-08-18 hat genau das gekostet.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from equity_scout.constants import DISCLAIMER  # noqa: E402
from equity_scout.suggestion_review import (  # noqa: E402
    HORIZONS,
    Outcome,
    Suggestion,
    benchmark_for,
    measure,
    summarise,
    verdict_line,
)
from equity_scout.suggestion_storage import (  # noqa: E402
    RANK_CUTOFF,
    collect_pitch_suggestions,
    collect_rank_suggestions,
    save_review,
)

DB_PATH = str(Path(__file__).resolve().parents[1] / "equity_scout.db")
# Ein Jahr deckt jeden Vorschlag seit dem ersten Lauf plus den längsten Horizont ab.
HISTORY_PERIOD = "1y"


def fetch_series(tickers: list[str]) -> dict[str, list[tuple[str, float]]]:
    """Bereinigte Tagesschlusskurse je Ticker. Netz — im Test durch eine Fake ersetzt."""
    import yfinance as yf

    data = yf.download(
        tickers, period=HISTORY_PERIOD, auto_adjust=True, progress=False,
        threads=True, group_by="ticker",
    )
    series: dict[str, list[tuple[str, float]]] = {}
    for ticker in tickers:
        try:
            frame = data[ticker] if len(tickers) > 1 else data
        except KeyError:
            continue  # unbekanntes Symbol: fehlt, und der Bericht zählt es als Lücke
        if "Close" not in frame.columns:
            continue
        closes = frame["Close"].dropna()
        if closes.empty:
            continue
        series[ticker] = [
            (str(idx)[:10], float(value)) for idx, value in closes.items() if value > 0
        ]
    return series


def build_report(
    suggestions: list[Suggestion],
    series: dict[str, list[tuple[str, float]]],
    *,
    now: str,
) -> dict:
    """Alle Messungen + Aggregate. Rein — der Netzabruf steckt im Aufrufer."""
    outcomes: list[Outcome] = []
    missing_prices: set[str] = set()
    for suggestion in suggestions:
        ticker_series = series.get(suggestion.ticker)
        if not ticker_series:
            missing_prices.add(suggestion.ticker)
            continue
        benchmark = benchmark_for(suggestion.ticker, suggestion.region)
        benchmark_series = series.get(benchmark) if benchmark else None
        for horizon in HORIZONS:
            outcome = measure(suggestion, ticker_series, horizon, benchmark_series)
            if outcome is not None:
                outcomes.append(outcome)

    summaries = []
    for source, label in (("pitch", "Pitches (per Telegram vorgeschlagen)"),
                          ("rank", f"Rangliste (Top {RANK_CUTOFF} je Stil)")):
        for horizon in HORIZONS:
            subset = [
                o for o in outcomes
                if o.suggestion.source == source and o.horizon_days == horizon
            ]
            summary = summarise(subset, label, horizon)
            summaries.append({
                "source": source,
                "label": summary.label,
                "horizon_days": summary.horizon_days,
                "n": summary.n,
                "n_independent": summary.n_independent,
                "hit_rate": summary.hit_rate,
                "mean_excess_pct": summary.mean_excess_pct,
                "median_excess_pct": summary.median_excess_pct,
                "mean_return_pct": summary.mean_return_pct,
                "best": summary.best,
                "worst": summary.worst,
                "sector_concentration": summary.sector_concentration,
                "tickers": summary.tickers,
                "verdict": None if summary.verdict is None else {
                    "verdict": summary.verdict.verdict,
                    "p_value": summary.verdict.p_value,
                    "note": summary.verdict.note,
                },
                "line": verdict_line(summary),
            })

    return {
        "computed_at": now,
        "n_suggestions": len(suggestions),
        "n_measured": len(outcomes),
        "missing_prices": sorted(missing_prices),
        "horizons": list(HORIZONS),
        "rank_cutoff": RANK_CUTOFF,
        "summaries": summaries,
        "outcomes": [
            {
                "source": o.suggestion.source,
                "ticker": o.suggestion.ticker,
                "suggested_at": o.suggestion.suggested_at,
                "score": o.suggestion.score,
                "bucket": o.suggestion.bucket,
                "sector": o.suggestion.sector,
                "horizon_days": o.horizon_days,
                "entry_date": o.entry_date,
                "entry_price": o.entry_price,
                "exit_date": o.exit_date,
                "exit_price": o.exit_price,
                "return_pct": o.return_pct * 100,
                "benchmark_ticker": o.benchmark_ticker,
                "benchmark_return_pct": (
                    None if o.benchmark_return_pct is None else o.benchmark_return_pct * 100
                ),
                "excess_pct": None if o.excess_pct is None else o.excess_pct * 100,
                "bars_available": o.bars_available,
            }
            for o in sorted(outcomes, key=lambda x: (x.horizon_days, x.suggestion.suggested_at))
        ],
        "disclaimer": DISCLAIMER,
    }


def print_report(report: dict) -> None:
    print(f"\nVorschlags-Rückschau — {report['computed_at']}")
    print(f"{report['n_suggestions']} Vorschläge, {report['n_measured']} Messungen "
          f"(Horizonte {report['horizons']} Handelstage)")
    if report["missing_prices"]:
        print(f"Ohne Kursreihe (nicht messbar): {', '.join(report['missing_prices'])}")
    for summary in report["summaries"]:
        if summary["n"] == 0:
            continue
        print(f"\n— {summary['label']}, {summary['horizon_days']} Tage —")
        print(f"  {summary['line']}")
        if summary["mean_return_pct"] is not None:
            print(f"  Rohrendite Ø {summary['mean_return_pct']:+.1f} %"
                  f" · Median-Exzess {summary['median_excess_pct'] or 0:+.1f} pp")
        if summary["best"] and summary["worst"]:
            print(f"  Bester {summary['best'][0]} {summary['best'][1]:+.1f} pp"
                  f" · Schlechtester {summary['worst'][0]} {summary['worst'][1]:+.1f} pp")
        if summary["sector_concentration"]:
            print(f"  Größter Sektor: {summary['sector_concentration'] * 100:.0f} % der Titel")
    print(f"\n{report['disclaimer']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="messen und drucken, nicht speichern")
    args = parser.parse_args()

    suggestions = collect_pitch_suggestions(args.db) + collect_rank_suggestions(args.db)
    if not suggestions:
        print("Keine Vorschläge gefunden — nichts zu messen.")
        return 0

    tickers = sorted({s.ticker for s in suggestions})
    benchmarks = sorted({
        b for s in suggestions if (b := benchmark_for(s.ticker, s.region)) is not None
    })
    print(f"{len(suggestions)} Vorschläge über {len(tickers)} Titel; "
          f"lade Kurse für {len(tickers) + len(benchmarks)} Symbole …")
    series = fetch_series(tickers + benchmarks)
    print(f"Kursreihen erhalten: {len(series)}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = build_report(suggestions, series, now=now)
    print_report(report)

    if not args.dry_run:
        review_id = save_review(args.db, now, report)
        print(f"Gespeichert als suggestion_reviews.id={review_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
