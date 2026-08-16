"""Does the session lane's ORB entry earn anything once it may hold OVERNIGHT?

Nico's idea (2026-08-16): the short-term trader should be able to hold for 30 minutes, an
hour, or across days. The refuted intraday rule (breakouts revert, -8.94 bp after 30 min,
t = -2.68 on 1,684 breakouts) plus the overnight finding (93 % of returns accrue overnight)
raise exactly one testable question: does ORB + overnight holding beat plain overnight
holding — i.e. does the ENTRY RULE add anything to the drift everyone gets for free?

Three arms per signal (one signal per ticker per day, no overlap):
  (a) force-flat at the close  — the live lane, as control
  (b) hold to the next open    — inherits the overnight drift
  (c) swing exits 5 %/3 %/7 d  — on the daily close series (exits.exit_reason)

Fairness benchmark: the SAME holding windows entered at 10:15 on every ticker/day WITHOUT
the ORB condition. If an arm only collects the drift the benchmark gets too, the entry rule
remains worthless. Reported per arm: mean, hit rate, naive t, and a same-day-clustered t
(daily means first — 90 tickers on one day share the market factor; LOOP.md's independence
rule applies to cross-sectional clustering too, not just overlapping windows).

Persisted deliberately (lesson from T8, 2026-08-16: ad-hoc scripts are unreproducible).
Data: yfinance 15-minute bars (free window ~60 days) + daily bars. Costs are reported as a
sensitivity line (10 bp per side = costs.py's flat floor), not baked into the raw means.

Usage:  uv run python scripts/research_orb_overnight.py [--period 60d]
"""
from __future__ import annotations

import argparse
from math import sqrt

import pandas as pd

from equity_scout.exits import ExitRules, exit_reason
from equity_scout.st_session import OPENING_RANGE_BARS

# Fixed, explicit universe (liquid US large caps + the lane's own SESSION_UNIVERSE) so the
# run is reproducible — the earlier studies' "91 tickers" list was never persisted.
UNIVERSE = (
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD",
    "AVGO", "NFLX", "COST", "PEP", "KO", "MCD", "WMT", "HD", "NKE", "SBUX",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP", "BLK",
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "BMY", "AMGN",
    "XOM", "CVX", "COP", "SLB", "OXY", "CAT", "DE", "BA", "GE", "HON",
    "UPS", "FDX", "LMT", "RTX", "UNP", "CSX", "ORCL", "CRM", "ADBE", "INTC",
    "CSCO", "QCOM", "TXN", "IBM", "NOW", "AMAT", "MU", "LRCX", "KLAC", "ADI",
    "PYPL", "XYZ", "SHOP", "UBER", "ABNB", "PLTR", "SNOW", "CRWD", "PANW", "ZS",
    "DIS", "CMCSA", "T", "VZ", "TMUS", "PG", "CL", "MDLZ", "GIS", "MO",
)

SWING_RULES = ExitRules(profit_target=0.05, stop_loss=0.03, max_holding_days=7)
# Pseudo-entry bar for the no-condition benchmark: bar index 3 opens at 10:15 ET — at or
# before the median ORB signal time, so the benchmark never gets a LATER (drift-favoured)
# anchor than the signals it judges.
BENCHMARK_ENTRY_BAR = 3
COST_PER_SIDE_BPS = 10.0


def _stats(returns: list[float]) -> dict:
    n = len(returns)
    if n == 0:
        return {"n": 0, "mean_bps": 0.0, "t": None, "hit": 0.0}
    mean = sum(returns) / n
    if n < 2:
        return {"n": n, "mean_bps": mean * 1e4, "t": None, "hit": float(returns[0] > 0)}
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    t = mean / sqrt(var / n) if var > 0 else None
    hit = sum(1 for r in returns if r > 0) / n
    return {"n": n, "mean_bps": mean * 1e4, "t": t, "hit": hit}


def _welch_t(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    denom = sqrt(va / len(a) + vb / len(b))
    return (ma - mb) / denom if denom > 0 else None


def _daily_cluster_t(diffs_by_day: dict[str, list[float]]) -> tuple[float | None, int]:
    """t over per-day mean differences — the honest unit when 90 tickers share one day."""
    daily = [sum(v) / len(v) for v in diffs_by_day.values() if v]
    return (_stats(daily)["t"], len(daily))


def _swing_exit_return(entry_price: float, closes: pd.Series, start_pos: int) -> float:
    """Walk daily closes from the day AFTER entry until an exit rule fires (gross)."""
    for offset in range(1, len(closes) - start_pos):
        price = float(closes.iloc[start_pos + offset])
        ret = price / entry_price - 1
        if exit_reason(ret, offset, SWING_RULES):
            return ret
    return float(closes.iloc[-1]) / entry_price - 1


def collect(period: str) -> dict:
    import yfinance as yf

    intraday = yf.download(
        list(UNIVERSE), interval="15m", period=period, auto_adjust=True,
        progress=False, threads=True, group_by="ticker",
    )
    daily = yf.download(
        list(UNIVERSE), interval="1d", period="6mo", auto_adjust=True,
        progress=False, threads=True, group_by="ticker",
    )

    arms: dict[str, list[float]] = {"flat": [], "overnight": [], "swing": []}
    bench: dict[str, list[float]] = {"flat": [], "overnight": [], "swing": []}
    cluster: dict[str, dict[str, list[float]]] = {k: {} for k in arms}

    for ticker in UNIVERSE:
        try:
            bars = intraday[ticker].dropna(how="all")
            days = daily[ticker].dropna(how="all")
        except KeyError:
            continue
        if bars.empty or days.empty or bars.index.tz is None:
            continue
        bars = bars.tz_convert("America/New_York")
        opens = days["Open"]
        closes = days["Close"]
        for day, day_bars in bars.groupby(bars.index.date):
            day_bars = day_bars.between_time("09:30", "15:59")
            if len(day_bars) <= BENCHMARK_ENTRY_BAR:
                continue
            day_key = str(day)
            day_pos = closes.index.searchsorted(pd.Timestamp(day))
            if day_pos >= len(closes) or closes.index[day_pos].date() != day:
                continue
            next_pos = day_pos + 1
            next_open = float(opens.iloc[next_pos]) if next_pos < len(opens) else None
            last_close = float(day_bars["Close"].iloc[-1])

            or_high = float(day_bars["High"].iloc[:OPENING_RANGE_BARS].max())
            signal_pos = None
            for i in range(OPENING_RANGE_BARS, len(day_bars) - 1):
                if float(day_bars["Close"].iloc[i]) > or_high:
                    signal_pos = i
                    break

            def _routes(entry_price: float, sink: dict[str, list[float]]) -> None:
                sink["flat"].append(last_close / entry_price - 1)
                if next_open is not None:
                    sink["overnight"].append(next_open / entry_price - 1)
                sink["swing"].append(_swing_exit_return(entry_price, closes, day_pos))

            bench_entry = float(day_bars["Open"].iloc[BENCHMARK_ENTRY_BAR])
            _routes(bench_entry, bench)
            if signal_pos is not None:
                entry_price = float(day_bars["Open"].iloc[signal_pos + 1])
                _routes(entry_price, arms)
                for arm in arms:
                    cluster.setdefault(arm, {}).setdefault(day_key, [])
                # per-day signal-minus-benchmark differences for the clustered t
                cluster["flat"][day_key].append(
                    (last_close / entry_price - 1) - (last_close / bench_entry - 1)
                )
                if next_open is not None:
                    cluster["overnight"][day_key].append(
                        (next_open / entry_price - 1) - (next_open / bench_entry - 1)
                    )
                cluster["swing"][day_key].append(
                    _swing_exit_return(entry_price, closes, day_pos)
                    - _swing_exit_return(bench_entry, closes, day_pos)
                )
    return {"arms": arms, "bench": bench, "cluster": cluster}


def report(result: dict) -> str:
    lines = ["ORB entry with overnight holding vs. plain drift", "=" * 60]
    for arm, label in (
        ("flat", "(a) Zwangsflat zum Close (Kontrolle = heutige Lane)"),
        ("overnight", "(b) Halten bis zum naechsten Open"),
        ("swing", "(c) Swing-Exits 5%/3%/7d auf Tagesschluessen"),
    ):
        s = _stats(result["arms"][arm])
        b = _stats(result["bench"][arm])
        welch = _welch_t(result["arms"][arm], result["bench"][arm])
        ct, cdays = _daily_cluster_t(result["cluster"][arm])
        lines += [
            f"\n{label}",
            f"  Signale     : n={s['n']}, mean={s['mean_bps']:+.2f} bp, "
            f"t={s['t']:.2f}" if s["t"] is not None else f"  Signale     : n={s['n']}",
            f"  Hit-Rate    : {s['hit']:.1%}",
            f"  Benchmark   : n={b['n']}, mean={b['mean_bps']:+.2f} bp (Entry 10:15, ohne Bedingung)",
            f"  Differenz   : {s['mean_bps'] - b['mean_bps']:+.2f} bp, Welch-t={welch:.2f}"
            if welch is not None else "  Differenz   : zu wenig Daten",
            f"  Cluster-t   : {ct:.2f} ueber {cdays} Tage (Signal minus Benchmark, je Tag gemittelt)"
            if ct is not None else f"  Cluster-t   : n/a ({cdays} Tage)",
            f"  Netto-Check : Roundtrip {2 * COST_PER_SIDE_BPS:.0f} bp -> "
            f"mean netto {s['mean_bps'] - 2 * COST_PER_SIDE_BPS:+.2f} bp",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="60d", help="yfinance intraday period")
    args = parser.parse_args()
    print(report(collect(args.period)))


if __name__ == "__main__":
    main()
