"""Minute-bar store for the signal matrix: Alpaca SIP history on disk.

Why this exists: every prior minute-scale study in docs/research/ was data-limited. yfinance
serves 7 days of minute bars, which is why `breakout-first-minute` had 91 events and a t of
0.94 — not enough sample to decide anything. Alpaca's SIP feed reaches back to 2016-01-01
(verified 2026-08-17), i.e. ~1 million minute bars per ticker. That is the difference between
"we cannot tell" and "we measured it".

Feed choice, and the trap it carries: HISTORY comes from SIP (consolidated tape, all venues).
The LIVE lanes read IEX (~2-3 % of volume). Anything measured here therefore describes a
richer tape than the one a live lane trades on — a confirmed pattern is a candidate, never a
live edge, until a signal-vs-fill measurement says otherwise.

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
    assumption that does not hold. The 16:00 stamp is excluded (it is the end of the 15:59
    bar's interval, not a tradable minute of its own).
    """
    if frame.empty:
        return frame
    local = frame.index.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    return frame.loc[(minutes >= 9 * 60 + 30) & (minutes < 16 * 60)]


def save_year(
    frame: pd.DataFrame, ticker: str, year: int, *, root: Path | str = DATA_BASE_PATH
) -> Path:
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
