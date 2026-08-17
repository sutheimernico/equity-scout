# Signal-Matrix mit Plateau-Suche Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-dimensional signal matrix (signal type × bar resolution × holding period × threshold × cost assumption) over ~10 years of minute bars, then search it for connected PLATEAUS — regions where a rule survives its whole neighbourhood after costs — and validate every plateau on an untouched hold-out period.

**Architecture:** Three layers, each pure and testable on its own. (1) A minute-bar store: Alpaca SIP bars from 2016 on disk as gzipped CSV per ticker-year, plus a session-aware resampler. (2) A cell evaluator: one signal + one parameter tuple + one cost assumption → (n, mean_bp, t, hit_rate, net_bp). (3) A plateau finder: flood-fill over the cell grid, so the output is a REGION, never a winning cell. The hold-out window (2023-01-01 onward) is opened exactly once per plan execution and the fact is logged.

**Why this is worth building even though every previous rule failed:** the earlier minute-scale studies were data-limited, not effect-limited — `breakout-first-minute` had 91 events from 7 days because yfinance stops there. Alpaca's SIP feed reaches back to 2016-01-01 (verified 2026-08-17: 10k bars/call with paging, ~19k bars/s), which is ~1 million minute bars per ticker. On that sample size, minute-scale effects ARE resolvable — the 5-minute reversal already measured t = −32.1 on 42 days. What killed every candidate so far was COSTS, not significance, so the cost assumption is a mandatory axis of this matrix rather than a footnote.

**Tech Stack:** Python 3 / pandas / numpy / pytest / ruff (all existing). Alpaca SIP historical bars via the credentials already in `.env`. Storage: `csv.gz` via pandas — deliberately NOT parquet, because `pyarrow` is not installed and this plan does not introduce a dependency for a nightly batch job.

**Branch:** `autopilot/work` (loop convention). Gate per task: `uv run pytest -q` green AND `uv run ruff check .` clean. Conventional Commits, English.

---

## Scope: this plan MEASURES, it does not trade

This plan ends with a research document that answers one question: **do robust plateaus exist in this space, and do they survive a hold-out period?** Wiring a surviving plateau into a live lane (sleeve integration, decay monitoring, the "matrix maintains itself" loop) is a SEPARATE, Nico-gated follow-up plan — deliberately, because building the trading path for signals that may not exist is exactly the "measure before you build" rule this repo runs on. If Task 8 finds nothing, the correct outcome is a documented null result and no live code.

**Non-goals, explicitly:**

- **No leverage anywhere.** Leverage multiplies a *secured* expectation; nothing in this plan secures one. `minute-scale-trading` (2026-08-16) already priced it: at −4 bp per trade, 10× leverage yields −41 bp.
- **No news-latency strategy.** Nico's "buy in the second the news drops" needs a sub-second news feed and competes against microsecond co-located players; our measured signal-to-fill path is ~5 seconds. The matrix covers minute-scale PRICE patterns, which is the part we can honestly measure. Event reaction inside the first 30 minutes stays a candidate for a later plan (see Task 8's open-questions section).
- **No real money.** LOOP.md iron constraint, unchanged.

## The executability trap, named up front

Historical bars come from the **SIP** feed (consolidated, all venues). The live lanes read the **IEX** feed (~2-3 % of volume). A backtest on SIP and a live fill on IEX are not the same tape, and on minute bars that difference is material. So every plateau this plan reports carries a mandatory caveat, and the follow-up plan's FIRST task is a signal-vs-fill measurement (the same instrument `gapfade` already uses via `st_executions`). Do not let a SIP-measured plateau imply a live edge.

## File structure

| File | Responsibility |
|---|---|
| `src/equity_scout/data/minute_bars.py` | Fetch (paged) + store + load minute bars; session filter |
| `src/equity_scout/matrix/__init__.py` | Package marker |
| `src/equity_scout/matrix/timeframes.py` | Session-aware resampling 1min → k min |
| `src/equity_scout/matrix/signals.py` | Pure signal detectors, one function each |
| `src/equity_scout/matrix/grid.py` | Cell evaluation + full grid run + in-sample/hold-out split |
| `src/equity_scout/matrix/plateau.py` | Flood-fill plateau detection over the cell grid |
| `scripts/fetch_minute_history.py` | Resumable bulk download of the minute universe |
| `scripts/run_signal_matrix.py` | Runs the grid, finds plateaus, validates on hold-out, writes the research doc |
| `tests/test_minute_bars.py`, `tests/test_timeframes.py`, `tests/test_matrix_signals.py`, `tests/test_matrix_grid.py`, `tests/test_plateau.py` | Tests per layer |

---

### Task 1: Minute-bar store (fetch, save, load, session filter)

**Files:**
- Create: `src/equity_scout/data/minute_bars.py`
- Test: `tests/test_minute_bars.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_minute_bars.py`:

```python
"""Minute-bar store: paged parsing, session filter, on-disk roundtrip."""
from datetime import date

import pandas as pd
import pytest

from equity_scout.data.minute_bars import (
    REGULAR_CLOSE_ET,
    REGULAR_OPEN_ET,
    bars_path,
    parse_bars_page,
    regular_session_only,
    save_year,
    load_minutes,
)

PAGE = {
    "bars": {
        "AAPL": [
            {"t": "2024-01-02T14:30:00Z", "o": 187.0, "h": 187.5, "l": 186.8, "c": 187.2, "v": 120000},
            {"t": "2024-01-02T14:31:00Z", "o": 187.2, "h": 187.4, "l": 187.0, "c": 187.1, "v": 90000},
        ]
    },
    "next_page_token": "abc",
}


def test_parse_bars_page_returns_utc_indexed_frame_and_token():
    frame, token = parse_bars_page(PAGE, "AAPL")
    assert token == "abc"
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert str(frame.index.tz) == "UTC"
    assert frame["close"].iloc[-1] == 187.1


def test_parse_bars_page_absent_symbol_is_empty_not_error():
    frame, token = parse_bars_page({"bars": {}}, "AAPL")
    assert frame.empty and token is None


def test_regular_session_only_drops_pre_and_after_market():
    # 13:00Z = 08:00 ET (pre), 14:30Z = 09:30 ET (open), 21:00Z = 16:00 ET (close, exclusive)
    index = pd.to_datetime(
        ["2024-01-02T13:00:00Z", "2024-01-02T14:30:00Z",
         "2024-01-02T20:59:00Z", "2024-01-02T21:00:00Z"]
    )
    frame = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]}, index=index)
    kept = regular_session_only(frame)
    assert kept["close"].tolist() == [2.0, 3.0]


def test_regular_session_constants_are_the_us_cash_session():
    assert (REGULAR_OPEN_ET, REGULAR_CLOSE_ET) == ("09:30", "16:00")


def test_save_and_load_roundtrip(tmp_path):
    index = pd.to_datetime(["2024-01-02T14:30:00Z", "2024-01-02T14:31:00Z"])
    frame = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
         "close": [1.0, 2.0], "volume": [10, 20]},
        index=index,
    )
    save_year(frame, "AAPL", 2024, root=tmp_path)
    assert bars_path("AAPL", 2024, root=tmp_path).exists()
    back = load_minutes(["AAPL"], years=[2024], root=tmp_path)["AAPL"]
    assert len(back) == 2
    assert str(back.index.tz) == "UTC"
    assert back["close"].tolist() == [1.0, 2.0]


def test_load_minutes_skips_missing_years_without_inventing_data(tmp_path):
    assert load_minutes(["AAPL"], years=[2024], root=tmp_path) == {}


def test_load_minutes_rejects_a_year_it_cannot_parse(tmp_path):
    path = bars_path("AAPL", 2024, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not,a,bar,file\n1,2,3,4\n")
    with pytest.raises(ValueError, match="AAPL 2024"):
        load_minutes(["AAPL"], years=[2024], root=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_minute_bars.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'equity_scout.data.minute_bars'`

- [ ] **Step 3: Implement `src/equity_scout/data/minute_bars.py`**

```python
"""Minute-bar store for the signal matrix: Alpaca SIP history on disk.

Why this exists: every prior minute-scale study in docs/research/ was data-limited. yfinance
serves 7 days of minute bars, which is why `breakout-first-minute` had 91 events and a t of
0.94 — not enough sample to decide anything. Alpaca's SIP feed reaches back to 2016-01-01
(verified 2026-08-17), i.e. ~1 million minute bars per ticker. That is the difference between
"we cannot tell" and "we measured it".

Feed choice, and the trap it carries: HISTORY comes from SIP (consolidated tape, all venues).
The LIVE lanes read IEX (~2-3 % of volume). Anything measured here therefore describes a
richer tape than the one a live lane trades on — see the plan's executability section. This
module never pretends otherwise; it labels its feed in the stored files' provenance sidecar.

Storage: one gzipped CSV per ticker-year under `data/minutes/`. Deliberately not parquet —
pyarrow is not a dependency of this repo, and a nightly batch job does not justify adding one.
~98k rows per ticker-year compress to roughly 1.5 MB.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_BASE_PATH = "data/minutes"
FEED = "sip"  # history only; live lanes use IEX — see module docstring
HISTORY_START = "2016-01-01"  # earliest bar Alpaca serves (measured 2026-08-17)
PAGE_LIMIT = 10_000  # Alpaca's per-call maximum
REGULAR_OPEN_ET = "09:30"
REGULAR_CLOSE_ET = "16:00"
COLUMNS = ("open", "high", "low", "close", "volume")
_FIELD_MAP = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}


class MinuteBarError(RuntimeError):
    """Fetch failed in a way the caller must not read as 'no data'."""


def bars_path(ticker: str, year: int, *, root: Path | str = DATA_BASE_PATH) -> Path:
    return Path(root) / f"{ticker.upper()}-{year}.csv.gz"


def parse_bars_page(payload: dict, ticker: str) -> tuple[pd.DataFrame, str | None]:
    """One Alpaca bars page -> (UTC-indexed OHLCV frame, next_page_token or None).

    An absent symbol yields an EMPTY frame, never an exception: a ticker that did not trade
    in a window is a fact, and the caller counts it honestly.
    """
    rows = (payload.get("bars") or {}).get(ticker) or []
    token = payload.get("next_page_token")
    if not rows:
        return pd.DataFrame(columns=list(COLUMNS)), token
    frame = pd.DataFrame(
        [{_FIELD_MAP[k]: bar[k] for k in _FIELD_MAP if k in bar} for bar in rows],
        index=pd.to_datetime([bar["t"] for bar in rows], utc=True),
    )
    return frame[list(COLUMNS)].sort_index(), token


def regular_session_only(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep 09:30 <= t < 16:00 America/New_York (DST-correct via tz conversion).

    Pre- and after-market bars are dropped on purpose: they are thin, their spreads are
    multiples of the regular session's, and a signal measured across them would book a cost
    assumption that does not hold. The close bar itself is excluded (16:00 is the end of the
    15:59 bar's interval, not a tradable minute of its own).
    """
    if frame.empty:
        return frame
    local = frame.index.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    open_min = 9 * 60 + 30
    close_min = 16 * 60
    return frame.loc[(minutes >= open_min) & (minutes < close_min)]


def save_year(frame: pd.DataFrame, ticker: str, year: int, *, root: Path | str = DATA_BASE_PATH) -> Path:
    """Persist one ticker-year. Overwrites: a re-fetch is the correction path."""
    path = bars_path(ticker, year, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, compression="gzip", index_label="t")
    return path


def load_minutes(
    tickers: list[str], *, years: list[int], root: Path | str = DATA_BASE_PATH
) -> dict[str, pd.DataFrame]:
    """{ticker: concatenated UTC-indexed frame} over `years`. Missing ticker-years are simply
    absent — the caller reports coverage rather than silently averaging over a hole. A file
    that exists but cannot be parsed raises: silent corruption is worse than a crash."""
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        parts = []
        for year in years:
            path = bars_path(ticker, year, root=root)
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path, index_col="t", parse_dates=["t"])
                missing = [c for c in COLUMNS if c not in frame.columns]
                if missing:
                    raise ValueError(f"Spalten fehlen: {missing}")
            except Exception as err:
                raise ValueError(f"{ticker} {year} nicht lesbar ({path}): {err}") from err
            if frame.index.tz is None:
                frame.index = frame.index.tz_localize("UTC")
            parts.append(frame[list(COLUMNS)])
        if parts:
            out[ticker] = pd.concat(parts).sort_index()
    return out


def fetch_minute_year(ticker: str, year: int) -> pd.DataFrame:
    """All regular-session minute bars of one ticker-year, following Alpaca's paging.

    Raises MinuteBarError on any non-200 so the bulk script can retry that ticker-year
    instead of writing a truncated file.
    """
    import httpx

    from equity_scout.alpaca_broker import DATA_BASE, auth_headers

    pages: list[pd.DataFrame] = []
    token: str | None = None
    with httpx.Client(headers=auth_headers(), timeout=60.0) as client:
        while True:
            params = {
                "symbols": ticker,
                "timeframe": "1Min",
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "feed": FEED,
                "limit": PAGE_LIMIT,
            }
            if token:
                params["page_token"] = token
            response = client.get(f"{DATA_BASE}/stocks/bars", params=params)
            if response.status_code != 200:
                raise MinuteBarError(
                    f"{ticker} {year}: HTTP {response.status_code} {response.text[:160]}"
                )
            frame, token = parse_bars_page(response.json(), ticker)
            if not frame.empty:
                pages.append(frame)
            if not token:
                break
    if not pages:
        return pd.DataFrame(columns=list(COLUMNS))
    return regular_session_only(pd.concat(pages).sort_index())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_minute_bars.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/data/minute_bars.py tests/test_minute_bars.py
git commit -m "feat(data): minute-bar store for the signal matrix (Alpaca SIP history)"
```

---

### Task 2: Bulk download script + the minute universe

**Files:**
- Create: `scripts/fetch_minute_history.py`
- Modify: `.gitignore` (the bar store must never be committed)
- Test: `tests/test_fetch_minute_history.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch_minute_history.py`:

```python
"""Bulk minute download: resumable, honest about gaps, never silently partial."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.fetch_minute_history import MINUTE_UNIVERSE, missing_jobs, summarise_coverage


def test_universe_is_liquid_and_deduplicated():
    assert len(MINUTE_UNIVERSE) == len(set(MINUTE_UNIVERSE))
    assert 30 <= len(MINUTE_UNIVERSE) <= 60
    assert "SPY" in MINUTE_UNIVERSE and "AAPL" in MINUTE_UNIVERSE


def test_missing_jobs_lists_only_absent_ticker_years(tmp_path):
    (tmp_path / "AAPL-2024.csv.gz").write_bytes(b"")
    jobs = missing_jobs(["AAPL", "MSFT"], [2024], root=tmp_path)
    assert jobs == [("MSFT", 2024)]


def test_summarise_coverage_counts_rows_and_flags_thin_years(tmp_path):
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]},
        index=pd.to_datetime(["2024-01-02T14:30:00Z"]),
    )
    frame.to_csv(tmp_path / "AAPL-2024.csv.gz", compression="gzip", index_label="t")
    rows = summarise_coverage(["AAPL"], [2024], root=tmp_path)
    assert rows == [{"ticker": "AAPL", "year": 2024, "bars": 1, "thin": True}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch_minute_history.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.fetch_minute_history'`

- [ ] **Step 3: Implement `scripts/fetch_minute_history.py`**

```python
#!/usr/bin/env python3
"""Bulk-download the minute-bar universe for the signal matrix (resumable).

Measured 2026-08-17: ~19k bars/s, i.e. ~5 s per ticker-year -> the full universe over
2016-2026 lands in roughly 45 minutes. Resumable by design: a ticker-year that already has a
file is skipped, so an interrupted run continues where it stopped.

Universe choice — deliberately the MOST liquid names, and that is a feature, not a
convenience: this matrix asks whether a pattern beats its TRADING COSTS. Mega-caps and large
ETFs are where costs are lowest, so a signal that fails here fails everywhere more expensive.
The reverse does not hold, and Task 8's write-up says so.

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

from equity_scout.data.minute_bars import (
    DATA_BASE_PATH,
    MinuteBarError,
    bars_path,
    fetch_minute_year,
    save_year,
)

# 21 ETFs (the depot's own basket, so matrix findings can speak to the sleeves) + 29 mega-caps
# across sectors. Fixed list, not a screen: a screen would make the universe a moving target
# and the matrix uncomparable between runs.
MINUTE_UNIVERSE: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA", "IEF", "TLT", "GLD", "SLV", "VEU", "EEM",
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "VNQ",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "UNH", "XOM", "JNJ", "WMT", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
    "KO", "PEP", "COST", "ADBE", "CRM", "AMD", "NFLX", "INTC", "CSCO",
)
FULL_YEARS = tuple(range(2016, 2027))
THIN_YEAR_BARS = 50_000  # a full ticker-year is ~98k regular-session bars; below this = gap


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
        missing = missing_jobs(args.tickers, args.years)
        print(f"fehlend: {len(missing)} Ticker-Jahre")
        return 0

    jobs = missing_jobs(args.tickers, args.years)
    print(f"{len(jobs)} Ticker-Jahre zu laden (vorhandene werden übersprungen)")
    started, failures = time.time(), []
    for i, (ticker, year) in enumerate(jobs, start=1):
        try:
            frame = fetch_minute_year(ticker, year)
        except MinuteBarError as err:
            # Loud and recorded: a truncated file would poison every later measurement,
            # so nothing is written and the pair stays on the resume list.
            print(f"  FEHLER {ticker} {year}: {err}", file=sys.stderr)
            failures.append((ticker, year))
            continue
        if frame.empty:
            print(f"  leer {ticker} {year} — nicht gespeichert (kein Handel/kein Zugang)")
            continue
        save_year(frame, ticker, year)
        elapsed = time.time() - started
        print(f"  [{i}/{len(jobs)}] {ticker} {year}: {len(frame):,} Bars "
              f"({elapsed / i:.1f}s/Job, ~{(len(jobs) - i) * elapsed / i / 60:.0f} min übrig)")
    if failures:
        print(f"\n{len(failures)} Ticker-Jahre fehlgeschlagen — Skript erneut ausführen:")
        for ticker, year in failures[:20]:
            print(f"  {ticker} {year}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Keep the bar store out of git**

Append to `.gitignore`:

```
# Minute-bar store for the signal matrix: ~50 tickers x 11 years, several GB. Reproducible
# via scripts/fetch_minute_history.py, so it is derived data, not source.
data/minutes/
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_fetch_minute_history.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Live smoke on ONE ticker-year, then check coverage**

Run: `set -a; . ./.env; set +a; uv run python scripts/fetch_minute_history.py --tickers SPY --years 2024`
Expected: `SPY 2024: ~98,000 Bars`, one file at `data/minutes/SPY-2024.csv.gz` around 1-2 MB.
Run: `uv run python scripts/fetch_minute_history.py --tickers SPY --years 2024 --coverage`
Expected: 1 ticker-year, not flagged thin.

- [ ] **Step 7: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/fetch_minute_history.py tests/test_fetch_minute_history.py .gitignore
git commit -m "feat(data): resumable bulk download of the minute universe"
```

---

### Task 3: Session-aware resampling (the time-slice axis)

**Files:**
- Create: `src/equity_scout/matrix/__init__.py`, `src/equity_scout/matrix/timeframes.py`
- Test: `tests/test_timeframes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timeframes.py`:

```python
"""Resampling 1-minute bars to k minutes without welding sessions together."""
import pandas as pd

from equity_scout.matrix.timeframes import BAR_MINUTES, resample_bars


def _minutes(day: str, count: int, start_utc: str = "14:30") -> pd.DataFrame:
    index = pd.date_range(f"{day}T{start_utc}:00Z", periods=count, freq="1min")
    return pd.DataFrame(
        {"open": range(1, count + 1), "high": range(2, count + 2),
         "low": range(0, count), "close": range(1, count + 1),
         "volume": [100] * count},
        index=index, dtype=float,
    )


def test_five_minute_bars_aggregate_ohlcv_correctly():
    out = resample_bars(_minutes("2024-01-02", 10), 5)
    assert len(out) == 2
    first = out.iloc[0]
    assert first["open"] == 1.0 and first["close"] == 5.0
    assert first["high"] == 6.0 and first["low"] == 0.0
    assert first["volume"] == 500.0


def test_a_bar_never_spans_two_trading_days():
    frame = pd.concat([_minutes("2024-01-02", 3), _minutes("2024-01-03", 3)])
    out = resample_bars(frame, 5)
    # 3 minutes per day: each day yields its own partial bar, never one merged bar
    assert len(out) == 2
    assert out.index[0].date().isoformat() == "2024-01-02"
    assert out.index[1].date().isoformat() == "2024-01-03"


def test_partial_trailing_bar_is_dropped_when_incomplete_is_false():
    out = resample_bars(_minutes("2024-01-02", 7), 5, keep_incomplete=False)
    assert len(out) == 1  # the 2-minute remainder is not a 5-minute bar


def test_one_minute_passthrough_is_identity():
    frame = _minutes("2024-01-02", 4)
    assert resample_bars(frame, 1).equals(frame)


def test_the_axis_values_are_the_ones_the_matrix_uses():
    assert BAR_MINUTES == (1, 5, 15, 30, 60)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_timeframes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'equity_scout.matrix'`

- [ ] **Step 3: Implement the package and resampler**

Create `src/equity_scout/matrix/__init__.py`:

```python
"""Signal matrix: one measurement space over signals, time slices, holds, thresholds, costs.

The point of this package is a REGION, never a winning cell — see
docs/superpowers/plans/2026-08-17-signal-matrix-plateaus.md.
"""
```

Create `src/equity_scout/matrix/timeframes.py`:

```python
"""Resample 1-minute bars onto the matrix's time-slice axis.

Grouping by trading DAY before resampling is not a detail: a plain `resample("5min")` over a
multi-day frame produces bars that span the overnight gap (15:59 close welded to next day's
09:30 open). Such a bar carries the overnight move inside an intraday signal, which is exactly
the confound the ORB studies had to strip out by hand.
"""
from __future__ import annotations

import pandas as pd

BAR_MINUTES = (1, 5, 15, 30, 60)  # the matrix's time-slice axis
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample_bars(
    bars: pd.DataFrame, minutes: int, *, keep_incomplete: bool = True
) -> pd.DataFrame:
    """1-minute OHLCV -> `minutes`-bars, never crossing a trading day.

    `keep_incomplete=False` drops a trailing bar that had fewer than `minutes` source bars —
    use it when a signal's economics depend on the bar being a full interval.
    """
    if bars.empty or minutes == 1:
        return bars
    local_day = bars.index.tz_convert("America/New_York").date
    pieces = []
    for _, group in bars.groupby(local_day):
        agg = group.resample(f"{minutes}min", origin="start").agg(_AGG)
        if not keep_incomplete:
            counts = group.resample(f"{minutes}min", origin="start").size()
            agg = agg.loc[counts == minutes]
        pieces.append(agg.dropna(subset=["open", "close"]))
    return pd.concat(pieces).sort_index() if pieces else bars.iloc[0:0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timeframes.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/matrix/__init__.py src/equity_scout/matrix/timeframes.py tests/test_timeframes.py
git commit -m "feat(matrix): session-aware resampling onto the time-slice axis"
```

---

### Task 4: Signal detectors (the signal axis, incl. the untested candlestick patterns)

**Files:**
- Create: `src/equity_scout/matrix/signals.py`
- Test: `tests/test_matrix_signals.py`

Six detectors. Four re-measure rules the repo tested only on single scales; two (`hammer`,
`bullish_engulfing`) have NEVER been tested here — verified 2026-08-17, no occurrence of
hammer/engulfing/doji anywhere in the codebase.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_matrix_signals.py`:

```python
"""Signal detectors: each fires on the constructed case and stays silent otherwise."""
import pandas as pd

from equity_scout.matrix.signals import SIGNALS, bullish_engulfing, hammer, momentum_up, reversal_down, volume_spike


def _bars(rows: list[dict]) -> pd.DataFrame:
    index = pd.date_range("2024-01-02T14:30:00Z", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, index=index, dtype=float)


def test_registry_exposes_every_detector_with_its_thresholds():
    assert set(SIGNALS) == {
        "momentum_up", "reversal_down", "volume_spike", "hammer", "bullish_engulfing", "gap_up",
    }
    for name, spec in SIGNALS.items():
        assert callable(spec.detect), name
        assert len(spec.thresholds) >= 3, name  # a one-point axis cannot form a plateau


def test_momentum_up_fires_only_above_the_threshold():
    bars = _bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 10},
        {"open": 100, "high": 103, "low": 100, "close": 103, "volume": 10},  # +3 %
        {"open": 103, "high": 103.1, "low": 103, "close": 103.1, "volume": 10},  # +0.1 %
    ])
    fired = momentum_up(bars, threshold=0.02)
    assert fired.tolist() == [False, True, False]


def test_reversal_down_fires_after_a_drop():
    bars = _bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 10},
        {"open": 100, "high": 100, "low": 96, "close": 97, "volume": 10},  # -3 %
    ])
    assert reversal_down(bars, threshold=0.02).tolist() == [False, True]


def test_volume_spike_needs_a_multiple_of_the_trailing_median():
    rows = [{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 100} for _ in range(25)]
    rows[-1]["volume"] = 400  # 4x the median
    fired = volume_spike(_bars(rows), threshold=3.0)
    assert fired.iloc[-1] and not fired.iloc[-2]


def test_hammer_needs_a_long_lower_wick_and_a_small_body():
    bars = _bars([
        # body 100->100.2 (0.2), lower wick 100->97 (3.0): wick >> body, close near the high
        {"open": 100, "high": 100.3, "low": 97.0, "close": 100.2, "volume": 10},
        # a plain up-bar is not a hammer
        {"open": 100, "high": 103, "low": 99.9, "close": 102.9, "volume": 10},
    ])
    assert hammer(bars, threshold=2.0).tolist() == [True, False]


def test_bullish_engulfing_needs_the_previous_body_covered():
    bars = _bars([
        {"open": 101, "high": 101, "low": 99, "close": 99, "volume": 10},   # down bar 101->99
        {"open": 98.5, "high": 102, "low": 98.4, "close": 101.5, "volume": 10},  # engulfs it
        {"open": 101.5, "high": 102, "low": 101, "close": 101.6, "volume": 10},  # tiny up bar
    ])
    assert bullish_engulfing(bars, threshold=1.0).tolist() == [False, True, False]


def test_no_detector_looks_into_the_future():
    # Shuffling everything AFTER row 5 must not change the first five decisions: a detector
    # that peeked would produce different flags. This is the plan's look-ahead guard.
    rows = [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 10 + i}
        for i in range(20)
    ]
    early = _bars(rows[:5])
    for name, spec in SIGNALS.items():
        full = spec.detect(_bars(rows), threshold=spec.thresholds[0])
        head = spec.detect(early, threshold=spec.thresholds[0])
        assert full.iloc[:5].tolist() == head.tolist(), name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_matrix_signals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'equity_scout.matrix.signals'`

- [ ] **Step 3: Implement `src/equity_scout/matrix/signals.py`**

```python
"""Signal detectors for the matrix — one pure function per pattern.

Contract every detector honours: it returns a boolean Series aligned to `bars`, and the flag
at row i uses ONLY rows <= i. `test_no_detector_looks_into_the_future` pins that: truncating
the frame must not change earlier flags. Without that guarantee a whole matrix of results is
worthless, and look-ahead has bitten this repo before (the 15:57-intraday-as-close incident).

Threshold axes are tuples, not single values, because the plan's unit of evidence is a
PLATEAU: a rule that works at exactly one threshold and fails at its neighbours is noise.
Every axis therefore has at least three points.

Two of these six have never been measured in this repo before (verified 2026-08-17): `hammer`
and `bullish_engulfing` — the candlestick family. The other four re-measure rules that were
only ever tested on a single time slice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

VOLUME_LOOKBACK = 20  # bars for the trailing median in volume_spike


@dataclass(frozen=True)
class SignalSpec:
    detect: Callable[..., pd.Series]
    thresholds: tuple[float, ...]
    description: str


def _body(bars: pd.DataFrame) -> pd.Series:
    return (bars["close"] - bars["open"]).abs()


def momentum_up(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar closed `threshold` above its own open — 'it is running right now'."""
    change = bars["close"] / bars["open"] - 1.0
    return (change >= threshold).fillna(False)


def reversal_down(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar closed `threshold` BELOW its open — the liquidity-provision setup: buy what
    just got dumped. The 5-minute study measured this effect at t = -32.1; the open question
    is only whether any (slice, hold, cost) region keeps it positive after costs."""
    change = bars["close"] / bars["open"] - 1.0
    return (change <= -threshold).fillna(False)


def volume_spike(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Volume at least `threshold` times the trailing median (shifted, so the current bar is
    not part of its own baseline)."""
    median = bars["volume"].rolling(VOLUME_LOOKBACK).median().shift(1)
    return (bars["volume"] >= threshold * median).fillna(False)


def hammer(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """Long lower wick, small body, close in the upper part of the range.

    `threshold` is the minimum lower-wick-to-body ratio. Degenerate bars (body 0) are excluded
    rather than treated as infinite ratio — a doji is a different pattern and gets no free pass.
    """
    body = _body(bars)
    lower_wick = bars[["open", "close"]].min(axis=1) - bars["low"]
    span = (bars["high"] - bars["low"]).replace(0.0, pd.NA)
    close_position = (bars["close"] - bars["low"]) / span
    return (
        (body > 0) & (lower_wick >= threshold * body) & (close_position >= 0.6)
    ).fillna(False)


def bullish_engulfing(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """An up bar whose body covers the previous DOWN bar's body by at least `threshold`x."""
    prev_open, prev_close = bars["open"].shift(1), bars["close"].shift(1)
    prev_body = (prev_open - prev_close).abs()
    covered = (bars["close"] >= prev_open) & (bars["open"] <= prev_close)
    return (
        (prev_close < prev_open)  # previous bar was down
        & (bars["close"] > bars["open"])  # this bar is up
        & covered
        & (_body(bars) >= threshold * prev_body)
        & (prev_body > 0)
    ).fillna(False)


def gap_up(bars: pd.DataFrame, *, threshold: float) -> pd.Series:
    """This bar opened `threshold` above the previous bar's close (intraday gap/jump)."""
    gap = bars["open"] / bars["close"].shift(1) - 1.0
    return (gap >= threshold).fillna(False)


SIGNALS: dict[str, SignalSpec] = {
    "momentum_up": SignalSpec(momentum_up, (0.002, 0.005, 0.01, 0.02), "Bar schließt X über eigenem Open"),
    "reversal_down": SignalSpec(reversal_down, (0.002, 0.005, 0.01, 0.02), "Bar schließt X unter eigenem Open"),
    "volume_spike": SignalSpec(volume_spike, (2.0, 3.0, 5.0, 8.0), "Volumen X-fach über Trailing-Median"),
    "hammer": SignalSpec(hammer, (1.5, 2.0, 3.0, 4.0), "Langer unterer Schatten, kleiner Körper"),
    "bullish_engulfing": SignalSpec(bullish_engulfing, (1.0, 1.5, 2.0, 3.0), "Körper verschlingt Vorgänger"),
    "gap_up": SignalSpec(gap_up, (0.002, 0.005, 0.01, 0.02), "Open X über vorherigem Close"),
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_matrix_signals.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/matrix/signals.py tests/test_matrix_signals.py
git commit -m "feat(matrix): six look-ahead-safe signal detectors incl. candlestick family"
```

---

### Task 5: Cell evaluation and the grid run

**Files:**
- Create: `src/equity_scout/matrix/grid.py`
- Test: `tests/test_matrix_grid.py`

**Files:**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_matrix_grid.py`:

```python
"""Cell evaluation: honest statistics, costs as a first-class axis, hard sample floor."""
import pandas as pd

from equity_scout.matrix.grid import (
    COST_BPS,
    HOLD_BARS,
    HOLD_OUT_START,
    MIN_TRADES,
    evaluate_cell,
    split_periods,
)


def _bars(closes: list[float], day: str = "2024-01-02") -> pd.DataFrame:
    index = pd.date_range(f"{day}T14:30:00Z", periods=len(closes), freq="5min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [100] * len(closes)},
        index=index, dtype=float,
    )


def test_evaluate_cell_measures_the_forward_move_after_costs():
    # every signal bar is followed by exactly +100 bp; 10 bp roundtrip leaves 90 bp
    bars = _bars([100.0, 101.0] * 30)
    signal = pd.Series([True, False] * 30, index=bars.index)
    cell = evaluate_cell(bars, signal, hold_bars=1, cost_bps=10.0)
    assert cell["n"] == 30
    assert round(cell["gross_bp"]) == 100
    assert round(cell["net_bp"]) == 90
    assert cell["hit_rate"] == 1.0


def test_a_cell_below_the_sample_floor_reports_none_not_a_number():
    bars = _bars([100.0, 101.0])
    signal = pd.Series([True, False], index=bars.index)
    cell = evaluate_cell(bars, signal, hold_bars=1, cost_bps=10.0)
    assert cell["n"] == 1
    assert cell["net_bp"] is None and cell["t"] is None  # 1 < MIN_TRADES


def test_trades_never_run_past_the_end_of_the_series():
    bars = _bars([100.0] * 5)
    signal = pd.Series([False, False, False, False, True], index=bars.index)
    cell = evaluate_cell(bars, signal, hold_bars=3, cost_bps=0.0)
    assert cell["n"] == 0  # the last bar cannot be held for 3 more


def test_a_bar_is_never_entered_twice_while_a_trade_is_open():
    # signals on every bar, hold 3 -> non-overlapping entries only
    bars = _bars([100.0] * 30)
    signal = pd.Series([True] * 30, index=bars.index)
    cell = evaluate_cell(bars, signal, hold_bars=3, cost_bps=0.0)
    assert cell["n"] == 9  # floor((30-1)/3), no pyramiding


def test_split_periods_keeps_the_hold_out_after_the_search_window():
    bars = pd.concat([_bars([100.0] * 3, day="2022-06-01"), _bars([100.0] * 3, day="2024-06-03")])
    in_sample, held_out = split_periods(bars)
    assert len(in_sample) == 3 and len(held_out) == 3
    assert str(held_out.index[0].date()) >= HOLD_OUT_START


def test_the_axes_are_the_documented_ones():
    assert HOLD_BARS == (1, 2, 3, 6, 12)
    assert COST_BPS == (2.0, 4.0, 10.0, 20.0)
    assert MIN_TRADES == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_matrix_grid.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'equity_scout.matrix.grid'`

- [ ] **Step 3: Implement `src/equity_scout/matrix/grid.py`**

```python
"""One matrix cell = one (signal, threshold, bar_minutes, hold_bars, cost_bps) measurement.

Design decisions that keep the numbers honest:

- **Costs are an AXIS, not a constant.** Every rule this repo ever tested died on costs, not
  on significance. A matrix that fixes one cost level hides exactly the thing that decides.
- **No pyramiding.** While a trade is open, later signals are ignored. Overlapping entries
  would multiply the same market move into several "independent" observations and inflate t.
- **A hard sample floor.** Below MIN_TRADES a cell reports None instead of a number. A cell
  with 12 trades and a big mean is the champion-artifact failure mode (AUC 0.6195 on 220 rows
  that became 0.5152 on 3281).
- **Entry at the signal bar's close, exit at the close `hold_bars` later.** The signal is
  known only once its bar has closed; entering at that close is the earliest honest fill. Both
  legs pay `cost_bps / 2`.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HOLD_BARS = (1, 2, 3, 6, 12)  # in units of the cell's own bar_minutes
COST_BPS = (2.0, 4.0, 10.0, 20.0)  # roundtrip; 4 bp = liquid names, 10 bp = realistic
MIN_TRADES = 200  # below this a cell is not evidence
HOLD_OUT_START = "2023-01-01"  # opened ONCE, at the end of the plan


def split_periods(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(search window, hold-out). The hold-out exists so a plateau found by searching a large
    space can be checked on data the search never touched."""
    cut = pd.Timestamp(HOLD_OUT_START, tz="UTC")
    return bars.loc[bars.index < cut], bars.loc[bars.index >= cut]


def evaluate_cell(
    bars: pd.DataFrame, signal: pd.Series, *, hold_bars: int, cost_bps: float
) -> dict:
    """Forward return of every non-overlapping signal entry, gross and after costs.

    Returns n / gross_bp / net_bp / t / hit_rate. n is ALWAYS reported; the statistics come
    back as None when n < MIN_TRADES, so a thin cell cannot masquerade as a finding.
    """
    closes = bars["close"].to_numpy(dtype=float)
    flags = signal.to_numpy(dtype=bool)
    returns_bp: list[float] = []
    i, last = 0, len(closes) - hold_bars
    while i < last:
        if flags[i] and closes[i] > 0:
            exit_price = closes[i + hold_bars]
            returns_bp.append((exit_price / closes[i] - 1.0) * 10_000.0)
            i += hold_bars  # no pyramiding: the position occupies its holding window
        else:
            i += 1
    n = len(returns_bp)
    if n < MIN_TRADES:
        return {"n": n, "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None}
    values = np.asarray(returns_bp)
    net = values - cost_bps
    std = float(net.std(ddof=1))
    t_stat = float(net.mean()) / (std / math.sqrt(n)) if std > 0 else None
    return {
        "n": n,
        "gross_bp": float(values.mean()),
        "net_bp": float(net.mean()),
        "t": t_stat,
        "hit_rate": float((net > 0).mean()),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_matrix_grid.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/matrix/grid.py tests/test_matrix_grid.py
git commit -m "feat(matrix): cell evaluation with costs as an axis and a hard sample floor"
```

---

### Task 6: Plateau detection (the point of the whole plan)

**Files:**
- Create: `src/equity_scout/matrix/plateau.py`
- Test: `tests/test_plateau.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plateau.py`:

```python
"""Plateaus: connected regions that survive their own neighbourhood, not winning cells."""
from equity_scout.matrix.plateau import MIN_PLATEAU_CELLS, PLATEAU_T, find_plateaus


def _cell(signal, threshold, bar_minutes, hold_bars, cost_bps, net_bp, t, n=1000):
    return {
        "signal": signal, "threshold": threshold, "bar_minutes": bar_minutes,
        "hold_bars": hold_bars, "cost_bps": cost_bps,
        "net_bp": net_bp, "t": t, "n": n, "hit_rate": 0.5,
    }


def test_an_isolated_winning_cell_is_not_a_plateau():
    cells = [_cell("momentum_up", 0.005, 5, 3, 4.0, net_bp=8.0, t=4.0)]
    assert find_plateaus(cells) == []


def test_a_connected_region_of_winners_is_a_plateau():
    # neighbours along the threshold axis AND the hold axis -> 4 connected cells
    cells = [
        _cell("reversal_down", 0.005, 5, 2, 4.0, 6.0, 3.0),
        _cell("reversal_down", 0.005, 5, 3, 4.0, 7.0, 3.5),
        _cell("reversal_down", 0.01, 5, 2, 4.0, 5.5, 3.1),
        _cell("reversal_down", 0.01, 5, 3, 4.0, 6.2, 3.3),
    ]
    plateaus = find_plateaus(cells)
    assert len(plateaus) == 1
    found = plateaus[0]
    assert found["size"] == 4
    assert found["signal"] == "reversal_down"
    assert found["bar_minutes"] == [5]
    assert found["thresholds"] == [0.005, 0.01]
    assert round(found["median_net_bp"], 1) == 6.1
    assert found["worst_t"] == 3.0


def test_cells_of_different_signals_never_merge():
    cells = [
        _cell("hammer", 2.0, 5, 3, 4.0, 6.0, 3.0),
        _cell("momentum_up", 0.005, 5, 3, 4.0, 6.0, 3.0),
    ]
    assert find_plateaus(cells) == []  # two singletons, not one pair


def test_a_cell_below_the_t_bar_breaks_the_region():
    cells = [
        _cell("gap_up", 0.002, 5, 2, 4.0, 6.0, 3.0),
        _cell("gap_up", 0.005, 5, 2, 4.0, 6.0, 1.0),  # t too low -> not a member
        _cell("gap_up", 0.01, 5, 2, 4.0, 6.0, 3.0),
    ]
    assert find_plateaus(cells) == []  # the middle cell separates two singletons


def test_none_valued_cells_are_ignored_not_treated_as_zero():
    cells = [
        _cell("hammer", 2.0, 5, 2, 4.0, None, None, n=12),
        _cell("hammer", 3.0, 5, 2, 4.0, None, None, n=12),
        _cell("hammer", 4.0, 5, 2, 4.0, None, None, n=12),
    ]
    assert find_plateaus(cells) == []


def test_the_bars_are_the_documented_ones():
    assert MIN_PLATEAU_CELLS == 4
    assert PLATEAU_T == 2.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_plateau.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'equity_scout.matrix.plateau'`

- [ ] **Step 3: Implement `src/equity_scout/matrix/plateau.py`**

```python
"""Find PLATEAUS in the cell grid — the unit of evidence this whole plan is built around.

The reasoning, in one paragraph: searching a large space and taking the best cell is
guaranteed to find something. With ~4 signals x 4 thresholds x 5 slices x 5 holds x 4 cost
levels the space has hundreds of cells, and at the 5 % level pure chance produces a
double-digit number of "significant" winners. That failure mode already cost this project five
weeks (the entry champion that claimed AUC 0.6195 on 220 rows and delivered 0.5152 on 3281).
A plateau is the answer: a rule must work across a CONNECTED region of its own parameter
neighbourhood. Noise does not come in connected blocks; a real mechanism does, because a
mechanism that works at a 0.5 % threshold and a 3-bar hold does not stop working at 1 % and 2
bars.

Adjacency is defined per axis: two cells are neighbours when they sit on the same signal and
the same cost level, and differ by exactly one step in exactly one of (threshold,
bar_minutes, hold_bars). Cost is NOT an adjacency axis — a rule that only survives at 2 bp is
not robust, it is a different economic claim, so each cost level gets its own regions.
"""
from __future__ import annotations

from statistics import median

MIN_PLATEAU_CELLS = 4  # fewer cells cannot show that neighbours agree
PLATEAU_T = 2.0  # every member cell must clear this on its own


def _axis_values(cells: list[dict], key: str) -> list:
    return sorted({cell[key] for cell in cells})


def _members(cells: list[dict]) -> list[dict]:
    """Cells that qualify at all: measurable, positive after costs, individually significant."""
    return [
        cell for cell in cells
        if cell.get("net_bp") is not None and cell.get("t") is not None
        and cell["net_bp"] > 0 and cell["t"] >= PLATEAU_T
    ]


def find_plateaus(cells: list[dict]) -> list[dict]:
    """Connected regions of qualifying cells, one summary dict per region.

    Regions smaller than MIN_PLATEAU_CELLS are dropped — that is the whole guard against
    single lucky cells.
    """
    members = _members(cells)
    if not members:
        return []
    steps = {
        "threshold": _axis_values(cells, "threshold"),
        "bar_minutes": _axis_values(cells, "bar_minutes"),
        "hold_bars": _axis_values(cells, "hold_bars"),
    }
    index = {
        (c["signal"], c["cost_bps"], c["threshold"], c["bar_minutes"], c["hold_bars"]): c
        for c in members
    }

    def neighbours(key):
        signal, cost, threshold, minutes, hold = key
        current = {"threshold": threshold, "bar_minutes": minutes, "hold_bars": hold}
        for axis, values in steps.items():
            position = values.index(current[axis])
            for offset in (-1, 1):
                nxt = position + offset
                if 0 <= nxt < len(values):
                    moved = dict(current)
                    moved[axis] = values[nxt]
                    candidate = (signal, cost, moved["threshold"], moved["bar_minutes"],
                                 moved["hold_bars"])
                    if candidate in index:
                        yield candidate

    seen: set = set()
    plateaus: list[dict] = []
    for key in index:
        if key in seen:
            continue
        region, stack = [], [key]
        seen.add(key)
        while stack:  # flood fill
            current = stack.pop()
            region.append(index[current])
            for candidate in neighbours(current):
                if candidate not in seen:
                    seen.add(candidate)
                    stack.append(candidate)
        if len(region) < MIN_PLATEAU_CELLS:
            continue
        plateaus.append({
            "signal": region[0]["signal"],
            "cost_bps": region[0]["cost_bps"],
            "size": len(region),
            "thresholds": sorted({c["threshold"] for c in region}),
            "bar_minutes": sorted({c["bar_minutes"] for c in region}),
            "hold_bars": sorted({c["hold_bars"] for c in region}),
            "median_net_bp": median(c["net_bp"] for c in region),
            "worst_net_bp": min(c["net_bp"] for c in region),
            "worst_t": min(c["t"] for c in region),
            "total_trades": sum(c["n"] for c in region),
        })
    return sorted(plateaus, key=lambda p: (-p["size"], -p["median_net_bp"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plateau.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/matrix/plateau.py tests/test_plateau.py
git commit -m "feat(matrix): plateau detection via flood fill over the cell grid"
```

---

### Task 7: The study runner

**Files:**
- Create: `scripts/run_signal_matrix.py`
- Test: `tests/test_run_signal_matrix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_signal_matrix.py`:

```python
"""Matrix runner: builds every cell, keeps the hold-out shut until asked."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_signal_matrix import build_cells, expected_cell_count


def _bars(n: int, day: str = "2022-06-01") -> pd.DataFrame:
    index = pd.date_range(f"{day}T14:30:00Z", periods=n, freq="1min")
    closes = [100.0 + (i % 7) * 0.1 for i in range(n)]
    return pd.DataFrame(
        {"open": closes, "high": [c + 0.05 for c in closes], "low": [c - 0.05 for c in closes],
         "close": closes, "volume": [100 + i % 50 for i in range(n)]},
        index=index, dtype=float,
    )


def test_build_cells_covers_the_whole_declared_axis_product():
    cells = build_cells({"AAA": _bars(400)}, bar_minutes=(1, 5), signals=("momentum_up",))
    # 1 signal x 4 thresholds x 2 slices x 5 holds x 4 cost levels
    assert len(cells) == expected_cell_count(n_signals=1, n_slices=2)
    assert {c["signal"] for c in cells} == {"momentum_up"}
    for cell in cells:
        assert set(cell) >= {"signal", "threshold", "bar_minutes", "hold_bars", "cost_bps", "n"}


def test_cells_carry_the_ticker_coverage_they_were_measured_on():
    cells = build_cells({"AAA": _bars(400), "BBB": _bars(400)}, bar_minutes=(5,),
                        signals=("momentum_up",))
    assert all(cell["tickers"] == 2 for cell in cells)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_signal_matrix.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.run_signal_matrix'`

- [ ] **Step 3: Implement `scripts/run_signal_matrix.py`**

```python
#!/usr/bin/env python3
"""Run the signal matrix, find plateaus in the search window, then open the hold-out ONCE.

Nico's framing (2026-08-17): not one parameter and not one time slice, but the whole space —
and the unit of interest is "a selection of winning cells", i.e. a region, not a champion.
This script produces exactly that, plus the one guard the region logic cannot supply on its
own: a period the search never saw.

Discipline this script enforces:
1. Plateaus are searched ONLY on bars before grid.HOLD_OUT_START.
2. The hold-out is then measured for the surviving plateaus and NOTHING else — no re-search,
   no threshold tuning "while we are in there". Every look at the hold-out is printed and
   goes into the research doc, so a second look is visible.
3. Cells below grid.MIN_TRADES report n and nothing else.

Usage:
    uv run python scripts/run_signal_matrix.py                    # full universe
    uv run python scripts/run_signal_matrix.py --tickers SPY AAPL --years 2022 2023
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from equity_scout.data.minute_bars import load_minutes
from equity_scout.matrix.grid import COST_BPS, HOLD_BARS, HOLD_OUT_START, evaluate_cell, split_periods
from equity_scout.matrix.plateau import find_plateaus
from equity_scout.matrix.signals import SIGNALS
from equity_scout.matrix.timeframes import BAR_MINUTES, resample_bars

from scripts.fetch_minute_history import FULL_YEARS, MINUTE_UNIVERSE


def expected_cell_count(*, n_signals: int, n_slices: int) -> int:
    """Axis product, used by the test and printed in the doc so the space size is explicit."""
    thresholds = sum(len(SIGNALS[name].thresholds) for name in list(SIGNALS)[:n_signals])
    return thresholds * n_slices * len(HOLD_BARS) * len(COST_BPS)


def build_cells(
    bars_by_ticker: dict[str, pd.DataFrame],
    *,
    bar_minutes: tuple[int, ...] = BAR_MINUTES,
    signals: tuple[str, ...] = tuple(SIGNALS),
) -> list[dict]:
    """Every cell of the declared axis product, pooled across tickers.

    Pooling is deliberate: a per-ticker matrix would multiply the space by 50 and invite
    exactly the cherry-picking this design exists to prevent. The pool is one measurement of
    the MECHANISM; per-ticker behaviour is a later question.
    """
    cells: list[dict] = []
    for minutes in bar_minutes:
        resampled = {
            ticker: resample_bars(bars, minutes, keep_incomplete=False)
            for ticker, bars in bars_by_ticker.items()
        }
        for name in signals:
            spec = SIGNALS[name]
            for threshold in spec.thresholds:
                flags = {t: spec.detect(b, threshold=threshold) for t, b in resampled.items()}
                for hold in HOLD_BARS:
                    for cost in COST_BPS:
                        pooled = [
                            evaluate_cell(resampled[t], flags[t], hold_bars=hold, cost_bps=cost)
                            for t in resampled
                        ]
                        cells.append(_pool(pooled, name, threshold, minutes, hold, cost,
                                           len(resampled)))
    return cells


def _pool(per_ticker: list[dict], signal, threshold, minutes, hold, cost, tickers) -> dict:
    """Trade-weighted pool of per-ticker cells. A cell that fell under the floor contributes
    its trade count and nothing else, so coverage stays visible."""
    usable = [c for c in per_ticker if c["net_bp"] is not None]
    total_n = sum(c["n"] for c in per_ticker)
    out = {
        "signal": signal, "threshold": threshold, "bar_minutes": minutes,
        "hold_bars": hold, "cost_bps": cost, "n": total_n, "tickers": tickers,
        "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None,
    }
    if not usable:
        return out
    weights = sum(c["n"] for c in usable)
    out["gross_bp"] = sum(c["gross_bp"] * c["n"] for c in usable) / weights
    out["net_bp"] = sum(c["net_bp"] * c["n"] for c in usable) / weights
    out["hit_rate"] = sum(c["hit_rate"] * c["n"] for c in usable) / weights
    # Pooled t from the per-ticker t's: sum(t_i * sqrt(n_i)) / sqrt(sum(n_i)) — Stouffer-style,
    # conservative because it never assumes the tickers are independent draws of one effect.
    out["t"] = sum(c["t"] * (c["n"] ** 0.5) for c in usable if c["t"] is not None) / (
        weights ** 0.5
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="*", default=list(MINUTE_UNIVERSE))
    parser.add_argument("--years", type=int, nargs="*", default=list(FULL_YEARS))
    parser.add_argument("--out", default=None, help="research doc path (default: docs/research/)")
    args = parser.parse_args()

    loaded = load_minutes(args.tickers, years=args.years)
    if not loaded:
        print("Keine Minutenbars gefunden — erst scripts/fetch_minute_history.py laufen lassen.",
              file=sys.stderr)
        return 2
    coverage = {t: len(b) for t, b in loaded.items()}
    print(f"{len(loaded)} Ticker, {sum(coverage.values()):,} Minutenbars geladen")

    search = {t: split_periods(b)[0] for t, b in loaded.items()}
    search = {t: b for t, b in search.items() if not b.empty}
    print(f"Suchfenster (vor {HOLD_OUT_START}): {sum(len(b) for b in search.values()):,} Bars")
    cells = build_cells(search)
    measurable = [c for c in cells if c["net_bp"] is not None]
    print(f"{len(cells)} Zellen gerechnet, {len(measurable)} über der Stichprobenschwelle")

    plateaus = find_plateaus(cells)
    print(f"\n{len(plateaus)} Plateau(s) im Suchfenster:")
    for p in plateaus:
        print(f"  {p['signal']} @ {p['cost_bps']:.0f}bp — {p['size']} Zellen, "
              f"Median {p['median_net_bp']:+.2f} bp, schlechtestes t {p['worst_t']:.2f}, "
              f"Slices {p['bar_minutes']}, Holds {p['hold_bars']}")

    print(f"\n=== HOLD-OUT ({HOLD_OUT_START}+) wird jetzt EINMAL geöffnet ===")
    held = {t: split_periods(b)[1] for t, b in loaded.items()}
    held = {t: b for t, b in held.items() if not b.empty}
    survivors = []
    for p in plateaus:
        confirmed = _validate(p, held)
        survivors.append(confirmed)
        verdict = "BESTÄTIGT" if confirmed["holds"] else "GEFALLEN"
        print(f"  {p['signal']} @ {p['cost_bps']:.0f}bp: {verdict} — "
              f"Median {confirmed['median_net_bp']:+.2f} bp "
              f"(Suchfenster {p['median_net_bp']:+.2f}), "
              f"{confirmed['positive_cells']}/{confirmed['cells']} Zellen positiv")

    _write_doc(args.out, coverage, cells, plateaus, survivors)
    return 0


def _validate(plateau: dict, held_out: dict[str, pd.DataFrame]) -> dict:
    """Re-measure exactly the plateau's own cells on the hold-out. No new search."""
    spec = SIGNALS[plateau["signal"]]
    results = []
    for minutes in plateau["bar_minutes"]:
        resampled = {t: resample_bars(b, minutes, keep_incomplete=False)
                     for t, b in held_out.items()}
        for threshold in plateau["thresholds"]:
            flags = {t: spec.detect(b, threshold=threshold) for t, b in resampled.items()}
            for hold in plateau["hold_bars"]:
                pooled = [
                    evaluate_cell(resampled[t], flags[t], hold_bars=hold,
                                  cost_bps=plateau["cost_bps"])
                    for t in resampled
                ]
                results.append(_pool(pooled, plateau["signal"], threshold, minutes, hold,
                                     plateau["cost_bps"], len(resampled)))
    usable = [r for r in results if r["net_bp"] is not None]
    positive = [r for r in usable if r["net_bp"] > 0]
    median_net = (
        sorted(r["net_bp"] for r in usable)[len(usable) // 2] if usable else None
    )
    return {
        "signal": plateau["signal"], "cost_bps": plateau["cost_bps"],
        "cells": len(usable), "positive_cells": len(positive),
        "median_net_bp": median_net,
        # A plateau "holds" only if the MAJORITY of its own cells stay positive out of sample.
        # One surviving cell out of nine is a coin, not a confirmation.
        "holds": bool(usable) and len(positive) >= max(1, len(usable) // 2 + 1),
    }


def _write_doc(out, coverage, cells, plateaus, survivors) -> None:
    from datetime import date

    path = Path(out or f"docs/research/{date.today().isoformat()}-signal-matrix.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Signal-Matrix: Plateaus statt Siegerzellen ({date.today().isoformat()})",
        "",
        "Reproduzierbar: `uv run python scripts/run_signal_matrix.py`. Plan:",
        "`docs/superpowers/plans/2026-08-17-signal-matrix-plateaus.md`.",
        "",
        "## Datenbasis",
        f"- {len(coverage)} Ticker, {sum(coverage.values()):,} Minutenbars (Alpaca SIP, ab 2016)",
        f"- {len(cells)} Zellen im Raum, "
        f"{len([c for c in cells if c['net_bp'] is not None])} über der Stichprobenschwelle",
        f"- Suchfenster bis {HOLD_OUT_START}, Hold-out danach — **einmal** geöffnet",
        "",
        "## Plateaus im Suchfenster",
        "",
        "| Signal | Kosten | Zellen | Median netto | schlechtestes t | Slices | Holds |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in plateaus:
        lines.append(
            f"| {p['signal']} | {p['cost_bps']:.0f} bp | {p['size']} | "
            f"{p['median_net_bp']:+.2f} bp | {p['worst_t']:.2f} | {p['bar_minutes']} | "
            f"{p['hold_bars']} |"
        )
    if not plateaus:
        lines.append("| — | — | — | — | — | — | — |")
        lines.append("")
        lines.append("**Kein Plateau gefunden.** Das ist ein Ergebnis, kein Fehler: in diesem "
                     "Raum gibt es keine zusammenhängende Region, die nach Kosten positiv und "
                     "einzeln signifikant ist.")
    lines += ["", "## Hold-out", "",
              "| Signal | Kosten | Zellen positiv | Median netto | Urteil |", "|---|---|---|---|---|"]
    for s in survivors:
        median = "—" if s["median_net_bp"] is None else f"{s['median_net_bp']:+.2f} bp"
        lines.append(
            f"| {s['signal']} | {s['cost_bps']:.0f} bp | {s['positive_cells']}/{s['cells']} | "
            f"{median} | {'BESTÄTIGT' if s['holds'] else 'GEFALLEN'} |"
        )
    if not survivors:
        lines.append("| — | — | — | — | — |")
    lines += [
        "",
        "## Grenzen dieser Messung",
        "",
        "- **Feed-Bruch:** gemessen auf SIP (konsolidiert), live handeln die Lanes IEX "
        "(~2-3 % des Volumens). Ein bestätigtes Plateau ist damit ein Kandidat, kein Live-Edge "
        "— der erste Schritt eines Folgeplans ist eine Signal-vs-Fill-Messung.",
        "- **Universum:** die 50 liquidesten Namen. Das ist der billigste Fall für Kosten; "
        "was hier scheitert, scheitert überall teurer. Die Umkehrung gilt nicht.",
        "- **Kein Hebel, kein Echtgeld.** Hebel multipliziert einen gesicherten "
        "Erwartungswert; nichts hier sichert einen.",
        "- **Nur regulärer Handel** (09:30-16:00 ET). Pre-/After-Market hat andere Spreads, "
        "eine Kostenachse von 2-20 bp würde dort nicht gelten.",
    ]
    path.write_text("\n".join(lines) + "\n")
    print(f"\nDoku geschrieben: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_run_signal_matrix.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Smoke-run on the one downloaded ticker-year**

Run: `uv run python scripts/run_signal_matrix.py --tickers SPY --years 2024`
Expected: it loads SPY 2024, reports that the SEARCH window (before 2023-01-01) is empty, and
exits 2 with the hint to fetch more years — proving the split guard works before the bulk
download exists. If SPY 2022 is present too, it produces cells and a doc.

- [ ] **Step 6: Commit**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/run_signal_matrix.py tests/test_run_signal_matrix.py
git commit -m "feat(matrix): study runner with plateau search and single hold-out look"
```

---

### Task 8: Full run, research doc, and the honest verdict

**Files:**
- Create: `docs/research/<today>-signal-matrix.md` (written by the script)
- Modify: `PLAN.md` (new phase with the outcome)

- [ ] **Step 1: Download the full minute universe**

Run: `set -a; . ./.env; set +a; uv run python scripts/fetch_minute_history.py`
Expected: ~550 ticker-years, ~45 minutes, ~50 million bars. Re-run once if any ticker-year
failed (the script prints them and skipping is safe — it resumes).

- [ ] **Step 2: Verify coverage before trusting any number**

Run: `uv run python scripts/fetch_minute_history.py --coverage`
Expected: near-zero "thin" ticker-years for 2016-2025 (2026 is partial by definition, and
tickers listed after 2016 legitimately miss early years). Record the numbers — they go into
the doc's data-basis section.

- [ ] **Step 3: Run the matrix**

Run: `uv run python scripts/run_signal_matrix.py`
Expected: cell count printed, plateau list, then exactly one hold-out block. Runtime is
minutes-to-tens-of-minutes; if it exceeds an hour, reduce `--years` rather than trimming axes
(a trimmed axis cannot form a plateau and silently changes the question).

- [ ] **Step 4: Read the result critically before writing it up**

Check each of these and write the answer into the doc:
- Did any plateau survive the hold-out with a MAJORITY of its cells positive?
- For every surviving plateau: is its median net edge larger than the SIP-vs-IEX feed
  difference plausibly is? If not, say so — the plateau is inside the measurement's own error.
- Are the surviving plateaus concentrated at the 2 bp cost level? If yes, the finding is about
  execution quality we do not have, and the doc must lead with that.
- How many cells were below the sample floor? A matrix that is mostly floor is a coverage
  statement, not a finding.

- [ ] **Step 5: Record the outcome in PLAN.md**

Add a phase section (mirroring the style of the existing "Phase: ..." blocks) with: the space
size, the plateau count, the hold-out verdict, and ONE of these two follow-ups:
- **If a plateau survived:** an open `- [ ]` item for the follow-up plan — signal-vs-fill
  measurement on IEX first, lane wiring second, decay monitoring third. Explicitly Nico-gated.
- **If none survived:** an entry in the null-result list, and the statement that the minute
  scale is now measured on ~50 million bars instead of 7 days — which closes the "we never
  looked properly" question rather than leaving it open.

- [ ] **Step 6: Gate + commit**

```bash
uv run pytest -q && uv run ruff check .
git add docs/research/ PLAN.md
git commit -m "docs(research): signal matrix over minute bars - plateau search and hold-out"
```

---

## Execution notes

- **Task order is mandatory.** Tasks 1-7 build and test the machinery on tiny fixtures; Task 8
  is the only one that touches the real data set. Do not run the full matrix before Task 7's
  tests are green — a bug found after a 45-minute download plus a full grid run costs the
  hold-out's innocence, because you will be tempted to look twice.
- **The hold-out is a one-shot resource.** If Task 8 reveals a bug that requires re-running,
  say so in the doc explicitly ("second look, reason: ..."). Silently re-running is the exact
  behaviour the split exists to prevent.
- **Self-review before each commit** (CLAUDE.md): read the diff for correctness, simplicity,
  repo conventions.
- **What this plan does NOT decide:** whether to trade any of it. That is Nico's call on the
  follow-up plan, and it starts with the feed-difference measurement, not with an order.

## Outcome (2026-08-17, Bau abgeschlossen — Messung läuft über Nacht)

**Die komplette Maschinerie steht und ist getestet** (6 Commits, Gate grün, ruff clean). Der
Datenlauf läuft; die Befunde stehen morgen in `docs/research/`.

### Was gegenüber diesem Plan erweitert wurde — auf Nicos Nachträge vom selben Abend

1. **Zeitscheiben bis 1 Monat, nicht nur bis 60 Minuten.** `TIME_SLICES` = 1min/5min/15min/
   30min/60min/1D/1W/1M. `resample_bars` verzweigt: Intraday-Scheiben werden pro HANDELSTAG
   gruppiert (sonst verschweißt eine 5-Minuten-Bar 15:59 mit dem nächsten 09:30), Swing-Scheiben
   bewusst nicht — dass sie Sitzungen überspannen, ist ihr Zweck. Jahresskala verworfen: bei 10
   Jahren sind das 10 Beobachtungen pro Ticker, die Stichprobenschwelle würde jede Zelle
   verwerfen, und das Ergebnis wäre eine Zeile „nicht messbar" für einen Rechentag.
2. **Asset-Klasse als eigene Achse** (Nicos Frage „unterscheiden sich Aktien und Rohstoffe?").
   70 Instrumente in 8 Klassen: Aktien, Index-ETFs, Sektoren, Rohstoffe (Gold, Silber, Öl, Gas,
   Kupfer, Platin, Agrar), Anleihen, Währungen, Volatilität, REITs. Klassen verschmelzen NICHT in
   der Plateau-Nachbarschaft — „wirkt auf Gold und auf Anleihen" ist ein Befund, keine Zelle.
3. **Ein siebtes Signal** (`breakout_high`, Donchian auf jeder Scheibe) neben den sechs geplanten.
4. **News-Latenz-Zerfallskurve** (`matrix/latency.py`, `data/news_history.py`,
   `scripts/run_news_latency.py`) — Nicos Frage, ob wir viele Quellen scrapen sollen, um schneller
   zu sein. Sie ist messbar statt diskutierbar, weil Alpaca den Benzinga-Wire ab 2016 mit
   **sekundengenauem** `created_at` liefert. Gemessen wird pro Verzögerungsstufe (0/1/2/5/15/30
   Min), was ein langsamerer Einsteiger VERPASST und was er noch verdient. `decay_verdict()` gibt
   dazu einen von drei klaren Sätzen aus — hält der Effekt ≥ 5 Minuten, ist Latenz nicht der
   Engpass und ein Scraping-Netz wäre Aufwand ohne Gegenwert; existiert er nur in Minute 0-1, ist
   es ein Rennen gegen Mikrosekunden-Gegner, das mit ~5 s Signal-zu-Fill nicht zu gewinnen ist.
5. **Nachtlauf-Tauglichkeit:** JSONL-Checkpoint pro Ticker (`data/matrix_cells.jsonl`), ein
   Ticker nach dem anderen im Speicher (statt 70 Millionen Zeilen gleichzeitig), Wiederaufnahme
   überspringt fertige Ticker, und eine abgerissene letzte Zeile nach einem Kill ist kein Fehler.
6. **Laufzeit-Optimierung, ohne die es kein Nachtlauf wäre:** die Kostenachse ändert nicht, WELCHE
   Trades stattfinden — also werden Trades einmal pro (Signal, Schwelle, Scheibe, Haltedauer)
   berechnet und alle vier Kostenstufen davon abgeleitet. Die Auswahl läuft über die
   Signal-Indizes statt über jede Bar. Ergebnis: **SPY mit 979.348 Bars → 7.280 Zellen in 19 s**
   (eine Bar-für-Bar-Schleife hätte pro Ticker Stunden gebraucht).

### Zwei harte Datengrenzen, gemessen statt vermutet

- **Das laufende Jahr ist gesperrt.** Jede 2026-Anfrage antwortet `HTTP 403 subscription does not
  permit querying recent SIP data`. Nutzbar sind **2016-2025**; `FULL_YEARS` wurde entsprechend
  gekürzt. Der Hold-out (ab 2023) umfasst damit drei vollständige Jahre.
- **Der Feed-Bruch ist real und bleibt:** Historie = SIP (konsolidiert), live = IEX (~2-3 % des
  Volumens). Genau deshalb ist ein bestätigtes Plateau ein Kandidat und kein Live-Edge.

### Ein Bug, den die Tests gefangen haben (und der still Plateaus erfunden hätte)

Die Achsen-Nachbarschaft wurde zuerst aus den VORHANDENEN Zellen abgeleitet. Damit wären zwei
Zellen zu Nachbarn geworden, sobald die Zelle dazwischen unter die Stichprobenschwelle fällt —
1D direkt neben 1M, wenn 1W zu dünn ist. Aus zwei unabhängigen Einzelfunden wäre so ein
„Plateau" entstanden, also genau das Artefakt, gegen das der ganze Ansatz gebaut ist. Die
Nachbarschaft kommt jetzt aus der DEKLARIERTEN Achse (`slice_order`).

### Vorbefund aus dem Probelauf (SPY allein, 2016-2025)

1.984 messbare Zellen, davon **206 nach Kosten positiv, aber nur 2 mit t ≥ 2 — und beide
isoliert, also kein Plateau.** Bei 20 bp Kosten überlebt nichts. Die beste Einzelzelle
(`gap_up`, 30min, Halten 12, bei 2 bp: +14,86 bp, t = 2,20) sitzt mit n = 284 knapp über der
Schwelle. Das ist genau die Struktur, die die Plateau-Regel aussortieren soll — der volle Lauf
über 70 Instrumente hat je Zelle ein Vielfaches der Stichprobe.

### Welle 2 (2026-08-17 nachts): „alle Parameter gegen alle Parameter"

Nicos Präzisierung: nicht nur Parameter gegen Zeitscheiben, sondern **Parameter gegen Parameter**,
und Beispiele wie „hoher Greed-Index UND dazu eine positive News". Umgesetzt als eigene Achsen-Art
in `matrix/contexts.py`:

- **Signale: 7 → 13.** Neu: `gap_down`, `spike_pullback` (**Nicos Setup**: großer Aufwärtssprung,
  dann sofortiger Rücksetzer), `spike_fade` (Erschöpfung nach Abwärtssprung), `consecutive_down`
  (n rote Bars — der häufigste menschliche Grund, einen Dip zu kaufen), `range_contraction`
  („coiled spring"), `new_low_20`.
- **Bedingungs-Achse, 23 Werte.** Marktkontext (`first_hour`, `midday`, `last_hour`,
  `high_rel_volume`, `uptrend`, `downtrend`, `after_news`, `calm_market`, `stressed_market`) plus
  **jedes Signal als Zustand** (`after_<signal>`) — das ist „jeder Parameter gegen jeden".
- **Warum Zustand und nicht Koinzidenz** (der Punkt, an dem der naive Ansatz scheitert): zwei
  Ereignisse, die je 1 % der Bars treffen, fallen auf 0,01 % der Bars zusammen — rund 100 Fälle
  in einer Million Bars, also unter dem Stichprobenboden. Als Zustand („B hat in den letzten 10
  Bars gefeuert, dann feuerte A") deckt dieselbe Bedingung ein Vielfaches ab und wird messbar,
  ohne die Behauptung zu verwässern. Das Gate-Fenster ist um eine Bar verschoben: die Bedingung
  muss VOR dem Signal stehen.
- **Tiefe bleibt eins.** Signal × EINE Bedingung, nie gestapelt. Jede weitere Bedingung schneidet
  die Stichprobe: ein Filter, der ein Drittel der Bars behält, macht aus 900 Trades 300, zwei
  gestapelte machen 100 — unter dem Boden. Die ehrliche Grenze von zehn Jahren Minutendaten ist
  eine Bedingung. `none` läuft immer mit, damit der BEITRAG der Bedingung sichtbar bleibt.
- **Greed-Index → VIX-Bänder.** Der Fear-&-Greed-Komposit wurde in diesem Repo am 2026-08-11
  gemessen und war **schwächer als seine beste Zutat**, also wird die Zutat verwendet
  (`calm_market` < 15, `stressed_market` > 22, jeweils der Vortags-Close, damit keine Bar weiß,
  wie die Angst nach ihrem Handel endete).
- **Zwei Korrektheitsfixes, die dabei auffielen:** (1) die Schwellen-Achse wird jetzt PRO SIGNAL
  gebildet — global gemischt hätte `consecutive_down` (Achse zählt Bars: 2,3,4,5) die
  Nachbarschaft der Prozent-Signale zerschnitten; (2) die Bedingung ist Gruppierungs- und keine
  Nachbarschaftsachse, damit „wirkt nur nach einer Meldung" nicht mit „wirkt immer" verschmilzt.
- **Laufzeit:** 109.749 Zellen pro Ticker in **41 s**; 70 Instrumente also < 1 h. Der Checkpoint
  wächst auf ~7,7 Mio Zeilen / 2,2 GB, weshalb das Pooling auf **inkrementelle Summen pro
  Anlageklasse** umgestellt wurde (Rows pro Schlüssel zu sammeln hätte Gigabytes RAM gebraucht).

**Vorbefund Welle 2 (SPY allein):** 32.236 messbare gepoolte Zellen, davon qualifizieren
**47 (0,1 %)** — die Zufallserwartung bei reinem Rauschen läge bei ~741. Die Ausbeute liegt also
UNTER dem, was Rauschen liefern würde, und **kein einziges Plateau** entsteht: die Sieger liegen
isoliert. Alle fünf Spitzenzellen stehen bei 2 bp, der unrealistischsten Kostenstufe.

## Faktor-Inventar: was noch in die Matrix kann (Nicos Frage nach den weiteren Parametern)

Das Projekt berechnet weit mehr als die 13 Signale. Was davon wie einfließen kann, hängt an einer
harten Eigenschaft: **ein Faktor kann nur dann ein TRIGGER sein, wenn er minutengenau existiert.**
Alles Tagesbasierte kann ausschließlich BEDINGUNG sein — es ändert sich einmal pro Tag und kann
daher keinen Einstiegszeitpunkt bestimmen, nur einen Zeitraum qualifizieren.

| Faktor | Quelle im Repo | Auflösung | Rolle | Status |
|---|---|---|---|---|
| Preis/Volumen-Muster | Minutenbars | Minute | Trigger | **drin** (13 Signale) |
| Wire-Meldung | `news_history` | Sekunde | Trigger + Bedingung | **drin** (`after_news`) |
| VIX-Level | `data/prices/vix_level.csv` | Tag | Bedingung | **drin** (2 Bänder) |
| Tageszeit / Sitzungsphase | Bar-Zeitstempel | Minute | Bedingung | **drin** (3 Werte) |
| Trend (schneller Schnitt) | Bars | je Scheibe | Bedingung | **drin** (up/down) |
| Relatives Volumen | Bars | je Scheibe | Bedingung | **drin** |
| VIX-Terminstruktur (VIX/VIX3M) | `run_behaviour_study` | Tag | Bedingung | offen — W0 fand inkrementell nur 0,08, also niedrige Priorität |
| VIX9D/VIX (Kurzfrist-Stress) | `run_behaviour_study` | Tag | Bedingung | offen |
| Marktbreite (% über 200d) | `regime.sector_breadth` | Tag | Bedingung | offen |
| Zinskurve (^TNX − ^IRX) | `regime.build_regime` | Tag | Bedingung | offen |
| SPY-Trend vs. 200d | `ml/features` | Tag | Bedingung | offen |
| SPY-Volumenratio, OBV-Trend | `run_behaviour_study` | Tag | Bedingung | offen |
| Depot-Drawdown | `ml/features` | Tag | Bedingung | offen |
| Momentum 3M/6M, 52-Wochen-Nähe | `factors.py` | Tag | Bedingung | offen |
| Value (KGV, KBV), Quality (ROE, Marge) | `factors.py` | Quartal | Bedingung | offen — nur für Einzelaktien, nicht für ETFs |
| F-Score (9 Kriterien) | `fscore.py` | Quartal | Bedingung | offen — Ziel-Horizont ist bereits auf 126 Tage vorregistriert |
| Insider-Käufe (Form 4) | `evidence/` | Tag (mit Meldeverzug) | Bedingung | offen |
| Congress-Trades, 13F | `evidence/` | Wochen Verzug | Bedingung | evidenzbasiert tot (Congress-Lane), niedrige Priorität |
| Earnings-Termin (vor/nach) | `evidence/` | Tag | Bedingung | offen — als „Tage bis/nach Bericht" |

**Reihenfolge, in der ich das ergänzen würde** (jeweils eine Welle, weil jede Bedingung den Raum
verbreitert und damit die Beweislast erhöht): (1) die drei Tages-Regime-Bedingungen aus `regime.py`
— Marktbreite, Zinskurve, SPY-Trend, weil sie fertig berechnet vorliegen und das ganze Universum
betreffen; (2) Earnings-Nähe, weil sie der stärkste bekannte Ereignis-Taktgeber ist; (3)
Momentum/52-Wochen-Nähe je Titel; (4) Fundamentaldaten, sobald der Backfill-Kollektor steht.

Nicht aufgenommen und warum: **Twitter/X und andere Social-Quellen.** Historische Tweets sind
nicht frei beziehbar (API kostenpflichtig, Scraping gegen die Nutzungsbedingungen und technisch
geblockt), also ließe sich die Hypothese nicht einmal testen — und die Latenzfrage, um die es
dabei geht, beantwortet die Zerfallskurve billiger.

### Offen

- [ ] Nachtlauf-Ergebnisse lesen: `docs/research/2026-08-1x-signal-matrix.md` und
      `...-news-latency-decay.md`, dann Outcome hier vervollständigen.
- [ ] Nico-Gate: nur falls ein Plateau den Hold-out überlebt → Folgeplan, dessen ERSTER Schritt
      eine Signal-vs-Fill-Messung auf IEX ist, nicht eine Lane.
- [ ] Welle 3: die vier Ausbaustufen aus dem Inventar oben, in der genannten Reihenfolge.
