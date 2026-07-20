"""Kraken public OHLC bars for the crypto lane (vision v11) — free, keyless, REAL-TIME.

The one market where retail gets genuinely real-time data for free: Kraken's public REST
API needs no key (rate limit ~1 req/sec per IP+pair; the lane polls 4 pairs every 15
minutes — far below it). The endpoint returns at most the last 720 bars per interval,
which is ~7.5 days of 15-minute bars — plenty for a 20-bar Donchian. The LAST row is the
still-running bar; `completed_bars` drops it so the engine only ever sees closed bars.
stdlib urllib transport (same stance as telegram_client), honest None on any failure.
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd

CRYPTO_PAIRS = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD"}
BAR_INTERVAL_MINUTES = 15
_BASE_URL = "https://api.kraken.com/0/public/OHLC"
_TIMEOUT_SECONDS = 15


def _get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - network failure degrades to "no data this run"
        return None


def fetch_ohlc(
    pair: str,
    *,
    interval: int = BAR_INTERVAL_MINUTES,
    get_json=_get_json,
) -> pd.DataFrame | None:
    """OHLC bars for a Kraken pair name (e.g. "XBTUSD"), indexed by UTC bar START time,
    columns open/high/low/close — INCLUDING the still-running last bar (see
    `completed_bars`). None on any transport/shape failure — never invented bars."""
    payload = get_json(f"{_BASE_URL}?pair={pair}&interval={interval}")
    if not payload or payload.get("error"):
        return None
    result = payload.get("result") or {}
    rows = next((v for k, v in result.items() if k != "last"), None)
    if not rows:
        return None
    try:
        frame = pd.DataFrame(
            [
                {
                    "time": pd.Timestamp(int(r[0]), unit="s", tz="UTC"),
                    "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]),
                }
                for r in rows
            ]
        ).set_index("time")
    except (ValueError, TypeError, IndexError):
        return None
    return frame if not frame.empty else None


def completed_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Everything but the newest row — Kraken's last row is the still-forming bar, and an
    engine deciding on a half-formed bar would trade on a close that does not exist yet."""
    return bars.iloc[:-1] if len(bars) else bars
