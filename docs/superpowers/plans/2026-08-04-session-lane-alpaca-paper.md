# Session-Lane auf Alpaca Paper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the executability bias from the session lane by sourcing real-time IEX bars and routing entries as bracket orders to an Alpaca **paper** account, so the lane's track record is measured against fills that actually existed — **and cut the reaction latency from 30–45 minutes to about one**, so the lane can actually trade the move it claims to trade.

> **Revision 2026-08-05 (Nico):** The first draft of this plan removed only the settle
> buffer and kept 15-minute bars on the `*/15` cron — that lands at 0–15 minutes, average
> ~7. Measured latency chain in the *current* system: a spike at 10:31 ET falls in the
> 10:30–10:45 bar, which settles at 11:05 (`SETTLE_MINUTES = 20`) and is first seen by the
> 11:15 cron slot — **44 minutes**. Three additions close the rest of the gap, see design
> decisions 5–7. Holding overnight was raised and deliberately deferred: the session lane
> stays flat-by-close so its 48-trade track stays comparable, and a hold-for-hours-to-days
> lane goes on top later — nothing here blocks it.

**Architecture:** Two new network-isolated modules mirror the existing `intraday_bars` shape — `alpaca_data.py` (bars, same DataFrame contract) and `alpaca_broker.py` (orders, positions, cancel). `st_session.decide()` stays byte-identical: it keeps producing signals, but its price field becomes the *expected* price rather than the booked fill. `run_shortterm.py`'s session path places bracket orders instead of booking locally, then reconciles the broker's positions against `shortterm.db` — the broker is the source of truth, the DB is journal and mirror.

**Tech Stack:** Python 3.12, httpx (already a dependency), pandas, SQLite via `equity_scout.db`, pytest. Alpaca REST v2 (`data.alpaca.markets`, `paper-api.alpaca.markets`), IEX feed on the free Basic plan.

---

## Precondition (blocks Tasks 1–8; Task 0 is independent)

**No Alpaca code may be built before `scripts/verify_alpaca_paper.py` runs green during US
market hours (15:30–22:00 CEST).** Task 0 fixes a defect in the existing lane and is
deliberately outside this gate — it is worth doing even if the Alpaca path is abandoned.

The design rests on **two** measured claims, both checked by `[2/4]`:

1. **Freshness** — IEX bars arrive roughly one bar-interval old. If they arrive 15+ minutes
   late, the delay we are paying to remove is still there and this plan is void.
2. **Density** — at 1-minute resolution the mega-caps actually print. IEX is ~2–3 % of US
   volume, so a given minute can carry no trade at all; below 80 % of the last 60 minutes
   covered, a minute-resolution trigger fires on stale prints and re-introduces exactly the
   bias this plan removes. Then the trigger resolution goes back up (5Min) and the latency
   target moves with it.

If either fails, fall back to quantifying the bias in the existing track instead.

Density is anchored on the newest bar, not on the wall clock, so **it is verdicted even
outside market hours** — that check can be run the moment the keys exist. Freshness cannot.

```bash
# Nico enters ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY in .env first (paper keys!)
uv run python scripts/verify_alpaca_paper.py                # checks 1+2, no orders
uv run python scripts/verify_alpaca_paper.py --place-orders # checks 3+4, places+cancels
```

Record the actual bar ages in the outcome section of this document. "It looked fine" is
not a record.

---

## Design decisions taken here (not in the spec)

**1. The lane keeps its identity, the regime break is marked.** No `session_live` twin
lane. A `st_state` row `execution_regime` records the ISO timestamp from which fills come
from the broker; every surface that shows the session track reads it and labels the split.
Rationale: a second lane would fragment a 10-trade history into two useless halves, and
the honest problem is not "which lane" but "which fills are believable".

**2. `SETTLE_MINUTES` does not disappear — it becomes zero for the Alpaca path.** The
completeness rule (a bar is usable once its interval has elapsed) is kept as a separate,
tested function so the yfinance path stays untouched and reviewable. Two feeds, one gate
shape.

**3. Sizing stays local.** `shortterm_book.buy` decides quantity from the local book, and
that quantity goes into the order. The broker's paper account is not consulted for buying
power — the arena's 10,000 USD is the honest constraint, not Alpaca's default 100k paper
balance.

**4. Costs stop being modelled on the Alpaca path.** `DEFAULT_SLIPPAGE_BPS = 5.0` is a
guess; the broker fill is a measurement. Fills booked from Alpaca carry
`slippage_bps=0.0` and the real difference lands in the reconciliation table. Booking both
would double-count.

**5. Two resolutions, two roles.** The opening range keeps its 15-minute bars; only the
breakout trigger drops to 1 minute. The range is a *breadth* measurement — it wants every
print of the first 30 minutes, and IEX's thin slice hurts least when aggregated. The
trigger is an *immediacy* measurement, where aggregation is precisely the cost. Running the
range on 1-minute bars would buy nothing and would make the stop and the target noisier,
since both are derived from it (`STOP_RANGE_MULT`, `TARGET_RANGE_MULT`).

**6. The exits leave our loop entirely.** This is the largest single latency win and it
needs no fast feed at all: with stop and target resting at the broker as bracket legs, the
exchange triggers them in milliseconds regardless of when our process next wakes. Our code
only has to be awake for *entries*. It also retires the failure mode found in Task 0 — a
position can no longer sit unmanaged because a run did not happen.

**7. Polling every minute, not a streaming daemon.** 1-minute bars over REST on a
`* * * * *` cron gives ~30–60 s entry latency with no long-lived process. A WebSocket
subscription (`wss://stream.data.alpaca.markets/v2/iex`) would cut that to milliseconds but
adds a daemon with reconnect, heartbeat and state recovery — parts that die quietly at
night, which is the failure class this project has already been bitten by twice (the v12
cron `cd` bug, the Tokyo-stamped panel row). For an opening-range breakout on mega-caps the
seconds are not the binding constraint. Revisit only if a measured miss rate says so.

Rate limits are not a concern: one multi-symbol bars call per minute against Alpaca Basic's
200 requests/minute. But it does require splitting the session lane out of
`scripts/intraday_copilot.sh` — that chain also runs radar, evidence and notify, none of
which may run 15× more often. New Task 9.

---

## File structure

| File | Responsibility |
|---|---|
| `src/equity_scout/alpaca_data.py` (new) | Fetch 15-min IEX bars; same DataFrame contract as `intraday_bars.fetch_bars`; completeness gate |
| `src/equity_scout/alpaca_broker.py` (new) | Place bracket/market orders, read positions and orders, cancel; typed results, no pandas |
| `src/equity_scout/session_reconcile.py` (new) | Pure comparison of broker positions vs. book positions → divergence report |
| `src/equity_scout/shortterm_storage.py` (modify) | `st_executions` table + accessors for expected-vs-actual fills |
| `scripts/run_shortterm.py` (modify, `run_session`) | Wire the broker path in; staleness gate; reconciliation call |
| `src/equity_scout/digest.py` (modify) | One line: slippage measured so far |
| `frontend/src/components/ShorttermPanel.tsx` (modify) | Regime label on the session lane |
| `tests/test_alpaca_data.py`, `tests/test_alpaca_broker.py`, `tests/test_session_reconcile.py`, `tests/test_run_shortterm_alpaca.py` (new) | Faked responses only — no live calls, ever |

---

### Task 0: The in-session force-flat has never fired — fix the window (NOT blocked by the verification)

**Files:**
- Modify: `src/equity_scout/market_hours.py:18` (`WINDOW_END`)
- Test: `tests/test_market_hours.py` (append)

Found while surveying on 2026-08-04, measured, not suspected:

| Fact | Value |
|---|---|
| Last session bar starts | 15:45 ET |
| That bar is settled (+15 bar +20 settle) | **16:20 ET** |
| `within_market_window` returns False from | **16:30:01 ET** |
| `*/15` cron slots in that window | **none** — :15 is too early, :30 fires a second too late |
| `Session-Ende (flat)` exits in `shortterm.db` (15 sells total) | **0** |
| `Session-Ende (Nachlauf)` exits (the 02:35 nightly sweep) | 1 |

So `st_session.py:91`'s force-flat — the code that implements "the lane NEVER holds
overnight" — is unreachable in production. Every position instead sits open and unmanaged
from 16:20 ET until the nightly sweep at 02:35 CEST, about four hours, and if that chain
fails it sits there for days. That is the 2026-07-21 loss mechanism (−176,70) with the
guard rail already off.

This is worth fixing whether or not Alpaca happens, so it comes first.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_market_hours.py`:

```python
def test_window_still_open_at_the_cron_slot_after_the_last_bar_settles() -> None:
    """Regression (2026-08-04): the last session bar settles at 16:20 ET, but the window
    closed at 16:30:00 and the */15 cron fires at 16:30:0X — so no run ever saw that bar
    in-session, and the force-flat never executed once in 15 recorded exits."""
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    assert within_market_window(datetime(2026, 8, 4, 16, 45, 3, tzinfo=ny)) is True


def test_window_closes_before_the_next_cron_slot() -> None:
    """The window must not creep so far that the 17:00 run also fires — the lane would
    poll a closed market for an hour."""
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    assert within_market_window(datetime(2026, 8, 4, 17, 0, 3, tzinfo=ny)) is False


def test_panel_cutoff_still_excludes_the_session_that_just_closed() -> None:
    """WINDOW_END also drives last_completed_us_session; widening it must not make the
    panel accept a still-running session as an end-of-day close."""
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    assert last_completed_us_session(datetime(2026, 8, 4, 16, 40, tzinfo=ny)).isoformat() \
        == "2026-08-03"
```

Check the imports at the top of `tests/test_market_hours.py` and add
`last_completed_us_session` if it is not already imported.

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_market_hours.py -v`
Expected: `test_window_still_open_at_the_cron_slot_after_the_last_bar_settles` FAILS
(assert False is True); the other two pass already.

- [x] **Step 3: Fix the constant**

In `src/equity_scout/market_hours.py`:

```python
WINDOW_END = time(16, 50)  # 16:00 close + settle grace, wide enough that the */15 cron
                           # slot at 16:45 still runs: the last 15:45 bar only settles at
                           # 16:20, and the old 16:30 end left NO slot in between — the
                           # in-session force-flat had never once fired (measured
                           # 2026-08-04, 0 of 15 session exits).
```

Update the module docstring's "plus a 30-minute grace" to match the new value and state
why the grace is now 50 minutes: it is not about the data delay, it is about a cron slot
existing after the last bar becomes usable.

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_market_hours.py tests/test_run_shortterm.py -v`
Expected: all passed

- [x] **Step 5: Full gate and commit** — done 2026-08-04, commit `18b6f45`.

```bash
uv run pytest -q && uv run ruff check .
git add src/equity_scout/market_hours.py tests/test_market_hours.py
git commit -m "fix(session): keep the market window open until the last bar can be traded"
```

- [ ] **Step 6: Confirm it fires in production**

The day after deploying, check that the last intraday run of the session happened at 16:45
ET and — when a position was open into the close — that a `Session-Ende (flat)` row exists:

```bash
grep "16:45\|22:45" intraday.log | tail -3
uv run python -c "
import sqlite3
c = sqlite3.connect('shortterm.db')
print(c.execute(\"select count(*) from st_trades where lane='session' and reason like 'Session-Ende (flat)%'\").fetchone())
"
```

Expected: a non-zero count on the first day a position runs into the close. Until that is
observed, this fix is unverified in production regardless of green tests.

**Partially verified 2026-08-05** (first full session after the fix): the 16:30 ET *and*
16:45 ET cron slots both ran and both reached `st_session` — under the old `WINDOW_END` the
16:30 slot fired one second too late and 16:45 did not exist at all, so the window now
demonstrably contains a slot after the last bar settles at 16:20. The `Session-Ende (flat)`
count is still 0, but for a benign reason: both of the day's positions (NVDA, AAPL) were
stopped out at 10:45 and 11:15 ET, so nothing ran into the close. **Still open** — the fix
is proven reachable, not yet proven to fire. Re-check on the first day a position survives
to 16:45.

Side observation from the same log, which is why Task 9 Step 1 exists: the 16:45 run wrote
a full report block including the disclaimer for a session with *zero* fills and zero open
positions. At a one-minute cadence that is ~390 such blocks a day.

---

### Task 1: Alpaca bar fetch with the same DataFrame contract

> **Revised 2026-08-05 (design decision 5).** The code below is written against a single
> `BAR_MINUTES = 15`. Build it with the resolution as a **parameter** instead —
> `fetch_bars(tickers, *, bar_minutes)` — because the lane now needs both: 15Min for the
> opening range, 1Min for the breakout trigger. The DataFrame contract, the completeness
> gate and the tests are otherwise unchanged; the gate just takes its interval from the
> argument rather than from a module constant.

**Files:**
- Create: `src/equity_scout/alpaca_data.py`
- Test: `tests/test_alpaca_data.py`

- [x] **Step 1: Write the failing tests**

```python
"""Alpaca IEX bars must satisfy the exact contract intraday_bars.fetch_bars satisfies:
tz-aware America/New_York index, lowercase open/high/low/close columns. st_session.decide()
must not be able to tell the two feeds apart."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from equity_scout.alpaca_data import AlpacaDataError, complete_bars, parse_bars


def _payload() -> dict:
    return {
        "bars": {
            "AAPL": [
                {"t": "2026-08-04T13:30:00Z", "o": 300.0, "h": 302.0, "l": 299.5,
                 "c": 301.0, "v": 1000},
                {"t": "2026-08-04T13:45:00Z", "o": 301.0, "h": 303.0, "l": 300.5,
                 "c": 302.5, "v": 1200},
            ]
        }
    }


def test_parse_yields_new_york_index_and_lowercase_columns() -> None:
    frames = parse_bars(_payload())
    frame = frames["AAPL"]
    assert str(frame.index.tz) == "America/New_York"
    assert frame.index[0].hour == 9 and frame.index[0].minute == 30
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame["close"].iloc[-1] == 302.5


def test_empty_series_is_absent_not_zero() -> None:
    assert parse_bars({"bars": {"AAPL": []}}) == {}


def test_missing_bars_key_raises_loudly() -> None:
    with pytest.raises(AlpacaDataError, match="kein 'bars'"):
        parse_bars({"message": "forbidden"})


def test_complete_bars_drops_the_still_running_interval() -> None:
    frames = parse_bars(_payload())
    # 09:45 bar covers 09:45-10:00; at 09:52 it is not finished yet.
    now = datetime(2026, 8, 4, 9, 52, tzinfo=ZoneInfo("America/New_York"))
    kept = complete_bars(frames["AAPL"], now)
    assert len(kept) == 1
    assert kept.index[-1].minute == 30


def test_complete_bars_keeps_a_just_finished_interval() -> None:
    frames = parse_bars(_payload())
    now = datetime(2026, 8, 4, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert len(complete_bars(frames["AAPL"], now)) == 2
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_alpaca_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.alpaca_data'`

- [x] **Step 3: Write the implementation**

```python
"""Real-time 15-minute IEX bars for the session lane (2026-08-04).

Replaces the yfinance path for lane `session`, whose ~15-minute delay forced a 20-minute
settle margin and produced fills at prices that were no longer available when the decision
was made (executability bias — see
docs/superpowers/specs/2026-08-04-session-lane-realtime-broker-design.md).

The delay is gone, the completeness rule is not: a bar is usable once its interval has
ELAPSED, never while it is still forming. `intraday_bars.settled_bars` stays untouched for
the other feed; this module owns the Alpaca-side gate.

Network code lives in `fetch_bars` alone and is faked in tests — same structure as
`intraday_bars`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from equity_scout.alpaca_broker import DATA_BASE, auth_headers

BAR_MINUTES = 15
FEED = "iex"  # Basic plan: the API default (sip) answers 403


class AlpacaDataError(RuntimeError):
    """The Alpaca feed broke the contract the session lane relies on."""


def parse_bars(payload: dict) -> dict[str, pd.DataFrame]:
    """Alpaca's multi-symbol bar response -> the intraday_bars DataFrame contract.

    A symbol with no bars is ABSENT from the result, never present with zeros: callers
    read absence as 'no data this run' and refuse to trade on it.
    """
    if "bars" not in payload:
        raise AlpacaDataError(
            f"Antwort enthaelt kein 'bars' — Feed oder Plan falsch: {str(payload)[:200]}"
        )
    out: dict[str, pd.DataFrame] = {}
    for ticker, series in (payload["bars"] or {}).items():
        if not series:
            continue
        frame = pd.DataFrame(
            [
                {"open": b["o"], "high": b["h"], "low": b["l"],
                 "close": b["c"], "volume": b["v"]}
                for b in series
            ],
            index=pd.DatetimeIndex([pd.Timestamp(b["t"]) for b in series], tz="UTC"),
        ).sort_index()
        out[ticker] = frame.tz_convert("America/New_York")
    return out


def complete_bars(bars: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Only bars whose interval has fully elapsed. With a real-time feed this is the whole
    gate — no safety margin is needed for a delay that no longer exists."""
    if bars.empty:
        return bars
    ends = bars.index + pd.Timedelta(minutes=BAR_MINUTES)
    return bars.loc[ends <= pd.Timestamp(now)]


def fetch_bars(tickers: list[str], *, now: datetime, hours: int = 8) -> dict[str, pd.DataFrame]:
    """Today's 15-minute IEX bars per ticker (network). Raises AlpacaDataError on any
    non-200 — a silent empty result would look exactly like 'no signal today'."""
    import httpx

    start = (now - timedelta(hours=hours)).astimezone(tz=None).strftime("%Y-%m-%dT%H:%M:%SZ")
    with httpx.Client(headers=auth_headers(), timeout=30.0) as client:
        response = client.get(
            f"{DATA_BASE}/stocks/bars",
            params={
                "symbols": ",".join(tickers),
                "timeframe": f"{BAR_MINUTES}Min",
                "start": start,
                "feed": FEED,
                "limit": 10_000,
            },
        )
    if response.status_code != 200:
        raise AlpacaDataError(
            f"GET /v2/stocks/bars -> {response.status_code}: {response.text[:300]}"
        )
    return parse_bars(response.json())
```

Note: `fetch_bars` imports `DATA_BASE` and `auth_headers` from `alpaca_broker` (Task 2).
Write Task 2 first if the import order bothers you — the tests above do not touch either.

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_alpaca_data.py -v`
Expected: 5 passed

- [x] **Step 5: Commit**

```bash
git add src/equity_scout/alpaca_data.py tests/test_alpaca_data.py
git commit -m "feat(session): fetch real-time IEX bars on the intraday_bars contract"
```

---

### Task 2: Broker module — credentials, bracket orders, positions

**Files:**
- Create: `src/equity_scout/alpaca_broker.py`
- Test: `tests/test_alpaca_broker.py`

- [x] **Step 1: Write the failing tests**

```python
"""The broker seam. Every test fakes the transport — a live call from the suite would
place orders in the paper book and corrupt the track record it exists to measure."""
from __future__ import annotations

import pytest

from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    BrokerPosition,
    bracket_payload,
    parse_order,
    parse_positions,
)


def test_bracket_payload_carries_stop_and_target() -> None:
    payload = bracket_payload("AAPL", qty=3.5, stop_price=295.0, target_price=310.0)
    assert payload["symbol"] == "AAPL"
    assert payload["side"] == "buy"
    assert payload["type"] == "market"
    assert payload["order_class"] == "bracket"
    assert payload["time_in_force"] == "day"
    assert payload["stop_loss"]["stop_price"] == "295.00"
    assert payload["take_profit"]["limit_price"] == "310.00"


def test_bracket_payload_rounds_quantity_down_to_whole_shares() -> None:
    """Bracket orders reject fractional quantities at Alpaca. Rounding DOWN keeps the
    position inside the size the book approved."""
    assert bracket_payload("AAPL", qty=3.9, stop_price=1.0, target_price=2.0)["qty"] == "3"


def test_bracket_payload_rejects_a_position_below_one_share() -> None:
    with pytest.raises(AlpacaBrokerError, match="unter einer ganzen Aktie"):
        bracket_payload("AAPL", qty=0.4, stop_price=1.0, target_price=2.0)


def test_parse_positions_maps_symbol_to_qty_and_price() -> None:
    positions = parse_positions([
        {"symbol": "AAPL", "qty": "3", "avg_entry_price": "301.25"},
        {"symbol": "TSLA", "qty": "2", "avg_entry_price": "330.10"},
    ])
    assert positions["AAPL"] == BrokerPosition(ticker="AAPL", qty=3.0, avg_entry_price=301.25)
    assert len(positions) == 2


def test_parse_order_reports_an_unfilled_order_as_none_price() -> None:
    order = parse_order({"id": "abc", "status": "accepted", "filled_qty": "0",
                         "filled_avg_price": None})
    assert order.order_id == "abc"
    assert order.filled_qty == 0.0
    assert order.filled_avg_price is None


def test_parse_order_reads_a_filled_order() -> None:
    order = parse_order({"id": "abc", "status": "filled", "filled_qty": "3",
                         "filled_avg_price": "301.44"})
    assert order.filled_qty == 3.0
    assert order.filled_avg_price == 301.44
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_alpaca_broker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.alpaca_broker'`

- [x] **Step 3: Write the implementation**

```python
"""Alpaca PAPER broker seam for the session lane (2026-08-04).

LOOP.md permits order routing to a paper account since 2026-08-04 and forbids real money
unconditionally. This module therefore hardcodes the paper host: there is no configuration
switch that could point it at a live endpoint, because a configurable one would eventually
be misconfigured.

Entries go out as BRACKET orders — entry, stop-loss and take-profit in one instruction — so
the position is protected in the market itself. That is the point: on 2026-07-21 the machine
stopped running for two days with five positions open, and no local stop can fire when the
process that would check it is not alive.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DATA_BASE = "https://data.alpaca.markets/v2"
PAPER_BASE = "https://paper-api.alpaca.markets/v2"  # never parameterised — see docstring


class AlpacaBrokerError(RuntimeError):
    """An order or account call did not do what the caller assumed."""


@dataclass(frozen=True)
class BrokerPosition:
    ticker: str
    qty: float
    avg_entry_price: float


@dataclass(frozen=True)
class BrokerOrder:
    order_id: str
    status: str
    filled_qty: float
    filled_avg_price: float | None  # None until something actually filled


def auth_headers() -> dict[str, str]:
    key, secret = os.getenv("ALPACA_API_KEY_ID"), os.getenv("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        raise AlpacaBrokerError(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY fehlen — Paper-Keys in .env eintragen."
        )
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def bracket_payload(ticker: str, *, qty: float, stop_price: float, target_price: float) -> dict:
    """Market entry with a resting stop and target. Quantity is rounded DOWN to whole
    shares: Alpaca rejects fractional quantities for bracket orders, and rounding up would
    take more risk than the book sized for."""
    whole = int(qty)
    if whole < 1:
        raise AlpacaBrokerError(
            f"{ticker}: Position {qty:.4f} liegt unter einer ganzen Aktie — "
            "Bracket-Order nicht moeglich."
        )
    return {
        "symbol": ticker,
        "qty": str(whole),
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "stop_loss": {"stop_price": f"{stop_price:.2f}"},
        "take_profit": {"limit_price": f"{target_price:.2f}"},
    }


def parse_positions(rows: list[dict]) -> dict[str, BrokerPosition]:
    return {
        row["symbol"]: BrokerPosition(
            ticker=row["symbol"],
            qty=float(row["qty"]),
            avg_entry_price=float(row["avg_entry_price"]),
        )
        for row in rows
    }


def parse_order(row: dict) -> BrokerOrder:
    price = row.get("filled_avg_price")
    return BrokerOrder(
        order_id=row["id"],
        status=row["status"],
        filled_qty=float(row.get("filled_qty") or 0.0),
        filled_avg_price=float(price) if price else None,
    )


def _client():  # noqa: ANN202 - httpx.Client, lazily imported to keep tests offline
    import httpx

    return httpx.Client(headers=auth_headers(), timeout=30.0)


def fetch_positions() -> dict[str, BrokerPosition]:
    """Every open position in the paper account (network)."""
    with _client() as client:
        response = client.get(f"{PAPER_BASE}/positions")
    if response.status_code != 200:
        raise AlpacaBrokerError(
            f"GET /v2/positions -> {response.status_code}: {response.text[:300]}"
        )
    return parse_positions(response.json())


def place_bracket(ticker: str, *, qty: float, stop_price: float,
                  target_price: float) -> BrokerOrder:
    """Submit a bracket entry (network). Raises on rejection — a swallowed rejection would
    leave the book believing it holds something it does not."""
    payload = bracket_payload(ticker, qty=qty, stop_price=stop_price, target_price=target_price)
    with _client() as client:
        response = client.post(f"{PAPER_BASE}/orders", json=payload)
    if response.status_code not in (200, 201):
        raise AlpacaBrokerError(
            f"POST /v2/orders ({ticker}) -> {response.status_code}: {response.text[:300]}"
        )
    return parse_order(response.json())


def close_position(ticker: str) -> BrokerOrder:
    """Flatten one position at market and cancel its resting bracket legs (network)."""
    with _client() as client:
        response = client.delete(f"{PAPER_BASE}/positions/{ticker}")
    if response.status_code not in (200, 207):
        raise AlpacaBrokerError(
            f"DELETE /v2/positions/{ticker} -> {response.status_code}: {response.text[:300]}"
        )
    return parse_order(response.json())
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_alpaca_broker.py -v`
Expected: 6 passed

- [x] **Step 5: Commit**

```bash
git add src/equity_scout/alpaca_broker.py tests/test_alpaca_broker.py
git commit -m "feat(session): add the Alpaca paper broker seam with bracket entries"
```

---

### Task 3: Reconciliation — the broker is the truth

**Files:**
- Create: `src/equity_scout/session_reconcile.py`
- Test: `tests/test_session_reconcile.py`

- [x] **Step 1: Write the failing tests**

```python
"""Two books that can drift are two books that WILL drift. This compares them and says so
out loud; nothing here merges silently."""
from __future__ import annotations

from dataclasses import replace

from equity_scout.alpaca_broker import BrokerPosition
from equity_scout.session_reconcile import Divergence, reconcile
from equity_scout.shortterm_book import LaneBook, LanePosition


def _book(**positions: LanePosition) -> LaneBook:
    return replace(LaneBook.fresh("session"), positions=dict(positions))


def _pos(qty: float) -> LanePosition:
    return LanePosition(qty=qty, entry_price=300.0, opened_at="2026-08-04T09:45:00-04:00")


def test_matching_books_report_no_divergence() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    assert reconcile(_book(AAPL=_pos(3.0)), broker) == []


def test_position_only_at_the_broker_is_reported() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    result = reconcile(_book(), broker)
    assert result == [Divergence("AAPL", kind="broker_only", book_qty=0.0, broker_qty=3.0)]


def test_position_only_in_the_book_is_reported() -> None:
    result = reconcile(_book(AAPL=_pos(3.0)), {})
    assert result == [Divergence("AAPL", kind="book_only", book_qty=3.0, broker_qty=0.0)]


def test_quantity_mismatch_is_reported() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 2.0, 301.0)}
    result = reconcile(_book(AAPL=_pos(3.0)), broker)
    assert result == [Divergence("AAPL", kind="qty_mismatch", book_qty=3.0, broker_qty=2.0)]


def test_rounding_difference_below_one_share_is_not_a_divergence() -> None:
    """The book sizes fractionally, the broker fills whole shares — a sub-share gap is the
    designed consequence of rounding down, not a fault."""
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    assert reconcile(_book(AAPL=_pos(3.9)), broker) == []
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_session_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.session_reconcile'`

- [x] **Step 3: Write the implementation**

```python
"""Broker-vs-book reconciliation for the session lane (2026-08-04).

Since the broker holds the real position, a difference between it and `shortterm.db` is a
fault report, not something to merge away. Pure comparison — the caller decides whether to
log, alert or halt.

Sub-share differences are expected by design: the book sizes fractionally, `bracket_payload`
rounds down to whole shares. Anything at or above one share is a real divergence.
"""
from __future__ import annotations

from dataclasses import dataclass

from equity_scout.alpaca_broker import BrokerPosition
from equity_scout.shortterm_book import LaneBook

TOLERANCE_SHARES = 1.0


@dataclass(frozen=True)
class Divergence:
    ticker: str
    kind: str  # "broker_only" | "book_only" | "qty_mismatch"
    book_qty: float
    broker_qty: float

    def describe(self) -> str:
        if self.kind == "broker_only":
            return f"{self.ticker}: Broker haelt {self.broker_qty:g}, Buch nichts"
        if self.kind == "book_only":
            return f"{self.ticker}: Buch haelt {self.book_qty:g}, Broker nichts"
        return (
            f"{self.ticker}: Buch {self.book_qty:g} vs Broker {self.broker_qty:g}"
        )


def reconcile(book: LaneBook, broker: dict[str, BrokerPosition]) -> list[Divergence]:
    """Every ticker where the two books disagree by a share or more."""
    out: list[Divergence] = []
    for ticker in sorted({*book.positions, *broker}):
        book_qty = book.positions[ticker].qty if ticker in book.positions else 0.0
        broker_qty = broker[ticker].qty if ticker in broker else 0.0
        if abs(book_qty - broker_qty) < TOLERANCE_SHARES:
            continue
        if broker_qty and not book_qty:
            kind = "broker_only"
        elif book_qty and not broker_qty:
            kind = "book_only"
        else:
            kind = "qty_mismatch"
        out.append(Divergence(ticker, kind=kind, book_qty=book_qty, broker_qty=broker_qty))
    return out
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_session_reconcile.py -v`
Expected: 5 passed

- [x] **Step 5: Commit**

```bash
git add src/equity_scout/session_reconcile.py tests/test_session_reconcile.py
git commit -m "feat(session): reconcile broker positions against the lane book"
```

---

### Task 4: Persist expected-vs-actual fills (the first slippage measurement)

**Files:**
- Modify: `src/equity_scout/shortterm_storage.py` (add table to `init_shortterm_db`, add two functions)
- Test: `tests/test_shortterm_storage.py` (append)

- [x] **Step 1: Write the failing tests**

Append to `tests/test_shortterm_storage.py`:

```python
def test_execution_records_expected_and_actual_price(tmp_path) -> None:
    from equity_scout.shortterm_storage import (
        init_shortterm_db,
        load_executions,
        record_execution,
    )

    path = tmp_path / "st.db"
    init_shortterm_db(path)
    record_execution(
        path, lane="session", ticker="AAPL", side="buy",
        signalled_at="2026-08-04T09:45:00-04:00", expected_price=301.00,
        actual_price=301.44, qty=3.0, order_id="abc",
    )
    rows = load_executions(path, lane="session")
    assert len(rows) == 1
    assert rows[0]["expected_price"] == 301.00
    assert rows[0]["actual_price"] == 301.44
    assert rows[0]["order_id"] == "abc"


def test_recording_the_same_order_twice_is_idempotent(tmp_path) -> None:
    from equity_scout.shortterm_storage import (
        init_shortterm_db,
        load_executions,
        record_execution,
    )

    path = tmp_path / "st.db"
    init_shortterm_db(path)
    for _ in range(2):
        record_execution(
            path, lane="session", ticker="AAPL", side="buy",
            signalled_at="2026-08-04T09:45:00-04:00", expected_price=301.00,
            actual_price=301.44, qty=3.0, order_id="abc",
        )
    assert len(load_executions(path, lane="session")) == 1
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_shortterm_storage.py -k execution -v`
Expected: FAIL — `ImportError: cannot import name 'record_execution'`

- [x] **Step 3: Write the implementation**

In `init_shortterm_db`'s `executescript`, add before the closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS st_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lane TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    signalled_at TEXT NOT NULL,
    expected_price REAL NOT NULL,
    actual_price REAL,
    qty REAL NOT NULL,
    order_id TEXT NOT NULL,
    UNIQUE (order_id)
);
```

Then append to the module:

```python
def record_execution(
    db_path: str | Path,
    *,
    lane: str,
    ticker: str,
    side: str,
    signalled_at: str,
    expected_price: float,
    actual_price: float | None,
    qty: float,
    order_id: str,
) -> None:
    """One broker execution against the price the signal expected. The difference is this
    project's first MEASURED slippage — every other cost number in the codebase is a
    modelled estimate. Keyed by order_id so a re-run never double-counts."""
    with db.connect(db_path) as con:
        con.execute(
            """INSERT OR IGNORE INTO st_executions
               (lane, ticker, side, signalled_at, expected_price, actual_price, qty, order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (lane, ticker, side, signalled_at, expected_price, actual_price, qty, order_id),
        )


def load_executions(db_path: str | Path, lane: str) -> list[dict]:
    with db.connect(db_path) as con:
        con.row_factory = __import__("sqlite3").Row
        rows = con.execute(
            "SELECT * FROM st_executions WHERE lane = ? ORDER BY signalled_at", (lane,)
        ).fetchall()
    return [dict(row) for row in rows]


def slippage_summary(db_path: str | Path, lane: str = "session") -> dict | None:
    """Mean and worst realised slippage in basis points, or None while nothing filled.
    Positive means the fill was WORSE than the signal price for that side."""
    rows = [r for r in load_executions(db_path, lane) if r["actual_price"]]
    if not rows:
        return None
    bps = []
    for row in rows:
        direction = 1.0 if row["side"] == "buy" else -1.0
        bps.append(
            direction * (row["actual_price"] - row["expected_price"])
            / row["expected_price"] * 10_000.0
        )
    return {"n": len(bps), "mean_bps": sum(bps) / len(bps), "worst_bps": max(bps)}
```

Note: check whether `shortterm_storage.py` already imports `sqlite3` at module level and
use that instead of the inline `__import__` if so — match the file's existing idiom.

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_shortterm_storage.py -v`
Expected: all passed (including the two new ones)

- [x] **Step 5: Commit**

```bash
git add src/equity_scout/shortterm_storage.py tests/test_shortterm_storage.py
git commit -m "feat(session): persist expected-vs-actual fills for slippage measurement"
```

---

### Task 5: Staleness gate — no new position after a gap

**Files:**
- Modify: `scripts/run_shortterm.py` (new module-level function)
- Test: `tests/test_run_shortterm_alpaca.py` (create)

- [x] **Step 1: Write the failing tests**

```python
"""The 2026-07-21 outage rule, stated as code: whoever cannot show they were here a bar ago
does not open a new position. Exits stay allowed — abandoning an open position is worse
than any entry rule."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import scripts.run_shortterm as runner

NY = ZoneInfo("America/New_York")
may_open_new_position = runner.may_open_new_position


def test_a_run_one_bar_after_the_last_one_may_open() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=15)).isoformat()
    assert may_open_new_position(last_run=last, now=now) is True


def test_a_gap_of_more_than_one_bar_blocks_new_entries() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=40)).isoformat()
    assert may_open_new_position(last_run=last, now=now) is False


def test_the_very_first_run_may_open() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    assert may_open_new_position(last_run=None, now=now) is True
```

The import style is copied from `tests/test_run_shortterm.py:9` (`import
scripts.run_shortterm as runner`) — `scripts/` is importable as a package, so do not add a
`sys.path` hack. Binding `may_open_new_position` off the module keeps the later
monkeypatch tests in this same file working against `runner`.

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_run_shortterm_alpaca.py -v`
Expected: FAIL — `ImportError: cannot import name 'may_open_new_position'`

- [x] **Step 3: Write the implementation**

In `scripts/run_shortterm.py`, next to `_session_overnight_sweep`:

```python
MAX_RUN_GAP = timedelta(minutes=BAR_MINUTES * 1.5)
LAST_RUN_KEY = "last_session_run"


def may_open_new_position(*, last_run: str | None, now: datetime) -> bool:
    """False when the previous run is more than ~one bar back. A gap means the machine
    cannot promise to be here for the exit either, and an entry without a reliable exit is
    the exact shape of the 2026-07-21 loss. The very first run is allowed: no history is
    not the same as a gap. Exits and sweeps ignore this gate entirely."""
    if last_run is None:
        return True
    return now - datetime.fromisoformat(last_run) <= MAX_RUN_GAP
```

Add `from equity_scout.alpaca_data import BAR_MINUTES` to the imports (or reuse the
existing `intraday_bars.BAR_MINUTES` import if one is already there — they are both 15;
do not import both).

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_run_shortterm_alpaca.py -v`
Expected: 3 passed

- [x] **Step 5: Commit**

```bash
git add scripts/run_shortterm.py tests/test_run_shortterm_alpaca.py
git commit -m "feat(session): block new entries after a run gap"
```

---

### Task 6: Wire the broker path into `run_session`

**Files:**
- Modify: `scripts/run_shortterm.py:172-229` (`run_session`)
- Test: `tests/test_run_shortterm_alpaca.py` (append)

This is the task where the lane changes behaviour. Keep the yfinance path reachable via
`--feed yfinance` so a broken key never silently stops the lane — it degrades to the old,
biased-but-working path with a loud warning rather than trading nothing.

> **Revised 2026-08-05 (design decisions 5 + 7).** Two changes to what is written below.
> First, `run_session` now fetches twice: 15Min bars to build the opening range,
> 1Min bars to test the breakout against. `st_session.decide()` keeps its signature —
> it receives the range it always received, just evaluated against a fresher last price.
> Second, `MAX_RUN_GAP` was `BAR_MINUTES * 1.5` = 22.5 min against a `*/15` cron. On a
> minute cron the same 1.5-interval reasoning gives 90 s, which would alarm on every
> ordinary hiccup. Size it against the *cron* period, not the bar period: `MAX_RUN_GAP =
> timedelta(minutes=5)` — long enough to ride out a slow fetch, short enough that a dead
> cron is caught inside one opening range.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_shortterm_alpaca.py`:

```python
import pandas as pd
import pytest

from equity_scout.alpaca_broker import BrokerOrder, BrokerPosition
from equity_scout.shortterm_storage import init_shortterm_db, load_executions

run_shortterm = runner  # same module, name kept for readability in these tests


def _bars() -> pd.DataFrame:
    idx = pd.date_range("2026-08-04 09:30", periods=5, freq="15min", tz=NY)
    # opening range 09:30-10:00 = [100, 102]; the 10:00 bar closes above it -> signal,
    # the 10:15 bar opens at 103 -> that is the fill.
    return pd.DataFrame(
        {"open": [100.0, 101.0, 102.5, 103.0, 104.0],
         "high": [102.0, 102.0, 103.5, 104.5, 105.0],
         "low": [100.0, 100.5, 102.0, 102.8, 103.5],
         "close": [101.0, 101.5, 103.0, 104.0, 104.5],
         "volume": [1000] * 5},
        index=idx,
    )


def test_a_breakout_places_a_bracket_order_and_books_the_broker_fill(tmp_path, monkeypatch):
    db_path = tmp_path / "st.db"
    init_shortterm_db(db_path)
    placed = {}

    def fake_place(ticker, *, qty, stop_price, target_price):
        placed.update(ticker=ticker, qty=qty, stop=stop_price, target=target_price)
        return BrokerOrder(order_id="o1", status="filled", filled_qty=float(int(qty)),
                           filled_avg_price=103.12)

    monkeypatch.setattr(run_shortterm, "alpaca_fetch_bars", lambda tickers, now: {"AAPL": _bars()})
    monkeypatch.setattr(run_shortterm, "fetch_broker_positions", dict)
    monkeypatch.setattr(run_shortterm, "place_bracket", fake_place)

    run_shortterm.run_session(
        str(db_path), now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca"
    )

    assert placed["ticker"] == "AAPL"
    # entry 103.0, range 2.0 -> stop 102.0, target 105.0
    assert placed["stop"] == pytest.approx(102.0)
    assert placed["target"] == pytest.approx(105.0)
    rows = load_executions(db_path, lane="session")
    assert rows[0]["expected_price"] == pytest.approx(103.0)
    assert rows[0]["actual_price"] == pytest.approx(103.12)


def test_a_divergence_is_reported_and_does_not_silently_merge(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "st.db"
    init_shortterm_db(db_path)
    monkeypatch.setattr(run_shortterm, "alpaca_fetch_bars", lambda tickers, now: {"AAPL": _bars()})
    monkeypatch.setattr(
        run_shortterm, "fetch_broker_positions",
        lambda: {"TSLA": BrokerPosition("TSLA", 4.0, 330.0)},
    )
    monkeypatch.setattr(run_shortterm, "place_bracket",
                        lambda *a, **k: BrokerOrder("o2", "filled", 1.0, 103.0))

    run_shortterm.run_session(
        str(db_path), now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca"
    )
    out = capsys.readouterr().out
    assert "ABWEICHUNG" in out and "TSLA" in out


def test_a_stale_run_manages_positions_but_opens_nothing(tmp_path, monkeypatch):
    db_path = tmp_path / "st.db"
    init_shortterm_db(db_path)
    from equity_scout.shortterm_storage import set_lane_state

    set_lane_state(db_path, "session", run_shortterm.LAST_RUN_KEY,
                   datetime(2026, 8, 4, 9, 0, tzinfo=NY).isoformat())
    monkeypatch.setattr(run_shortterm, "alpaca_fetch_bars", lambda tickers, now: {"AAPL": _bars()})
    monkeypatch.setattr(run_shortterm, "fetch_broker_positions", dict)

    def refuse(*args, **kwargs):
        raise AssertionError("no entry may be placed after a run gap")

    monkeypatch.setattr(run_shortterm, "place_bracket", refuse)
    run_shortterm.run_session(
        str(db_path), now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca"
    )
```

Both accessors exist as written: `shortterm_storage.get_lane_state:205` and
`set_lane_state:214`, each taking `(db_path, lane, key[, value])`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_run_shortterm_alpaca.py -v`
Expected: FAIL — `AttributeError: module 'run_shortterm' has no attribute 'alpaca_fetch_bars'`

- [ ] **Step 3: Write the implementation**

Add the imports at the top of `scripts/run_shortterm.py` (aliased so tests can monkeypatch
them on the module):

```python
from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    close_position,
    fetch_positions as fetch_broker_positions,
    place_bracket,
)
from equity_scout.alpaca_data import complete_bars
from equity_scout.alpaca_data import fetch_bars as alpaca_fetch_bars
from equity_scout.session_reconcile import reconcile
from equity_scout.shortterm_storage import record_execution
```

Then restructure `run_session` — the decision loop is unchanged, only the fill path and the
surrounding bookkeeping move:

```python
def run_session(db: str, *, now: datetime, feed: str = "alpaca") -> None:
    if feed == "alpaca" and not os.getenv("ALPACA_API_KEY_ID"):
        print("WARN Alpaca-Keys fehlen — Session-Lane faellt auf yfinance zurueck "
              "(verzoegerte Bars, Executability-Bias).", file=sys.stderr)
        feed = "yfinance"

    if not within_market_window(now):
        book = load_book(db, "session")
        if book is not None and book.positions:
            _session_overnight_sweep(db, book, now=now, feed=feed)
        else:
            print("Außerhalb des US-Marktfensters — Session-Lane hat nichts zu tun.")
        return

    book = load_book(db, "session") or LaneBook.fresh("session", benchmark_ticker="SPY")
    state = json.loads(get_lane_state(db, "session", SESSION_STATE_KEY) or "{}")
    tickers = sorted({*SESSION_UNIVERSE, *book.positions})

    if feed == "alpaca":
        all_bars = alpaca_fetch_bars(tickers, now=now)
        gate = lambda bars: complete_bars(bars, now)  # noqa: E731 - one-line feed switch
        broker_positions = fetch_broker_positions()
        for divergence in reconcile(book, broker_positions):
            print(f"ABWEICHUNG {divergence.describe()} — Buch und Broker laufen auseinander.",
                  file=sys.stderr)
    else:
        all_bars = fetch_bars(tickers)
        gate = lambda bars: settled_bars(bars, now)  # noqa: E731

    if not all_bars:
        print("Keine Intraday-Bars verfügbar — Lauf übersprungen.")
        return

    may_open = may_open_new_position(
        last_run=get_lane_state(db, "session", LAST_RUN_KEY), now=now
    )
    if not may_open:
        print("Lücke seit dem letzten Lauf — nur Bestandsführung, keine neuen Einstiege.")

    session_date = next(iter(all_bars.values())).index[0].date().isoformat()
    if state.get("date") != session_date:
        state = {"date": session_date, "last_bar": {}, "ranges": {}, "traded": []}

    book, fills = _flatten_stale_positions(book, all_bars, session_date, now)
    prices: dict[str, float] = {}
    for ticker, bars in all_bars.items():
        settled = gate(bars)
        if settled.empty:
            continue
        prices[ticker] = float(settled["close"].iloc[-1])
        or_range = state["ranges"].get(ticker) or opening_range(settled)
        if or_range is None:
            continue
        state["ranges"][ticker] = list(or_range)
        actions, new_marker = decide(
            ticker, settled, book.positions.get(ticker),
            or_range=tuple(or_range),
            last_processed=state["last_bar"].get(ticker),
            traded_today=ticker in state["traded"],
        )
        for action in actions:
            if action.kind == "buy":
                if not may_open:
                    continue
                book, fill = _open_position(
                    db, book, action, or_range=tuple(or_range), feed=feed
                )
                if fill:
                    state["traded"].append(ticker)
            else:
                book, fill = _close_position(db, book, action, feed=feed)
            if fill:
                fills.append(fill)
        if new_marker:
            state["last_bar"][ticker] = new_marker

    book = capture_benchmark(book, prices.get("SPY"))
    snap = valuation(book, prices, prices.get("SPY"), _hour_stamp(now))
    persist_lane_step(db, book, updated_at=now.isoformat(timespec="seconds"),
                      trades=fills, valuation=snap,
                      state=[(SESSION_STATE_KEY, json.dumps(state)),
                             (LAST_RUN_KEY, now.isoformat())])
    print(f"Session {session_date}: Equity {snap.equity:,.2f} ({snap.total_return:+.2%}), "
          f"{len(book.positions)} offen, {len(fills)} Fills")
    _print_fills(fills)
```

And the two fill helpers, which hold the whole difference between the feeds:

```python
def _open_position(db: str, book: LaneBook, action, *, or_range: tuple[float, float],
                   feed: str) -> tuple[LaneBook, TradeFill | None]:
    """Size locally, then either route the order or book it simulated.

    On the Alpaca path the fill price comes from the BROKER, and slippage is not modelled
    on top of it — the broker price already contains the real thing. Booking the 5-bps
    estimate as well would charge the lane twice for the same cost.
    """
    if feed != "alpaca":
        return buy(book, action.ticker, action.price, action.at,
                   fraction=SESSION_FRACTION, reason=action.reason)

    or_high, or_low = or_range
    range_size = or_high - or_low
    probe, _ = buy(book, action.ticker, action.price, action.at,
                   fraction=SESSION_FRACTION, reason=action.reason)
    intended = probe.positions.get(action.ticker)
    if intended is None:
        return book, None
    try:
        order = place_bracket(
            action.ticker,
            qty=intended.qty,
            stop_price=action.price - STOP_RANGE_MULT * range_size,
            target_price=action.price + TARGET_RANGE_MULT * range_size,
        )
    except AlpacaBrokerError as error:
        print(f"Order abgelehnt ({action.ticker}): {error}", file=sys.stderr)
        return book, None
    if not order.filled_qty or order.filled_avg_price is None:
        print(f"Order {order.order_id} ({action.ticker}) noch nicht ausgefuehrt "
              f"(status={order.status}) — Buchung erfolgt im naechsten Lauf.", file=sys.stderr)
        return book, None
    record_execution(
        db, lane="session", ticker=action.ticker, side="buy", signalled_at=action.at,
        expected_price=action.price, actual_price=order.filled_avg_price,
        qty=order.filled_qty, order_id=order.order_id,
    )
    return buy(book, action.ticker, order.filled_avg_price, action.at,
               fraction=SESSION_FRACTION, reason=action.reason, slippage_bps=0.0)


def _close_position(db: str, book: LaneBook, action, *,
                    feed: str) -> tuple[LaneBook, TradeFill | None]:
    """Exits on the Alpaca path may already have happened in the market — the bracket legs
    fire without us. `close_position` is therefore best-effort: a 'position not found' is
    the normal case after a stop or target triggered, not an error."""
    if feed != "alpaca":
        return sell(book, action.ticker, action.price, action.at, reason=action.reason)
    try:
        order = close_position(action.ticker)
        price = order.filled_avg_price or action.price
        record_execution(
            db, lane="session", ticker=action.ticker, side="sell", signalled_at=action.at,
            expected_price=action.price, actual_price=order.filled_avg_price,
            qty=order.filled_qty, order_id=order.order_id,
        )
    except AlpacaBrokerError as error:
        print(f"Schliessen ueber Broker fehlgeschlagen ({action.ticker}): {error} — "
              f"Buch wird zum Signalpreis geschlossen, Abweichung im naechsten Abgleich.",
              file=sys.stderr)
        price = action.price
    return sell(book, action.ticker, price, action.at, reason=action.reason, slippage_bps=0.0)
```

`_session_overnight_sweep` gains the same `feed` parameter and calls `_close_position`
instead of `sell` directly — otherwise the nightly sweep would flatten the book while
leaving the broker holding the position, which is precisely the divergence this design
exists to prevent.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_run_shortterm_alpaca.py tests/test_run_shortterm.py -v`
Expected: all passed — the existing session tests must stay green on the yfinance path.

- [ ] **Step 5: Run the full gate**

Run: `uv run pytest -q && uv run ruff check .`
Expected: green, clean

- [ ] **Step 6: Commit**

```bash
git add scripts/run_shortterm.py tests/test_run_shortterm_alpaca.py
git commit -m "feat(session): route entries as bracket orders and book real fills"
```

---

### Task 7: Mark the regime break on the dashboard

**Files:**
- Modify: `scripts/run_shortterm.py` (write `execution_regime` once, on the first Alpaca fill)
- Modify: `src/equity_scout/api.py` (`/api/shortterm` payload)
- Modify: `frontend/src/components/ShorttermPanel.tsx`
- Test: `tests/test_api_shortterm.py` (append)

A track record whose measurement method changed mid-flight, without saying so, is a lie by
omission. The equity numbers need no correction — the label does.

**Deliberately NOT in the digest.** The Telegram diet of 2026-08-04 cut the arena to one
line with a ≤ 16-line budget for the whole message; a standing regime footnote is exactly
the kind of reference material that decision moved to the dashboard. The rule from that
session applies — nothing leaves Telegram that the dashboard does not show — and here the
dashboard shows it, so Telegram does not need to.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_shortterm.py` (match the file's existing client fixture and
`shortterm.db` monkeypatching — read the top of the file first):

```python
def test_shortterm_payload_exposes_the_execution_regime(tmp_path, monkeypatch) -> None:
    from equity_scout.shortterm_storage import init_shortterm_db, set_lane_state

    path = tmp_path / "st.db"
    init_shortterm_db(path)
    set_lane_state(path, "session", "execution_regime", "2026-08-05T09:45:00-04:00")
    # ...point the app at `path` the same way the other tests in this file do...
    payload = client.get("/api/shortterm").json()
    session = next(lane for lane in payload["lanes"] if lane["lane"] == "session")
    assert session["execution_regime"] == "2026-08-05T09:45:00-04:00"


def test_lanes_without_the_marker_report_none(tmp_path, monkeypatch) -> None:
    from equity_scout.shortterm_storage import init_shortterm_db

    path = tmp_path / "st.db"
    init_shortterm_db(path)
    payload = client.get("/api/shortterm").json()
    assert all(lane["execution_regime"] is None for lane in payload["lanes"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_api_shortterm.py -k regime -v`
Expected: FAIL — `KeyError: 'execution_regime'`

- [ ] **Step 3: Implement**

In `scripts/run_shortterm.py`, next to `LAST_RUN_KEY`:

```python
EXECUTION_REGIME_KEY = "execution_regime"
```

and in `_open_position`, immediately after the successful `record_execution(...)` call:

```python
    if get_lane_state(db, "session", EXECUTION_REGIME_KEY) is None:
        set_lane_state(db, "session", EXECUTION_REGIME_KEY, action.at)
```

In `api.py`, add one field per lane in the `/api/shortterm` builder:

```python
        "execution_regime": get_lane_state(db_path, lane, "execution_regime"),
```

In `ShorttermPanel.tsx`, extend the lane type with `execution_regime: string | null` and
render, under the session lane's heading only when the field is set:

```tsx
{lane.execution_regime && (
  <p className="note">
    Echte Broker-Fills (Alpaca Paper) seit dem{" "}
    {new Date(lane.execution_regime).toLocaleDateString("de-DE")}. Davor: simulierte Fills
    auf verzögerten Kursen — der frühere Verlauf ist dadurch zu günstig.
  </p>
)}
```

`note` is the existing muted-text class in this codebase; confirm the class name against a
neighbouring component rather than adding a new style.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_api_shortterm.py -v && npm run typecheck --prefix frontend && npm run build --prefix frontend`
Expected: passed, exit 0, build ok

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(session): label the execution-regime break on the dashboard"
```

---

### Task 8: Documentation and plan outcome

**Files:**
- Modify: `README.md` (Kurzfrist-Arena section), `.env.example`, `PLAN.md`, this file

- [ ] **Step 1: Add the keys to `.env.example`**

```bash
# Alpaca PAPER keys for the session lane (free, no KYC — app.alpaca.markets, Paper Trading).
# Real-money keys must never be used here; LOOP.md forbids live routing.
ALPACA_API_KEY_ID=
ALPACA_API_SECRET_KEY=
```

- [ ] **Step 2: README** — in the Kurzfrist-Arena section, replace the session lane's
"~15-min DELAYED bars" description with the real-time/bracket-order reality, and state the
executability bias that the old track carried, with the date of the break.

- [ ] **Step 3: PLAN.md** — add a phase block for this work, check off the v11 backlog line
"Session-Lane auf Alpaca-IEX-Echtzeit umstellbar" with the completion date.

- [ ] **Step 4: This file** — write the outcome section: measured bar ages from the
verification run, what deviated from the plan, what is still open.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs(session): record the Alpaca paper switch and its measured premises"
```

---

### Task 9: Run the session lane every minute (added 2026-08-05, design decision 7)

**Files:**
- Modify: `scripts/intraday_copilot.sh` (drop the `st_session` step)
- Create: `scripts/session_lane.sh` (session lane only, own flock)
- Modify: `crontab` (one new line, one shortened)
- Modify: `src/equity_scout/run_watchdog.py` (expected cadence)
- Test: `tests/test_run_shortterm_alpaca.py` (quiet-run assertion)

Ordering note: this task is what actually delivers the latency win, but it must come
**last**. Running the old 15-minute logic 15× more often changes nothing except the log
volume; running the new logic on the old cadence wastes most of the gain. Land Tasks 1–6
first, then flip the cadence in one reviewable step.

- [x] **Step 1: Silence the no-op run first — this is a prerequisite, not polish**

At `*/15` the lane produces ~26 log blocks a day and every one is worth reading. At
`* * * * *` it produces ~390, and `intraday.log` (220 kB today) becomes unreadable within a
week — which is how the two production bugs this project already hit stayed invisible.

Before touching the cron: make `run_session` print its block **only when something
happened** (a fill, an order placed, a rejection, an error, or the session's first and last
run of the day). A run that looks at bars and decides nothing writes nothing. Add a test
that asserts the quiet path produces no output.

- [ ] **Step 2: Split the script**

`scripts/session_lane.sh` runs only the session lane, with its own lock file
(`/tmp/equity-scout-session.lock`) so it can never be blocked by — or block — the slower
chain. `scripts/intraday_copilot.sh` keeps radar, evidence and notify and loses the
`st_session` step.

- [ ] **Step 3: Cron**

```cron
* * * * 1-5 flock -n /tmp/equity-scout-session.lock  <repo>/scripts/session_lane.sh  >> <repo>/session.log 2>&1
*/15 * * * 1-5 flock -n /tmp/equity-scout-intraday.lock <repo>/scripts/intraday_copilot.sh >> <repo>/intraday.log 2>&1
```

Own log file. `flock -n` skips rather than queues, so a slow minute is dropped, never
stacked. The `within_market_window` guard already keeps out-of-hours runs from doing work —
verify that it exits before any network call, otherwise the lane fetches bars 1,440 times a
day for nothing.

- [ ] **Step 4: Watchdog**

`run_watchdog.py` was written against a 15-minute cadence. Update its expected gap for the
session lane and confirm it does not alarm on ordinary skipped minutes — one missed minute
is normal, ten in a row is not.

- [ ] **Step 5: Verify on a live session, then commit**

The day after: confirm from `session.log` that runs happened every minute inside the window
and that the log is still readable. Record the measured entry latency — the gap between the
1-minute bar that triggered and the order timestamp — in the outcome section. That number
is the whole point of this plan; "it felt fast" is not a record.

---

## Risks that are not resolved by this plan

1. **IEX is ~2–3 % of US volume.** For 15-minute OHLC on mega-caps that is enough to shape a
   bar, but IEX highs and lows can differ from the consolidated tape. The opening range —
   and therefore every stop and target — is computed from a partial view of the market.
   Measurable later against the SIP-based daily panel; not measurable now. At 1-minute
   resolution this stops being a caveat and becomes a gate: the density check in the
   precondition decides whether the trigger resolution is viable at all. Even at 100 %
   density the 1-minute high/low is a *thin* high/low — a breakout level touched only on
   other venues does not exist for us, so the lane will systematically miss some real moves.
   That is a miss, not a false fill, and it is the acceptable direction to be wrong in.
2. **Alpaca paper fills are simulated**, not matched against real resting liquidity. They
   remove the executability bias (the price existed when the order was sent) but they are
   not proof of executability at size. At 10,000 USD across mega-caps, size is not the
   binding constraint — this is a small caveat, not a fatal one.
3. **Bracket orders are day-only.** If the evening sweep fails, the position closes at the
   next open rather than overnight-flat. Risk drops from "unprotected for days" to "flat one
   session late". It does not vanish.
4. **Five strategy trades are not a sample.** After this rewrite the strategy is not proven;
   it is measurable for the first time.
5. **Task 0 and the bracket orders overlap but do not replace each other.** Task 0 makes the
   force-flat reachable; the resting legs protect the position when no run happens at all.
   Keep both — they fail in different ways.
6. **Faster entries are not better entries.** This plan removes a delay; it does not add
   edge. It is entirely possible that the 44-minute lag was accidentally *protecting* the
   lane by filtering out the noisiest breakouts, and that trading them promptly makes the
   track worse. That would be a real finding, not a failure of the rewrite — but it means
   the post-change track must be judged on its own, against its own DSR hurdle, and not
   spliced onto the 48 trades that came before it. The `execution_regime` marker (design
   decision 1) is what keeps that honest.

## Outcome

_(to be filled after execution)_

### Precondition run 1 — 2026-08-05 20:50 UTC, market CLOSED

Keys were already on disk, in `signal-trader-demo/.env` under different names
(`ALPACA_API_KEY` / `ALPACA_API_SECRET`); copied into `equity-scout/.env` as
`ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY`. Note the invocation: this repo has no
`python-dotenv`, the shell scripts `. ./.env`. A bare `uv run python scripts/...` sees
nothing. Use:

```bash
set -a && . ./.env && set +a && uv run python scripts/verify_alpaca_paper.py
```

| Check | Result |
|---|---|
| [1/4] Credentials | **PASS** — account `PA3AKCY23RCD`, ACTIVE, paper (`PK…` key prefix) |
| [2/4] Density, 1Min | **PASS** — 9 of 10 tickers at 100 %, QQQ 98 % |
| [2/4] Freshness | **not measurable** — market closed, ages 1.4–65 min are meaningless |
| [3/4] Order accepted | **PASS** — limit buy 1 AAPL, accepted and cancelled, nothing left |
| [4/4] Resting stop | **PASS** — stop buy 1 AAPL, accepted and cancelled, nothing left |

Both order probes were rewritten before running them, because as written they were unsafe
during market hours: [3/4] placed a **market** order, which fills in milliseconds while the
market is open — the DELETE that follows then cannot cancel a filled order and the probe
leaves a real position behind. [4/4] placed a stop **sell** without a position, i.e. a
short, which a fresh paper account may reject. Both are now priced 20 % away from the
market (limit buy below, stop buy above) so neither can fill in either market state.
Verified after the run: 0 open orders, no new position.

**Freshness is now automated** rather than waiting for a hand-run: `scripts/verify_alpaca_guarded.sh`
(cron `0 16-21 * * 1-5`) runs the full check hourly inside the US session and **disarms
itself** by writing `.state/alpaca_verified` on the first pass — so the order probes are
placed once, not daily. Output goes to `alpaca_verify.log`. The script's new `--require-open`
flag exits 2 when the market is closed, so a closed-market run can never write the marker
and call an unmeasured freshness "green". Re-arm by deleting the marker.

It also **notifies by Telegram** (`scripts/notify_alpaca_verify.py`, on Nico's request) —
on a pass and on a real failure, never on a closed-market skip, which happens on most slots
and would train the recipient to ignore the one message that matters. The message quotes the
measured 1-minute ages, and a failure names the fallback (coarser trigger resolution) rather
than only reporting doom. Send path verified live 2026-08-05 with sample data.

**Density holds, which was the gate that could have killed the 1-minute trigger.** IEX
prints essentially every regular-session minute for these mega-caps.

The first density run reported 20–72 % for MSFT, AMD, AAPL and SPY and would have condemned
the design. That was a defect in the check, not in the feed: those four were the only
tickers still printing after 20:00 UTC, so a window anchored on their newest bar fell into
the thin after-hours tape. Fixed in `7df0f1b` — density is measured over regular-session
bars only. The lesson is worth keeping: a freshness/density metric anchored on "the last
bar" silently changes meaning outside session hours.

### Blocker found during the run: the paper account is not ours alone

The account already carries **1 share of AAPL**, bought 2026-06-18 — a smoke test from
`signal-trader-demo`, which shares these keys. Equity 100,012.37, one order in the whole
history. This breaks Task 3's premise: reconciliation treats broker positions as the truth,
and AAPL is in `SESSION_TICKERS`, so that share would be read as a lane position on the
first run.

**RESOLVED same evening.** Nico created a dedicated paper account named "Short Term" and
swapped its keys into `equity-scout/.env`. Verified: account **`PA3SIKMAPF0N`**, 100,000 USD,
**0 positions, 0 orders** — signal-trader-demo keeps its own book on the old keys. All
checks re-run green against the new account (order probes included).

### Precondition status

| Check | State |
|---|---|
| [1/4] Credentials | PASS (new account) |
| [2/4] Density 1Min | PASS (9× 100 %, QQQ 98 %) |
| [3/4] + [4/4] Orders | PASS (accepted + cancelled, nothing left behind) |
| [2/4] Freshness | **still open** — needs an open session; the cron runner collects it |

Tasks 1–8 unblock the moment freshness passes. Task 0 is already done.

### Build round 1 — 2026-08-05 night, Tasks 1–5 + Task 9 Step 1

Built ahead of the freshness measurement on the explicit judgement that these five tasks do
not depend on it: all of them are tested against faked HTTP responses, so how fast the feed
is cannot change the code. Tasks 6 and 9 (which actually switch the lane over and change the
cadence) deliberately wait — flipping production on an unmeasured premise is the exact
failure the precondition exists to prevent.

Commits `5c0b83d` … `cb2ca9d`. Gate at the end: **1314 tests, ruff clean.**

Deviations from the plan as written, each deliberate:

1. **Task 2 built before Task 1.** `alpaca_data` imports `DATA_BASE`/`auth_headers` from
   `alpaca_broker`, so Task 1's tests would have failed on the import, not on the assertion.
2. **Real bug in Task 1's `fetch_bars`:** `.astimezone(tz=None)` converts to the machine's
   local zone while the `"Z"` suffix claims UTC — the request window would have been shifted
   by the local offset (two hours in Berlin summer). Now `timezone.utc`.
3. **Resolution is a parameter, not a constant** (design decision 5): `complete_bars(...,
   bar_minutes=...)` and `fetch_bars(..., bar_minutes=...)`, with `RANGE_BAR_MINUTES = 15`
   and `TRIGGER_BAR_MINUTES = 1` exported.
4. **`parse_order` distinguishes 0.0 from None.** The plan's `float(price) if price` folds a
   zero fill price into "not filled yet"; those mean opposite things to the reconciliation.
   Same fix in `slippage_summary`'s row filter.
5. **`MAX_RUN_GAP` is an argument with a default, not a hardcoded constant.** Task 5 said
   `BAR_MINUTES * 1.5` (22.5 min) and Task 6's revision said 5 min — because the gate
   measures *missed cron slots*, so its tolerance belongs to the cadence, which changes in
   Task 9. Default is 5 min (target cadence); the caller may override. Also rejects a
   *future* `last_run`: clock skew is not evidence that we were just here (cf. the
   2026-07-24 Tokyo-timestamp incident).
6. **Task 4 follows the module's own idiom** — explicit column list plus `dict(zip(keys,
   row))`, as `load_trades` does — rather than the plan's `SELECT *` with a row factory.
   `st_executions` needs no migration: every accessor calls `init_shortterm_db`, and
   `CREATE TABLE IF NOT EXISTS` makes existing DBs self-migrating.

Tests added beyond the plan, each covering a boundary the plan left open: the zero-fill
price, the exact one-share reconciliation tolerance, a sub-share book position the broker
never took, stable divergence ordering, `describe()` output, the slippage sign convention
on both sides (a buy filled high and a sell filled low are both positive bps), `None`
slippage while nothing has filled, the gate's tolerance boundary and its future-stamp
rejection.

**Note for the next session — this already changed production behaviour.** Task 9 Step 1 is
live on the current `*/15` cadence: the session lane now prints its report block only on a
fill or on the first run of the day, so the log goes from ~26 blocks a day to two or three.
That is intended, but it means a quiet `intraday.log` is no longer evidence of a problem.
