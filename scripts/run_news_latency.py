#!/usr/bin/env python3
"""Measure the news latency-decay curve — the answer to "should we scrape to be faster?".

Two phases, same resumable pattern as the signal matrix:

1. **fetch** — historical news per year into `data/news/news-<year>.csv.gz` (Alpaca/Benzinga wire,
   second-level `created_at`, back to 2016). A year already on disk is skipped.
2. **measure** — for every (delay, hold, cost) combination: what a trader entering `delay`
   minutes after the wire MISSED, what they could still earn, and whether that is significant.
   Then one blunt verdict sentence.

The verdict is the deliverable, not the table: it says whether latency is the binding constraint
at all. If it is not, a scraping network is wasted effort. If it is, the race is against
co-located microsecond competition and our ~5-second path loses it — also without scraping.

Usage:
    uv run python scripts/run_news_latency.py --phase fetch
    uv run python scripts/run_news_latency.py --phase measure
    uv run python scripts/run_news_latency.py                  # both
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from equity_scout.data.minute_bars import load_minutes  # noqa: E402
from equity_scout.data.news_history import (  # noqa: E402
    NewsHistoryError,
    fetch_news_year,
    items_for_ticker,
    load_news,
    news_path,
    save_year,
)
from equity_scout.matrix.latency import (  # noqa: E402
    DELAY_MINUTES,
    HOLD_MINUTES,
    decay_verdict,
    event_moves,
    summarise,
)

from scripts.fetch_minute_history import FULL_YEARS, MINUTE_UNIVERSE  # noqa: E402

COST_BPS = 4.0  # liquid-name roundtrip; the matrix's own cost axis covers the rest


def phase_fetch(years: list[int], tickers: list[str]) -> None:
    pending = [y for y in years if not news_path(y).exists()]
    print(f"Phase 1 — News: {len(pending)} Jahre offen "
          f"({len(years) - len(pending)} schon auf Platte)", flush=True)
    started = time.time()
    for i, year in enumerate(pending, start=1):
        try:
            frame = fetch_news_year(year, tickers=tickers)
        except NewsHistoryError as err:
            print(f"  FEHLER {year}: {err}", file=sys.stderr, flush=True)
            continue
        if frame.empty:
            print(f"  {year}: keine Artikel", flush=True)
            continue
        save_year(frame, year)
        elapsed = time.time() - started
        print(f"  [{i}/{len(pending)}] {year}: {len(frame):,} Artikel "
              f"({elapsed / i:.0f}s/Jahr)", flush=True)


def phase_measure(years: list[int], tickers: list[str], out: str | None) -> int:
    news = load_news(years)
    if news.empty:
        print("Keine News auf Platte — erst --phase fetch laufen lassen.", file=sys.stderr)
        return 2
    print(f"\nPhase 2 — {len(news):,} Artikel, "
          f"{news['created_at'].min().date()} bis {news['created_at'].max().date()}")

    # Accumulate per (delay, hold) across tickers: one ticker's bars in memory at a time.
    buckets: dict[tuple[int, int], list] = {
        (delay, hold): [] for delay in DELAY_MINUTES for hold in HOLD_MINUTES
    }
    covered = 0
    for ticker in tickers:
        loaded = load_minutes([ticker], years=years)
        if ticker not in loaded:
            continue
        stamps = items_for_ticker(news, ticker)["created_at"]
        if stamps.empty:
            continue
        covered += 1
        for (delay, hold), store in buckets.items():
            moves = event_moves(loaded[ticker], stamps, delay_minutes=delay, hold_minutes=hold)
            store.append(moves)
        print(f"  {ticker}: {len(stamps):,} Artikel gegen {len(loaded[ticker]):,} Bars",
              flush=True)

    rows = []
    for (delay, hold), store in sorted(buckets.items()):
        merged = {
            "before_bp": pd.concat([pd.Series(m["before_bp"]) for m in store]).to_numpy()
            if store else pd.Series(dtype=float).to_numpy(),
            "after_bp": pd.concat([pd.Series(m["after_bp"]) for m in store]).to_numpy()
            if store else pd.Series(dtype=float).to_numpy(),
        }
        rows.append({"delay_minutes": delay, "hold_minutes": hold,
                     **summarise(merged, cost_bps=COST_BPS)})

    print(f"\n{'Verzög.':>8}{'Halten':>8}{'n':>9}{'verpasst':>11}{'danach':>10}"
          f"{'netto':>10}{'t':>8}")
    for row in rows:
        if row["net_bp"] is None:
            print(f"{row['delay_minutes']:>6}min{row['hold_minutes']:>6}min{row['n']:>9}"
                  f"{'—':>11}{'—':>10}{'—':>10}{'—':>8}")
            continue
        print(f"{row['delay_minutes']:>6}min{row['hold_minutes']:>6}min{row['n']:>9}"
              f"{row['missed_bp']:>+11.2f}{row['after_bp']:>+10.2f}"
              f"{row['net_bp']:>+10.2f}{row['t']:>+8.2f}")

    verdict = decay_verdict(rows)
    print(f"\nURTEIL: {verdict}")
    _write_doc(out, news, covered, rows, verdict)
    return 0


def _write_doc(out, news: pd.DataFrame, covered: int, rows: list[dict], verdict: str) -> None:
    path = Path(out or f"docs/research/{date.today().isoformat()}-news-latency-decay.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# News-Latenz: wie schnell zerfällt die Reaktion? ({date.today().isoformat()})",
        "",
        "Nicos Frage: sollen wir viele Quellen scrapen, um schneller als andere zu sein? Diese",
        "Messung entscheidet sie, statt sie zu diskutieren. Reproduzierbar über",
        "`uv run python scripts/run_news_latency.py`.",
        "",
        f"**URTEIL: {verdict}**",
        "",
        "## Datenbasis",
        "",
        f"- {len(news):,} Artikel mit **sekundengenauem** Zeitstempel "
        f"({news['created_at'].min().date()} bis {news['created_at'].max().date()}), "
        "Alpaca/Benzinga-Wire",
        f"- gegen Minutenbars von {covered} Instrumenten gehalten",
        f"- Kostenannahme {COST_BPS:.0f} bp Roundtrip (liquide Titel)",
        "",
        "## Zerfallskurve",
        "",
        "„verpasst\" = Bewegung zwischen Meldung und verzögertem Einstieg (der Preis der Latenz).",
        "„danach\" = was ab dem verzögerten Einstieg noch kommt. „netto\" = danach minus Kosten.",
        "",
        "| Verzögerung | Halten | n | verpasst | danach | netto | t |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        if row["net_bp"] is None:
            lines.append(f"| {row['delay_minutes']} min | {row['hold_minutes']} min | "
                         f"{row['n']} | — | — | — | — |")
            continue
        lines.append(
            f"| {row['delay_minutes']} min | {row['hold_minutes']} min | {row['n']:,} | "
            f"{row['missed_bp']:+.2f} bp | {row['after_bp']:+.2f} bp | "
            f"{row['net_bp']:+.2f} bp | {row['t']:+.2f} |"
        )
    lines += [
        "",
        "## Grenzen",
        "",
        "- **Der Wire ist nicht das Ereignis.** Gemessen wird ab der Benzinga-Veröffentlichung; "
        "die Verzögerung zwischen dem eigentlichen Vorfall und dem Wire steckt in „verpasst\" "
        "mit drin. Eine schnellere Quelle würde einen Teil davon einsammeln — wie viel, sagt "
        "diese Messung nicht.",
        "- **Kein Richtungsfilter.** Alle Artikel zählen gleich; „gute\" und „schlechte\" "
        "Nachrichten sind nicht getrennt. Ein Richtungssignal wäre der nächste Schritt, aber "
        "erst wenn die Zerfallskurve zeigt, dass überhaupt Zeit zum Handeln bleibt.",
        "- **Long-only, kein Hebel, Papier.** Wie überall in diesem Projekt.",
    ]
    path.write_text("\n".join(lines) + "\n")
    print(f"Doku geschrieben: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="*", default=list(FULL_YEARS))
    parser.add_argument("--tickers", nargs="*", default=list(MINUTE_UNIVERSE))
    parser.add_argument("--phase", choices=("all", "fetch", "measure"), default="all")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.phase in ("all", "fetch"):
        phase_fetch(args.years, args.tickers)
    if args.phase == "fetch":
        return 0
    return phase_measure(args.years, args.tickers, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
