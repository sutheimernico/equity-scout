# Ignition Fill Booking & Broker Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the ignition lane's book match what the broker actually holds, alarm on any future divergence, clean up the 296 orphaned MRVI shares, and put PBO back on a schedule so the research ledger's overfitting number stops rotting.

**Architecture:** Three independent changes. (1) The entry path in `run_ignition_lane.py` calls `settle_or_cancel` and books ITS return value — the function already computes the final post-cancel state, the caller was throwing it away. (2) A new pure module compares book positions against broker positions; the ignition runner records a divergence into `st_state`, and the watchdog — which is DB-only by design — alarms on that state with the existing per-chain cooldown. (3) `run_pbo.py` joins the weekly chain, where its own docstring says it belongs ("run it occasionally, not in the loop").

**Tech Stack:** Python 3.12, sqlite3 (raw, repo idiom), pytest, ruff, Alpaca paper REST via `equity_scout.alpaca_broker`.

---

## Context: what is actually broken

Measured on 2026-08-24 against the live paper account PA3SIKMAPF0N.

**Defect 1 — fills after the poll window are never booked.** `scripts/run_ignition_lane.py:191-196`:

```python
filled = await_fill(order)
if filled is None or not filled.filled_qty or not filled.filled_avg_price:
    settle_or_cancel(order)      # <-- return value discarded
    print(f"  {ticker}: Limit nicht erreicht — kein Einstieg (das ist ok)")
    continue
```

`await_fill` polls 6 × 0.4 s and NEVER cancels. When the fill lands later, `settle_or_cancel`
is called, tries to cancel, gets refused because the order completed, re-reads the final state
— and the caller throws that state away and `continue`s. The position exists at the venue and
not in the book. Next minute `book.positions` and `traded_today` are both still empty, so the
lane enters again.

MRVI on 2026-08-19 was bought THREE times: 142 @ 7.01 (17:59), 141 @ 7.07 (18:01),
141 @ 7.05 (18:04) = 424 shares. `st_trades` holds one row: 128 @ 7.0535.

**Defect 2 — a partial fill is booked as if complete.** The third order filled 76+42+10 = 128
inside the poll window and 13 more three seconds later. `await_fill` returned a
`partially_filled` order, the caller tested only `filled.filled_qty` for truthiness and booked
128 against the broker's eventual 141. `await_fill`'s own docstring warns about exactly this
("FULLY filled, not something filled").

Both defects disappear when the caller uses `settle_or_cancel`'s return value: it awaits, cancels
what is still resting, and re-reads — so whatever it reports is final, and booking it leaves book
and broker holding the same quantity.

**Defect 3 — nothing checks the book against the broker.** `equity_scout/watchdog.py` judges
heartbeat age and scheduler gaps only. The 296-share divergence sat unnoticed for five days.

**Defect 4 — PBO is stale, not wrong.** `research_ledger.db` holds PBO 0.7714 computed
2026-06-26 over 13 configs; the ledger now has 4,600 trials. `grep -rn run_pbo scripts/*.sh`
finds nothing: the script has never been wired into any chain.

**NOT a defect (checked, do not "fix"):** the DSR hurdle. `current_hurdle` = E[max Sharpe of N
trials] is the *deflation benchmark inside* the PSR call (`ledger.py:144`), not a pass/fail gate.
Comparing `sharpe_periodic > dsr_hurdle` is not the test the system makes. The real distribution
is DSR median 0.946 with 2,033 of 4,600 above 0.95, which is high because 4,600 configs over one
sample are not the independent trials the Gumbel term assumes — the known limitation PBO exists
to measure. That is why this plan schedules PBO instead of touching the hurdle formula.

---

## File Structure

- `src/equity_scout/broker_reconcile.py` — NEW. Pure comparison of book quantities vs broker
  quantities. No I/O, no network: the runner fetches, this decides. ~60 lines.
- `scripts/run_ignition_lane.py` — MODIFY. Entry path books `settle_or_cancel`'s result;
  after persisting, records any book-vs-broker divergence into `st_state`.
- `src/equity_scout/watchdog.py` — MODIFY. Add `position_divergence(db_path)` reading the state
  the runner wrote, and include it in the alert text builder.
- `scripts/run_watchdog.py` — MODIFY. Report a divergence through the existing cooldown path.
- `scripts/scheduled_run.sh` — MODIFY. Append the PBO step to the weekly chain.
- `tests/test_ignition_runner.py` — NEW. The two booking defects, as failing tests first.
- `tests/test_broker_reconcile.py` — NEW. The pure comparison.
- `tests/test_watchdog.py` — MODIFY. Divergence alarm.

---

### Task 1: Book what the broker really filled

**Files:**
- Modify: `scripts/run_ignition_lane.py:191-196`
- Test: `tests/test_ignition_runner.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ignition_runner.py`:

```python
"""The two booking defects the live run of 2026-08-19 produced: MRVI was bought three times
(424 shares at the venue) and booked once (128), because the entry path threw away the only
state that knew what had actually filled. Both tests feed the case the old code did NOT
handle — a fill that lands after the poll window, and a partial fill."""
from __future__ import annotations

from equity_scout.alpaca_broker import BrokerOrder
import scripts.run_ignition_lane as runner


def test_a_fill_that_lands_after_the_poll_window_is_booked() -> None:
    """await_fill gives up unfilled; settle_or_cancel's cancel is refused because the order
    completed, and its re-read is the fact. Discarding it left the venue holding a position
    the book never saw — and the next minute bought it again."""
    settled = BrokerOrder(order_id="o1", status="filled", filled_qty=142.0,
                          filled_avg_price=7.01)
    assert runner.bookable(settled) == (142.0, 7.01)


def test_a_partial_fill_books_exactly_what_filled() -> None:
    """settle_or_cancel cancels the resting remainder, so a partial fill is final: book the
    128 that filled, not the 141 that were ordered."""
    settled = BrokerOrder(order_id="o2", status="canceled", filled_qty=128.0,
                          filled_avg_price=7.05)
    assert runner.bookable(settled) == (128.0, 7.05)


def test_nothing_filled_is_no_entry() -> None:
    settled = BrokerOrder(order_id="o3", status="canceled", filled_qty=0.0,
                          filled_avg_price=None)
    assert runner.bookable(settled) is None


def test_a_quantity_without_a_price_is_no_entry() -> None:
    """A fill we cannot price cannot be booked honestly — the book would carry an invented
    entry price and every later return would be measured against it."""
    settled = BrokerOrder(order_id="o4", status="filled", filled_qty=10.0,
                          filled_avg_price=None)
    assert runner.bookable(settled) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_ignition_runner.py -v
```

Expected: 4 × FAIL, `AttributeError: module 'scripts.run_ignition_lane' has no attribute 'bookable'`

- [ ] **Step 3: Add `bookable` and use `settle_or_cancel`'s return value**

In `scripts/run_ignition_lane.py`, add above `main()`:

```python
def bookable(settled: BrokerOrder) -> tuple[float, float] | None:
    """(qty, price) to book from a SETTLED order, or None when there is nothing to book.

    `settle_or_cancel` has already awaited, cancelled whatever still rested and re-read the
    order, so its quantity is final even for a partial fill — booking it is what keeps the
    book and the venue holding the same number of shares. The live run of 2026-08-19 booked
    `await_fill`'s intermediate state instead (128 of 141 shares) and discarded the settled
    state entirely when the fill arrived after the poll window (two whole entries, 283
    shares, 3x the intended position).
    """
    if not settled.filled_qty or settled.filled_avg_price is None:
        return None
    return settled.filled_qty, settled.filled_avg_price
```

Replace lines 191-196 (the `await_fill` block) with:

```python
        try:
            order = place_limit_bracket(
                ticker, qty=qty, limit_price=pick["limit_price"],
                stop_price=pick["stop_price"], target_price=pick["target_price"],
            )
            booked = bookable(settle_or_cancel(order))
            if booked is None:
                print(f"  {ticker}: Limit nicht erreicht — kein Einstieg (das ist ok)")
                continue
            filled_qty, filled_price = booked
        except AlpacaBrokerError as exc:
            print(f"Broker lehnte Einstieg {ticker} ab: {exc}", file=sys.stderr)
            continue
```

Then replace the three later uses of `filled.filled_qty` / `filled.filled_avg_price` in the
same loop body with `filled_qty` / `filled_price`:

```python
        book, fill = buy(book, ticker, filled_price,
                         now.isoformat(timespec="seconds"), fraction=ENTRY_FRACTION,
                         reason=pick["reason"], qty=filled_qty)
        if fill:
            trades.append(fill)
            entries_today += 1
            high_water[ticker] = filled_price
            if pick.get("signal_id"):
                traded_signal_ids.append(pick["signal_id"])
            record_execution(
                args.shortterm_db, lane=LANE, ticker=ticker, side="buy",
                signalled_at=now.isoformat(timespec="seconds"),
                expected_price=pick["limit_price"], actual_price=filled_price,
                qty=filled_qty, order_id=order.order_id,
            )
            print(f"  GEKAUFT {ticker} {filled_qty} Stk @ "
                  f"{filled_price:.2f} $ (Limit war {pick['limit_price']:.2f})")
```

Fix the imports: `await_fill` is no longer used by this file, `BrokerOrder` now is.

```python
from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    BrokerOrder,
    close_position,
    place_limit_bracket,
    settle_or_cancel,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_ignition_runner.py -v && uv run ruff check scripts/run_ignition_lane.py
```

Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ignition_runner.py scripts/run_ignition_lane.py
git commit -m "fix(ignition): book the settled order, not the intermediate poll state"
```

---

### Task 2: A pure book-vs-broker comparison

**Files:**
- Create: `src/equity_scout/broker_reconcile.py`
- Test: `tests/test_broker_reconcile.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_broker_reconcile.py`:

```python
"""What the watchdog was structurally unable to see until 2026-08-24: the book and the venue
holding different numbers of the same share."""
from __future__ import annotations

from equity_scout.alpaca_broker import BrokerPosition
from equity_scout.broker_reconcile import divergences, divergence_text


def _pos(ticker: str, qty: float) -> BrokerPosition:
    return BrokerPosition(ticker=ticker, qty=qty, avg_entry_price=7.0)


def test_matching_quantities_are_no_divergence() -> None:
    assert divergences({"MRVI": 128.0}, {"MRVI": _pos("MRVI", 128.0)}) == []


def test_the_live_case_the_broker_holds_more_than_the_book() -> None:
    found = divergences({"MRVI": 128.0}, {"MRVI": _pos("MRVI", 424.0)})
    assert found == [{"ticker": "MRVI", "book_qty": 128.0, "broker_qty": 424.0,
                      "kind": "broker_excess"}]


def test_a_position_the_book_has_and_the_broker_does_not() -> None:
    """The book believing in a position that no longer exists is the mirror failure: every
    exit rule fires against a holding that cannot be sold."""
    found = divergences({"PURR": 110.0}, {})
    assert found == [{"ticker": "PURR", "book_qty": 110.0, "broker_qty": 0.0,
                      "kind": "book_only"}]


def test_a_position_only_the_broker_has() -> None:
    found = divergences({}, {"ELMT": _pos("ELMT", 49.0)})
    assert found == [{"ticker": "ELMT", "book_qty": 0.0, "broker_qty": 49.0,
                      "kind": "broker_only"}]


def test_fractional_rounding_is_not_a_divergence() -> None:
    """Alpaca reports fractional quantities; a 1e-9 difference is float noise, not a fill."""
    assert divergences({"SPY": 1.0}, {"SPY": _pos("SPY", 1.0000000001)}) == []


def test_tickers_the_lane_does_not_own_are_ignored() -> None:
    """The paper account is shared with the session lane. Only what this book claims — or
    holds an excess of — is this book's business."""
    assert divergences({}, {"AAPL": _pos("AAPL", 4.0)}, owned={"MRVI"}) == []


def test_the_text_names_both_numbers() -> None:
    text = divergence_text([{"ticker": "MRVI", "book_qty": 128.0, "broker_qty": 424.0,
                             "kind": "broker_excess"}])
    assert "MRVI" in text and "128" in text and "424" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_broker_reconcile.py -v
```

Expected: FAIL, `ModuleNotFoundError: No module named 'equity_scout.broker_reconcile'`

- [ ] **Step 3: Write the module**

Create `src/equity_scout/broker_reconcile.py`:

```python
"""Does the book hold what the venue holds?

The heartbeat SLAs in `watchdog.py` cannot answer this by construction: every chain can run
green while the book and the account drift apart. On 2026-08-19 the ignition lane bought MRVI
three times and booked it once; the difference (296 shares) sat in the paper account for five
days, outside every exit rule, and nothing in the system was looking.

Pure comparison — the caller fetches from the venue and reads the book, this decides. Kept
ignition-only for now (the one lane trading live); generalise when a second lane needs it.
"""
from __future__ import annotations

from equity_scout.alpaca_broker import BrokerPosition

# Alpaca reports fractional quantities as floats; anything below this is representation noise
# rather than an unbooked fill. One thousandth of a share is smaller than any position the
# lanes can open (`ENTRY_FRACTION` of a 10k book buys whole shares of anything above $1).
QTY_TOLERANCE = 1e-3


def divergences(
    book_positions: dict[str, float],
    broker_positions: dict[str, BrokerPosition],
    *,
    owned: set[str] | None = None,
) -> list[dict]:
    """Every ticker where book quantity and broker quantity disagree, sorted by ticker.

    `owned` limits which broker-only tickers count: the paper account is shared with the
    session lane, so a holding this book never claimed is not automatically its problem.
    Defaults to "everything the broker reports", which is what a single-lane account wants.
    """
    tickers = set(book_positions) | {
        t for t in broker_positions if owned is None or t in owned or t in book_positions
    }
    found = []
    for ticker in sorted(tickers):
        book_qty = float(book_positions.get(ticker, 0.0))
        broker = broker_positions.get(ticker)
        broker_qty = float(broker.qty) if broker else 0.0
        if abs(book_qty - broker_qty) <= QTY_TOLERANCE:
            continue
        if book_qty <= QTY_TOLERANCE:
            kind = "broker_only"
        elif broker_qty <= QTY_TOLERANCE:
            kind = "book_only"
        elif broker_qty > book_qty:
            kind = "broker_excess"
        else:
            kind = "book_excess"
        found.append({"ticker": ticker, "book_qty": book_qty, "broker_qty": broker_qty,
                      "kind": kind})
    return found


_KIND_TEXT = {
    "broker_excess": "Konto hält MEHR als das Buch",
    "book_excess": "Buch hält mehr als das Konto",
    "broker_only": "nur im Konto, nicht im Buch",
    "book_only": "nur im Buch, nicht im Konto",
}


def divergence_text(found: list[dict]) -> str:
    """One Telegram-ready message naming both numbers per ticker."""
    lines = ["⚠ Buch und Broker-Konto stimmen nicht überein:"]
    for item in found:
        lines.append(
            f"  {item['ticker']}: Buch {item['book_qty']:g} vs Konto {item['broker_qty']:g}"
            f" — {_KIND_TEXT[item['kind']]}"
        )
    lines.append("Solange das offen ist, misst die Lane ein anderes Depot als das echte.")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_broker_reconcile.py -v && uv run ruff check src/equity_scout/broker_reconcile.py
```

Expected: 7 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/broker_reconcile.py tests/test_broker_reconcile.py
git commit -m "feat(reconcile): compare lane book quantities against broker positions"
```

---

### Task 3: The ignition runner records a divergence

**Files:**
- Modify: `scripts/run_ignition_lane.py` (after `persist_lane_step`)
- Test: `tests/test_ignition_runner.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ignition_runner.py`:

```python
from equity_scout.alpaca_broker import BrokerPosition
from equity_scout.shortterm_storage import get_lane_state, init_shortterm_db


def test_a_divergence_is_recorded_for_the_watchdog(tmp_path) -> None:
    """The runner talks to the broker anyway; the watchdog is DB-only by design. So the
    runner writes the finding and the watchdog alarms on it — no network in the dead-man."""
    db = str(tmp_path / "st.db")
    init_shortterm_db(db)
    runner.record_divergence(
        db, book_positions={"MRVI": 128.0},
        broker_positions={"MRVI": BrokerPosition("MRVI", 424.0, 7.0)},
        now="2026-08-24T17:00:00+00:00",
    )
    state = get_lane_state(db, runner.LANE, runner.DIVERGENCE_KEY)
    assert state is not None and "424" in state


def test_no_divergence_clears_the_state(tmp_path) -> None:
    """A stale warning is worse than none: it trains you to ignore the channel."""
    db = str(tmp_path / "st.db")
    init_shortterm_db(db)
    runner.record_divergence(
        db, book_positions={"MRVI": 128.0},
        broker_positions={"MRVI": BrokerPosition("MRVI", 424.0, 7.0)},
        now="2026-08-24T17:00:00+00:00",
    )
    runner.record_divergence(
        db, book_positions={"MRVI": 424.0},
        broker_positions={"MRVI": BrokerPosition("MRVI", 424.0, 7.0)},
        now="2026-08-24T17:01:00+00:00",
    )
    assert get_lane_state(db, runner.LANE, runner.DIVERGENCE_KEY) in (None, "")
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_ignition_runner.py -v
```

Expected: FAIL, no attribute `record_divergence`.

- [ ] **Step 3: Implement**

In `scripts/run_ignition_lane.py`, add the import `fetch_positions` to the
`equity_scout.alpaca_broker` import list, `set_lane_state` to the `shortterm_storage` list,
and add near `bookable`:

```python
DIVERGENCE_KEY = "broker_divergence"


def record_divergence(
    db_path: str,
    *,
    book_positions: dict[str, float],
    broker_positions: dict[str, BrokerPosition],
    now: str,
) -> list[dict]:
    """Persist (or clear) the book-vs-broker finding for the watchdog to alarm on.

    Written as lane state rather than sent from here: this runner fires every minute, and a
    Telegram message per minute is a muted channel by lunchtime. The watchdog owns the
    cooldown.
    """
    found = divergences(book_positions, broker_positions)
    payload = json.dumps({"at": now, "items": found}) if found else ""
    set_lane_state(db_path, LANE, DIVERGENCE_KEY, payload)
    return found
```

`json` is already imported inside `main()`; move that `import json` to the module's import
block at the top of the file so both call sites see it.

Then, immediately after the `persist_lane_step(...)` call in `main()`:

```python
    try:
        found = record_divergence(
            args.shortterm_db,
            book_positions={t: p.qty for t, p in book.positions.items()},
            broker_positions=fetch_positions(),
            now=now.isoformat(timespec="seconds"),
        )
    except AlpacaBrokerError as exc:
        print(f"Abgleich Buch/Konto nicht möglich: {exc}", file=sys.stderr)
    else:
        if found:
            print(divergence_text(found), file=sys.stderr)
```

Import the two helpers: `from equity_scout.broker_reconcile import divergence_text, divergences`.

- [ ] **Step 4: Run to verify it passes**

```bash
uv run pytest tests/test_ignition_runner.py -v && uv run ruff check scripts/run_ignition_lane.py
```

Expected: 6 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_ignition_lane.py tests/test_ignition_runner.py
git commit -m "feat(ignition): record book-vs-broker divergence as lane state"
```

---

### Task 4: The watchdog alarms on a divergence

**Files:**
- Modify: `src/equity_scout/watchdog.py`
- Modify: `scripts/run_watchdog.py`
- Test: `tests/test_watchdog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_watchdog.py`:

```python
def test_a_recorded_divergence_is_reported(tmp_path) -> None:
    """The failure the heartbeat SLAs are blind to: every chain green, book and account apart."""
    from equity_scout.shortterm_storage import init_shortterm_db, set_lane_state
    from equity_scout.watchdog import position_divergence

    st_db = str(tmp_path / "st.db")
    init_shortterm_db(st_db)
    set_lane_state(st_db, "ignition", "broker_divergence", json.dumps(
        {"at": "2026-08-24T17:00:00+00:00",
         "items": [{"ticker": "MRVI", "book_qty": 128.0, "broker_qty": 424.0,
                    "kind": "broker_excess"}]}))
    found = position_divergence(st_db)
    assert found and found[0]["ticker"] == "MRVI"


def test_no_recorded_divergence_reports_nothing(tmp_path) -> None:
    from equity_scout.shortterm_storage import init_shortterm_db
    from equity_scout.watchdog import position_divergence

    st_db = str(tmp_path / "st.db")
    init_shortterm_db(st_db)
    assert position_divergence(st_db) == []
```

Add `import json` at the top of `tests/test_watchdog.py` if it is not already there.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_watchdog.py -v -k divergence
```

Expected: FAIL, cannot import `position_divergence`.

- [ ] **Step 3: Implement**

In `src/equity_scout/watchdog.py`:

```python
def position_divergence(shortterm_db: str, *, lane: str = "ignition") -> list[dict]:
    """The book-vs-broker finding the lane runner recorded, or [] when the books agree.

    Read from the short-term DB rather than measured here: the watchdog rides in the 24/7
    crypto slot and must never depend on the broker being reachable — a dead-man that dies
    when the network does alarms about nothing.
    """
    from equity_scout.shortterm_storage import get_lane_state

    raw = get_lane_state(shortterm_db, lane, "broker_divergence")
    if not raw:
        return []
    try:
        return list(json.loads(raw).get("items", []))
    except (ValueError, AttributeError):
        return []
```

Add `import json` to the module's imports if absent.

In `scripts/run_watchdog.py`, add the argument and the check. After the `--db` argument:

```python
    parser.add_argument("--shortterm-db", default=DEFAULT_SHORTTERM_DB_PATH)
```

with `from equity_scout.shortterm_storage import DEFAULT_SHORTTERM_DB_PATH` imported, and after
the scheduler-gap block in `main()`:

```python
    divergent = position_divergence(args.shortterm_db)
    if divergent:
        _report(divergence_text(divergent))
```

Import `position_divergence` from `equity_scout.watchdog` and `divergence_text` from
`equity_scout.broker_reconcile`. `_report` has no cooldown by design — but this state is
cleared by the runner as soon as the books agree, and a standing divergence is worth one
message per 15-minute crypto slot until it is fixed.

- [ ] **Step 4: Run to verify it passes**

```bash
uv run pytest tests/test_watchdog.py -v && uv run ruff check src/equity_scout/watchdog.py scripts/run_watchdog.py
```

Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/watchdog.py scripts/run_watchdog.py tests/test_watchdog.py
git commit -m "feat(watchdog): alarm on a recorded book-vs-broker divergence"
```

---

### Task 5: Clean up the 296 orphaned MRVI shares

Ordered AFTER Task 1 on purpose: cleaning up first would let the unfixed lane re-create the
divergence on the next signal.

**Files:** none — a one-off broker action, verified through the new reconciliation.

- [ ] **Step 1: Confirm the divergence is still exactly 296 shares**

```bash
uv run python -c "
from equity_scout.alpaca_broker import fetch_positions
from equity_scout.shortterm_storage import load_book
from equity_scout.broker_reconcile import divergences, divergence_text
book = load_book('shortterm.db', 'ignition')
print(divergence_text(divergences({t: p.qty for t, p in book.positions.items()}, fetch_positions())) or 'keine Divergenz')
"
```

Expected: MRVI, book 128 vs account 424.

- [ ] **Step 2: Sell the excess only**

The book's 128 shares stay — they are the lane's measured position and its 10 % sizing rule.
Only the unbooked excess goes. Market order, because this is error cleanup and not a trade the
measurement should own.

```bash
uv run python -c "
from equity_scout.alpaca_broker import _client, PAPER_BASE, auth_headers
import json
with _client() as c:
    r = c.post(f'{PAPER_BASE}/orders', json={'symbol':'MRVI','qty':'296','side':'sell','type':'market','time_in_force':'day'})
print(r.status_code, r.text[:300])
"
```

Expected: 200 and an order id.

- [ ] **Step 3: Verify book and account now agree**

Re-run the command from Step 1. Expected: `keine Divergenz`.

- [ ] **Step 4: Record what happened in the plan outcome**

No commit — nothing in the repo changed. The outcome section at the bottom of this document
carries the numbers.

---

### Task 6: Put PBO back on a schedule

**Files:**
- Modify: `scripts/scheduled_run.sh`
- Test: `tests/test_run_weekly_guarded.py`

- [ ] **Step 1: Read the weekly chain to find the step idiom**

```bash
grep -n "step " scripts/scheduled_run.sh
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_run_weekly_guarded.py`:

```python
def test_the_weekly_chain_computes_pbo() -> None:
    """PBO 0.7714 in the ledger was computed 2026-06-26 over 13 configs and never again,
    while the ledger grew to 4,600 trials. The Deflated Sharpe hurdle assumes independent
    trials; PBO is the check on that assumption, so it has to run as often as the search."""
    text = Path("scripts/scheduled_run.sh").read_text()
    assert "run_pbo.py" in text
```

Match the file's existing import of `Path` and its naming style.

- [ ] **Step 3: Run to verify it fails**

```bash
uv run pytest tests/test_run_weekly_guarded.py -v -k pbo
```

Expected: FAIL.

- [ ] **Step 4: Add the step**

Append to `scripts/scheduled_run.sh`, using the same `step` helper and quoting as the
surrounding lines (weekly, not nightly — `run_pbo.py`'s own docstring says "run it
occasionally, not in the loop"):

```bash
step pbo "$PY" scripts/run_pbo.py
```

- [ ] **Step 5: Run to verify it passes**

```bash
uv run pytest tests/test_run_weekly_guarded.py -v
```

- [ ] **Step 6: Compute PBO once now, against the current ledger**

```bash
nohup .venv/bin/python scripts/run_pbo.py > pbo.log 2>&1 &
```

Slow (one walk-forward per config). Read the result when it lands:

```bash
tail -5 pbo.log
```

- [ ] **Step 7: Commit**

```bash
git add scripts/scheduled_run.sh tests/test_run_weekly_guarded.py
git commit -m "feat(research): compute PBO in the weekly chain"
```

---

### Task 7: Full gate

- [ ] **Step 1: Run the whole suite and the linter**

```bash
uv run pytest -q && uv run ruff check .
```

Expected: green, clean. Commit nothing on a red gate.

- [ ] **Step 2: Verify the live lane still runs**

```bash
.venv/bin/python scripts/run_ignition_lane.py --dry-run --force
```

Expected: exits 0, prints its decisions, places no orders.

---

## Out of scope — Nico's calls, deliberately not touched

- **Entry-model universe.** Panel AUC has been flat at 0.507 for four weeks against a 0.55
  gate; 244 models trained, 0 promotions. The lever is the universe (axis 2, 2026-08-11), and
  that is a strategy decision.
- **Sleeve promotion.** `sleeve_mode: anchor`, 11 sleeves at 9.09 % each, `promoted_lanes` empty,
  while Cross-Sectional Momentum (12-1) leads the forward test at +5.09 % vs SPY −0.98 %.
  Turning research results into depot weights changes what the money does.
- **Gap-fade lane's future.** 0 orders in 6 trading days; today 0 of 24 tickers judgeable
  because no IEX pre-market print was fresher than 20 minutes. Either the watchlist changes or
  the lane goes — both are decisions, not fixes.
- **Shadow scoring without a champion.** `entry_predictions` stopped on 2026-08-11 because
  `score_watchlist` is a no-op without a champion; the 239 open predictions run out in early
  October and then the measurement strand is empty. Worth building, big enough to need its own
  plan.

---

## Outcome (2026-08-24, executed inline)

All six tasks done. Gate: **2,527 tests passed**, `ruff check .` clean. Five commits on
`autopilot/work`, unpushed.

**Task 1 — fill booking.** `bookable()` + `settle_or_cancel`'s return value. Verified live
within minutes: the minute cron picked up the new code while the rest of this plan was being
executed, and the entry path has run clean since.

**Tasks 2–4 — reconciliation.** `broker_reconcile.py` (10 tests), the runner records the finding
as lane state, the watchdog alarms on it. Verified end-to-end against the real account before
the cleanup: `run_watchdog.py` printed "MRVI: Buch 128 vs Konto 424 — Konto hält MEHR als das
Buch". After the cleanup the runner cleared the marker by itself and the watchdog reports no
divergence. The feedback loop closes without human action, which was the point.

**Task 5 — cleanup.** Sold exactly the 296 unbooked shares, market, filled @ 8.30
(order `b91fdad9`). Cost basis was 7.043, so the paper account realised ≈ +372 USD that belongs
to no lane's measurement — it is the unwind of an error, not a trade. Book and account now both
hold MRVI 128 / PURR 110. The lane's own measurement series (`st_trades`) was never touched.

**Task 6 — PBO. Deviation from the plan, deliberately.** The plan said to append a step to
`scripts/scheduled_run.sh`; that file ends in `exec`, so nothing can follow it. Used the repo's
established pattern instead — `scripts/weekly_pbo.sh` plus a managed crontab line (Sunday 04:00),
same ownership and blast-radius reasoning as `insider_shadow_lane.sh`. Also dropped the planned
`test_run_weekly_guarded.py` assertion: the repo has no test for any of its ten other cron lines,
and `assert "run_pbo" in text` only proves the string was typed. Consistency over a test with no
failure mode.

**The new PBO number: 0.56** (was 0.7714 from 2026-06-26, over 13 configs both times). Better
than two months ago and still above 0.5 — by the script's own reading, the leaderboard of this
search is "eher Glück". That is now a number that refreshes weekly instead of aging silently.

**What this did NOT fix, and it matters:** the ignition lane's entries still end up with no
resting stop at the venue — the bracket legs come back `canceled` / `expired` on all three
historical entries (verified in the order history for MRVI, PURR, ELMT). Protection therefore
exists only while the minute cron runs. That is a separate defect with its own blast radius
(it decides what happens when the machine is off), and it needs its own plan rather than a
patch tacked onto this one.
