"""Fetch broad daily OHLCV history for the spike study (v16, 2026-08-19).

Why this exists: the question "when does a jump continue and when does it reverse?" cannot be
answered with the data we had. `data/minutes/` covers 69 symbols — mega-caps and ETFs — and
those are precisely the names that never jump 50 %. The stocks that ignite are small and mid
caps, and we had no history for them at all.

Alpaca's daily bars cover them, all the way back, and daily history is available on the basic
plan (the SIP restriction bites on real-time, not on history).

ADJUSTMENT IS NOT OPTIONAL HERE. On raw bars a 1-for-10 reverse split reads as +900 % and a
forward split as -50 %; a spike study on raw data would be a study of corporate actions. The
matrix night of 2026-08-18 already paid for this lesson once (split-poisoned bars) — hence
`adjustment=all`, stated in the file so nobody re-derives it.

Writes one gzipped CSV per year into data/daily/, so a run can be resumed and a year can be
re-fetched without touching the others.

Usage:
    uv run python scripts/fetch_spike_history.py --start 2019-01-01 [--end 2026-08-18]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from equity_scout.alpaca_broker import auth_headers
from equity_scout.alpaca_screener import fetch_assets
from equity_scout.catalyst_scan import _is_excluded_instrument

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
OUT_DIR = Path("data/daily")

SYMBOLS_PER_CALL = 100   # comfortably inside URL limits, few enough to page quickly
PAGE_LIMIT = 10_000
RETRIES = 4
BACKOFF_SECONDS = 2.0


def tradable_ordinary_symbols() -> list[str]:
    """Every ordinary, tradable US equity — warrants, rights and pooled vehicles removed.

    Reuses the ignition scan's instrument filter so the study population and the live
    population are the SAME set. A study on a different universe than the one we trade would
    answer a question we never asked.
    """
    assets = fetch_assets()
    return sorted(
        symbol for symbol, asset in assets.items()
        if asset["tradable"] and not _is_excluded_instrument(asset["name"])
        # Alpaca uses dots for share classes (BRK.A); those are fine. Slashes and spaces
        # appear on non-equity oddities that the bar endpoint rejects wholesale.
        and "/" not in symbol and " " not in symbol
    )


def _get(params: dict) -> dict:
    for attempt in range(RETRIES):
        request = urllib.request.Request(
            f"{BARS_URL}?{urllib.parse.urlencode(params)}", headers=auth_headers()
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == RETRIES - 1:
                raise
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == RETRIES - 1:
                raise
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    return {}


def fetch_year(symbols: list[str], year: int, *, start: str, end: str) -> list[tuple]:
    """(symbol, date, o, h, l, c, v, trade_count) rows for one calendar year."""
    window_start = max(start, f"{year}-01-01")
    window_end = min(end, f"{year}-12-31")
    if window_start > window_end:
        return []
    rows: list[tuple] = []
    for index in range(0, len(symbols), SYMBOLS_PER_CALL):
        chunk = symbols[index:index + SYMBOLS_PER_CALL]
        token = None
        while True:
            params = {
                "symbols": ",".join(chunk),
                "timeframe": "1Day",
                "start": window_start,
                "end": window_end,
                "limit": PAGE_LIMIT,
                "adjustment": "all",  # see module docstring — never negotiable
                "feed": "sip",        # history is permitted on the basic plan
            }
            if token:
                params["page_token"] = token
            payload = _get(params)
            for symbol, bars in (payload.get("bars") or {}).items():
                for bar in bars:
                    rows.append((
                        symbol, bar["t"][:10], bar["o"], bar["h"], bar["l"],
                        bar["c"], bar["v"], bar.get("n", 0),
                    ))
            token = payload.get("next_page_token")
            if not token:
                break
        done = min(index + SYMBOLS_PER_CALL, len(symbols))
        print(f"  {year}: {done}/{len(symbols)} Symbole, {len(rows)} Bars",
              file=sys.stderr, flush=True)
    return rows


def write_year(rows: list[tuple], year: int) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"daily-{year}.csv.gz"
    with gzip.open(path, "wt", newline="") as handle:
        handle.write("ticker,date,open,high,low,close,volume,trades\n")
        for row in rows:
            handle.write(",".join(str(value) for value in row) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2026-08-18")
    parser.add_argument("--limit-symbols", type=int, default=None,
                        help="cap the universe (smoke tests only)")
    args = parser.parse_args(argv)

    symbols = tradable_ordinary_symbols()
    if args.limit_symbols:
        symbols = symbols[:args.limit_symbols]
    print(f"{len(symbols)} handelbare Einzelaktien im Studienuniversum", file=sys.stderr)

    years = range(int(args.start[:4]), int(args.end[:4]) + 1)
    for year in years:
        path = OUT_DIR / f"daily-{year}.csv.gz"
        if path.exists():
            print(f"{year}: bereits vorhanden — übersprungen", file=sys.stderr)
            continue
        rows = fetch_year(symbols, year, start=args.start, end=args.end)
        if not rows:
            print(f"{year}: keine Bars", file=sys.stderr)
            continue
        written = write_year(rows, year)
        print(f"{year}: {len(rows)} Bars -> {written}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
