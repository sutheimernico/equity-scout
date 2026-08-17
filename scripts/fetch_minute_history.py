#!/usr/bin/env python3
"""Bulk-download the minute-bar universe for the signal matrix (resumable).

Measured 2026-08-17: ~19k bars/s, i.e. ~5 s per ticker-year -> the full universe over
2016-2026 lands in roughly 75 minutes. Resumable by design: a ticker-year that already has a
file is skipped, so an interrupted run continues where it stopped.

Universe design, per Nico's brief (2026-08-17): not only stocks — indices, commodities, bonds,
currencies and volatility, so the matrix can answer whether a pattern behaves DIFFERENTLY per
asset class. Asset class is therefore a matrix axis, and every ticker carries its class here.

Two honest limits of this universe:
- **ETFs, not futures.** Alpaca serves US equities and ETFs; there is no CL/GC futures feed.
  So "oil" means USO (which carries roll cost and tracking error), not the WTI contract. Good
  enough to measure signal MECHANICS, not good enough to quote a commodity's own return.
- **Liquidity bias, deliberately.** These are the most liquid instruments in their class, i.e.
  the cheapest possible case for trading costs. A signal that fails here fails everywhere more
  expensive; the reverse does not follow, and the research doc says so.

Usage:
    uv run python scripts/fetch_minute_history.py               # all missing ticker-years
    uv run python scripts/fetch_minute_history.py --years 2024 2025
    uv run python scripts/fetch_minute_history.py --coverage    # report only, no fetching
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from equity_scout.data.minute_bars import (  # noqa: E402
    DATA_BASE_PATH,
    MinuteBarError,
    bars_path,
    fetch_minute_year,
    save_year,
)

# {ticker: asset class}. Fixed list, not a screen: a screen would make the universe a moving
# target and the matrix uncomparable between runs.
ASSET_CLASSES: dict[str, str] = {
    # Broad indices
    "SPY": "index", "QQQ": "index", "IWM": "index", "DIA": "index", "MDY": "index",
    "EFA": "index", "EEM": "index", "VGK": "index", "EWJ": "index", "FXI": "index",
    # US sectors
    "XLF": "sector", "XLK": "sector", "XLE": "sector", "XLV": "sector", "XLI": "sector",
    "XLP": "sector", "XLY": "sector", "XLU": "sector", "XLB": "sector", "XLRE": "sector",
    # Commodities (ETFs on the underlying — see module docstring)
    "GLD": "commodity", "SLV": "commodity", "USO": "commodity", "UNG": "commodity",
    "DBC": "commodity", "DBA": "commodity", "CPER": "commodity", "PPLT": "commodity",
    # Bonds / rates
    "TLT": "bond", "IEF": "bond", "SHY": "bond", "HYG": "bond", "LQD": "bond", "TIP": "bond",
    # Currencies
    "UUP": "currency", "FXE": "currency", "FXY": "currency", "FXB": "currency",
    # Volatility
    "VXX": "volatility",
    # Real estate
    "VNQ": "reit",
    # Mega-cap single stocks, spread across sectors
    "AAPL": "stock", "MSFT": "stock", "NVDA": "stock", "AMZN": "stock", "GOOGL": "stock",
    "META": "stock", "TSLA": "stock", "AVGO": "stock", "JPM": "stock", "V": "stock",
    "UNH": "stock", "XOM": "stock", "JNJ": "stock", "WMT": "stock", "PG": "stock",
    "MA": "stock", "HD": "stock", "CVX": "stock", "MRK": "stock", "ABBV": "stock",
    "KO": "stock", "PEP": "stock", "COST": "stock", "ADBE": "stock", "CRM": "stock",
    "AMD": "stock", "NFLX": "stock", "INTC": "stock", "CSCO": "stock", "BA": "stock",
}
MINUTE_UNIVERSE: tuple[str, ...] = tuple(ASSET_CLASSES)
FULL_YEARS = tuple(range(2016, 2027))
THIN_YEAR_BARS = 50_000  # a full ticker-year is ~98k regular-session bars; below this = gap


def asset_class(ticker: str) -> str:
    """The matrix's asset-class axis value. Unknown tickers are labelled, never guessed."""
    return ASSET_CLASSES.get(ticker.upper(), "unknown")


def missing_jobs(
    tickers: list[str], years: list[int], *, root: Path | str = DATA_BASE_PATH
) -> list[tuple[str, int]]:
    """The (ticker, year) pairs with no file yet — the resume list."""
    return [
        (ticker, year)
        for ticker in tickers
        for year in years
        if not bars_path(ticker, year, root=root).exists()
    ]


def summarise_coverage(
    tickers: list[str], years: list[int], *, root: Path | str = DATA_BASE_PATH
) -> list[dict]:
    """Rows per existing ticker-year with bar counts and a `thin` flag. Coverage is reported,
    never assumed: a matrix cell computed over a half-empty year is a different measurement
    than the same cell over a full one."""
    rows = []
    for ticker in tickers:
        for year in years:
            path = bars_path(ticker, year, root=root)
            if not path.exists():
                continue
            bars = len(pd.read_csv(path, index_col="t"))
            rows.append({"ticker": ticker, "year": year, "bars": bars,
                         "thin": bars < THIN_YEAR_BARS})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="*", default=list(FULL_YEARS))
    parser.add_argument("--tickers", nargs="*", default=list(MINUTE_UNIVERSE))
    parser.add_argument("--coverage", action="store_true", help="report coverage, fetch nothing")
    args = parser.parse_args()

    if args.coverage:
        rows = summarise_coverage(args.tickers, args.years)
        total = sum(r["bars"] for r in rows)
        thin = [r for r in rows if r["thin"]]
        print(f"{len(rows)} Ticker-Jahre vorhanden, {total:,} Bars insgesamt")
        print(f"davon dünn (< {THIN_YEAR_BARS:,} Bars): {len(thin)}")
        for row in thin[:20]:
            print(f"  {row['ticker']} {row['year']}: {row['bars']:,}")
        print(f"fehlend: {len(missing_jobs(args.tickers, args.years))} Ticker-Jahre")
        return 0

    jobs = missing_jobs(args.tickers, args.years)
    print(f"{len(jobs)} Ticker-Jahre zu laden (vorhandene werden übersprungen)", flush=True)
    started, failures, saved_bars = time.time(), [], 0
    for i, (ticker, year) in enumerate(jobs, start=1):
        try:
            frame = fetch_minute_year(ticker, year)
        except MinuteBarError as err:
            # Loud and recorded: a truncated file would poison every later measurement,
            # so nothing is written and the pair stays on the resume list.
            print(f"  FEHLER {ticker} {year}: {err}", file=sys.stderr, flush=True)
            failures.append((ticker, year))
            continue
        if frame.empty:
            print(f"  leer {ticker} {year} — nicht gespeichert (kein Handel/kein Zugang)",
                  flush=True)
            continue
        save_year(frame, ticker, year)
        saved_bars += len(frame)
        elapsed = time.time() - started
        print(f"  [{i}/{len(jobs)}] {ticker} {year}: {len(frame):,} Bars "
              f"({elapsed / i:.1f}s/Job, ~{(len(jobs) - i) * elapsed / i / 60:.0f} min übrig)",
              flush=True)
    print(f"\nFertig: {saved_bars:,} Bars in {(time.time() - started) / 60:.1f} min")
    if failures:
        print(f"{len(failures)} Ticker-Jahre fehlgeschlagen — Skript erneut ausführen:")
        for ticker, year in failures[:20]:
            print(f"  {ticker} {year}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
