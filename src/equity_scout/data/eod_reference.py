"""Independent EOD close reference for the depot's price cross-check.

yfinance is an unofficial scraper and the depot's ONLY price source. A data GAP degrades
honestly everywhere (loaders are gap-tolerant, the completeness gate refuses thin data); a
WRONG price is caught by nothing before it books into the track record — the
15:57-intraday-as-close incident is the near-miss precedent. So the advance compares its panel
against a second, independent source.

Source choice (2026-08-17): the plan called for Stooq's free quote CSV, but that endpoint is
gone — `stooq.com/q/l/?...&e=csv` answers 404 on both .com and .pl, and the history CSV now
sits behind a JavaScript proof-of-work bot wall. The replacement is Alpaca's daily bars: an
OFFICIAL broker API (not a scraper), already credentialed in this repo for the paper lanes, and
therefore a genuinely independent reading of the same tape. It is not keyless like Stooq was;
it needs no new account either, which is why it wins over any register-for-a-key alternative.

The free IEX feed is enough for this job: measured on 2026-08-14 the two sources agreed to
0.007 % on SPY/IEF/GLD. The check exists to catch a WRONG price, not to adjudicate cents.

Only bars of days that are already OVER count. A bar of the running session is not an EOD
close, and comparing the panel's last close against a half-finished day would invent a
divergence out of the clock.
"""
from __future__ import annotations

from datetime import date

from equity_scout.alpaca_broker import DATA_BASE, auth_headers

TIMEOUT_SECONDS = 20.0
LOOKBACK_DAYS = 10  # enough to survive a long weekend plus a holiday


class EodReferenceError(RuntimeError):
    """Reference unreachable or unusable — the caller warns and advances without it."""


def parse_daily_closes(payload: dict, *, today: date) -> dict[str, tuple[str, float]]:
    """Alpaca multi-symbol daily bars -> {ticker: (iso_date, close)} of the newest FINISHED day.

    A symbol with no usable bar is simply absent; the caller reads absence as 'no reference',
    never as agreement.
    """
    out: dict[str, tuple[str, float]] = {}
    today_iso = today.isoformat()
    for ticker, bars in (payload.get("bars") or {}).items():
        for bar in reversed(bars or []):
            stamp, close = str(bar.get("t", ""))[:10], bar.get("c")
            if not stamp or stamp >= today_iso or close is None:
                continue  # running session or malformed row — not an EOD close
            try:
                value = float(close)
            except (TypeError, ValueError):
                continue
            if value > 0:
                out[ticker] = (stamp, value)
            break
    return out


def fetch_latest_closes(
    tickers: list[str], *, today: date | None = None
) -> dict[str, tuple[str, float]]:
    """Latest finished daily close per ticker. Raises EodReferenceError on any transport or
    auth failure — the caller decides that a missing check must not stop the depot."""
    import httpx

    day = today or date.today()
    start = date.fromordinal(day.toordinal() - LOOKBACK_DAYS).isoformat()
    try:
        with httpx.Client(headers=auth_headers(), timeout=TIMEOUT_SECONDS) as client:
            response = client.get(
                f"{DATA_BASE}/stocks/bars",
                params={
                    "symbols": ",".join(tickers),
                    "timeframe": "1Day",
                    "start": start,
                    "feed": "iex",
                    "limit": 1_000,
                },
            )
    except Exception as err:  # noqa: BLE001 — transport detail is not the caller's business
        raise EodReferenceError(f"{type(err).__name__}: {err}") from err
    if response.status_code != 200:
        raise EodReferenceError(
            f"GET /v2/stocks/bars (1Day) -> {response.status_code}: {response.text[:200]}"
        )
    return parse_daily_closes(response.json(), today=day)
