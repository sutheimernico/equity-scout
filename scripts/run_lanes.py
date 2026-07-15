"""Arena runner: advance both paper lanes in one run against ONE shared price fetch.

FAIRNESS BY CONSTRUCTION: a single ``now``, a single ``prices`` dict and a single frozen
``LaneParams`` (exit rules + sizing + fees + slippage) drive BOTH lanes through the SAME
loop body — divergent per-lane inputs are impossible to express here. Lane "nico" executes
only Nico's approved buy pitches (linked by pitch_id, the executed marker); lane "autopilot"
buys in-zone watchlist candidates above the score threshold autonomously.

PAPER ONLY. yfinance spot quotes are isolated behind the lazy ``_fetch_spot`` seam so no
network is touched at import time or in tests (inject fetch_price / monkeypatch _fetch_spot).

Usage:
    python scripts/run_lanes.py [--db equity_scout.db] [--threshold 0.45]
        [--position-fraction 0.05] [--profit-target 0.20] [--stop-loss 0.15]
        [--max-holding-days 180]
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.yf_provider import fetch_dividend_yield
from equity_scout.inbox_storage import load_pitches
from equity_scout.lane_storage import (
    executed_pitch_ids,
    load_lane_portfolio,
    load_lane_valuations,
    record_trades,
    save_lane_portfolio,
    save_lane_valuation,
)
from equity_scout.lanes import (
    DEFAULT_FEE_RATE,
    DEFAULT_POSITION_FRACTION,
    DEFAULT_SLIPPAGE_BPS,
    LANE_AUTOPILOT,
    LANE_NICO,
    BuyOrder,
    ExitRules,
    apply_exits,
    execute_buys,
    lane_b_orders,
)
from equity_scout.portfolio import credit_dividends, mark_to_market, new_portfolio
from equity_scout.radar_storage import load_latest_watchlist

DEFAULT_THRESHOLD = 0.45
INITIAL_CAPITAL = 10_000.0


@dataclass(frozen=True)
class LaneParams:
    """The one parameter set both lanes share — exit rules, sizing, fees, slippage.

    Frozen and passed once into run_lanes so the two lanes cannot diverge by construction:
    the phase's fairness invariant lives here.
    """

    rules: ExitRules
    position_fraction: float = DEFAULT_POSITION_FRACTION
    fee_rate: float = DEFAULT_FEE_RATE
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS


def _fetch_spot(ticker: str) -> float | None:
    """Last close for ``ticker`` via yfinance (lazy import + retry), None on failure.

    Mirrors entry.fetch_entry_history's isolation of yfinance so nothing here imports the
    network at module load.
    """
    import yfinance as yf

    from equity_scout.data.fetch import with_retry

    def _spot() -> float | None:
        history = yf.Ticker(ticker).history(period="1d")
        if history.empty or "Close" not in history.columns:
            return None
        closes = history["Close"].dropna().tolist()
        return float(closes[-1]) if closes else None

    try:
        return with_retry(_spot, attempts=3)
    except Exception:
        return None


def _lane_a_orders(db_path: str) -> list[BuyOrder]:
    """Approved buy pitches lane "nico" has not executed yet (pitch_id = executed marker)."""
    executed = executed_pitch_ids(db_path, LANE_NICO)
    orders: list[BuyOrder] = []
    for pitch in load_pitches(db_path, limit=1000):
        if pitch["status"] != "buy" or pitch["id"] in executed:
            continue
        orders.append(
            BuyOrder(
                ticker=pitch["ticker"],
                name=pitch.get("name", pitch["ticker"]),  # pitch rows carry no name column
                score=pitch["composite"],
                reason=f"Freigegeben am {pitch['decided_at'][:10]}: Pitch #{pitch['id']}",
                pitch_id=pitch["id"],
            )
        )
    return orders


def _days_since_last_run(db_path: str, now: str) -> float:
    """Calendar days since either lane was last valued (day-keyed history), for the dividend span.

    Both lanes are always valued together, so their latest ``valued_on`` matches; taking the max is
    just belt-and-braces. 0.0 on the first run (no prior valuation) so the first advance credits no
    dividend, and 0.0 on a same-day re-run so re-running the CLI within one day double-counts nothing.
    """
    last: str | None = None
    for lane in (LANE_NICO, LANE_AUTOPILOT):
        vals = load_lane_valuations(db_path, lane)
        if vals and (last is None or vals[-1]["valued_on"] > last):
            last = vals[-1]["valued_on"]
    if last is None:
        return 0.0
    return float(max((date.fromisoformat(now[:10]) - date.fromisoformat(last)).days, 0))


def _fmt_value(value: float) -> str:
    """German number format: 10.234,00 (thousands dot, decimal comma)."""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(fraction: float) -> str:
    """German signed percent: +2,3."""
    return f"{fraction * 100:+.1f}".replace(".", ",")


def run_lanes(
    db_path: str,
    *,
    now: str,
    fetch_price: Callable[[str], float | None],
    params: LaneParams,
    threshold: float,
    fetch_dividend_yield: Callable[[str], float | None] | None = None,
) -> dict:
    """Advance both lanes in one run — shared ``now``, shared ``prices``, shared ``params``.

    Sequence per lane, identical: credit_dividends -> apply_exits -> execute_buys -> mark_to_market
    -> persist (portfolio + day-keyed valuation + trade ledger). Returns a per-lane summary dict.

    ``fetch_dividend_yield`` (optional, injected like ``fetch_price``) supplies TTM yields; the accrual
    spans ``_days_since_last_run``. Both are shared by construction, so the fairness invariant holds:
    the two lanes see the same yields and the same span. Omitted → no dividend credited (honest zero).
    """
    nico = load_lane_portfolio(db_path, LANE_NICO) or new_portfolio(
        initial_capital=INITIAL_CAPITAL
    )
    autopilot = load_lane_portfolio(db_path, LANE_AUTOPILOT) or new_portfolio(
        initial_capital=INITIAL_CAPITAL
    )

    lane_a = _lane_a_orders(db_path)
    watchlist = load_latest_watchlist(db_path) or {}
    lane_b = lane_b_orders(
        watchlist, held_tickers=set(autopilot.positions), threshold=threshold
    )

    # Fetch prices ONCE for the union of everything either lane could touch this run.
    union = (
        set(nico.positions)
        | set(autopilot.positions)
        | {order.ticker for order in lane_a}
        | {order.ticker for order in lane_b}
        | {"SPY"}
    )
    # Drop unpriced tickers: a None value would break mark_to_market's cost-basis fallback
    # (prices.get(t, cost) returns None when the key exists with a None value).
    prices = {ticker: price for ticker in union if (price := fetch_price(ticker)) is not None}
    spy = prices.get("SPY")

    # TTM dividend yields for the held/candidate names (SPY is the benchmark, not a position, so it
    # is skipped). One dict + one span for BOTH lanes → the dividend credit stays fairness-neutral.
    dividend_yields: dict[str, float] = {}
    if fetch_dividend_yield is not None:
        dividend_yields = {
            ticker: y for ticker in union - {"SPY"}
            if (y := fetch_dividend_yield(ticker)) is not None
        }
    days_elapsed = _days_since_last_run(db_path, now)

    summary: dict = {}
    # ONE loop body over both lanes with ONE now, ONE prices, ONE params: the lanes cannot
    # see different inputs. opened_at/now are UTC-aware ISO strings — lanes._held_days subtracts
    # fromisoformat(now) - fromisoformat(opened_at), and a naive/aware mix raises TypeError, so
    # every timestamp threaded through here must stay tz-aware (documented invariant).
    for lane, portfolio, orders in (
        (LANE_NICO, nico, lane_a),
        (LANE_AUTOPILOT, autopilot, lane_b),
    ):
        portfolio = credit_dividends(portfolio, prices, dividend_yields, days_elapsed)
        portfolio, sells = apply_exits(
            portfolio, prices, now=now, lane=lane, rules=params.rules,
            fee_rate=params.fee_rate, slippage_bps=params.slippage_bps,
        )
        portfolio, buys = execute_buys(
            portfolio, orders, prices, now=now, lane=lane,
            position_fraction=params.position_fraction,
            fee_rate=params.fee_rate, slippage_bps=params.slippage_bps,
        )
        # Buy-and-hold SPY from day one (same convention as portfolio.advance): initialise the
        # benchmark once from the shared SPY price so "vs SPY" tracks a real position, not a flat line.
        if portfolio.benchmark_shares == 0.0 and spy:
            portfolio = replace(portfolio, benchmark_shares=portfolio.initial_capital / spy)

        valuation = mark_to_market(portfolio, prices, benchmark_price=spy)
        save_lane_portfolio(db_path, lane, portfolio, updated_at=now)
        save_lane_valuation(
            db_path, lane, valued_on=now[:10],
            total_value=valuation.total_value, total_return=valuation.total_return,
            benchmark_value=valuation.benchmark_value,
            benchmark_return=valuation.benchmark_return,
            open_positions=valuation.open_positions,
        )
        record_trades(db_path, sells + buys)
        print(
            f"Lane {lane}: {len(buys)} Käufe, {len(sells)} Verkäufe, "
            f"Wert {_fmt_value(valuation.total_value)} ({_fmt_pct(valuation.total_return)} %) "
            f"vs SPY {_fmt_pct(valuation.benchmark_return)} %"
        )
        summary[lane] = {
            "buys": len(buys),
            "sells": len(sells),
            "total_value": valuation.total_value,
            "total_return": valuation.total_return,
            "benchmark_return": valuation.benchmark_return,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--position-fraction", type=float, default=DEFAULT_POSITION_FRACTION)
    parser.add_argument("--profit-target", type=float, default=ExitRules.profit_target)
    parser.add_argument("--stop-loss", type=float, default=ExitRules.stop_loss)
    parser.add_argument("--max-holding-days", type=int, default=ExitRules.max_holding_days)
    args = parser.parse_args()

    params = LaneParams(
        rules=ExitRules(
            profit_target=args.profit_target,
            stop_loss=args.stop_loss,
            max_holding_days=args.max_holding_days,
        ),
        position_fraction=args.position_fraction,
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_lanes(args.db, now=now, fetch_price=_fetch_spot, params=params,
              threshold=args.threshold, fetch_dividend_yield=fetch_dividend_yield)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
