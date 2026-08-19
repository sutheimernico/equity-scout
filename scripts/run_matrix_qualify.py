"""CLI: qualify matrix plateaus for trading (v17, trader #3) — the chain that was missing.

`find_plateaus` has produced connected winning regions since 2026-08-17 and nothing ever read
them. This script is the link: it walks the cell checkpoint, pools per asset class, finds
plateaus, re-measures each candidate with the calendar-block bootstrap, and writes the survivors
into the register that `strategies/matrix_strategy.py` trades from.

Four gates, in order, each recorded with its verdict:

1. **plateau** — a connected region of its own parameter neighbourhood, not a lucky cell.
2. **bootstrap** — the dependence-aware statistic. The old pooled t was inflated by factor 1.9 on
   real data (measured 2026-08-19), so this is where most candidates are expected to die.
3. **robustness** — entry at `open[i+1]` instead of the signal close. A same-bar entry can harvest
   the bid-ask bounce that the signal itself selected for; a rule that only works at the signal
   close is a microstructure artefact, not a mechanism.
4. **hold-out** — 2023-2025, opened ONCE, hypothesis registered before the result is seen.

Why the bootstrap needs to reload bars: the checkpoint stores cell AGGREGATES (n, net_bp, t), and
resampling needs the individual trades with their timestamps. Only the handful of plateau
candidates get this treatment — doing it for the whole grid would be prohibitive.

Usage:
    uv run python scripts/run_matrix_qualify.py --checkpoint data/matrix_cells.jsonl
    uv run python scripts/run_matrix_qualify.py --open-holdout --hypothesis "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from equity_scout.data.minute_bars import load_minutes  # noqa: E402
from equity_scout.matrix.bootstrap import block_bootstrap, pool_trades  # noqa: E402
from equity_scout.matrix.grid import (  # noqa: E402
    HOLD_OUT_START,
    pool_cells,
    trade_returns_with_times,
)
from equity_scout.matrix.plateau import find_plateaus  # noqa: E402
from equity_scout.matrix.registry import (  # noqa: E402
    DEFAULT_MATRIX_DB_PATH,
    STAGE_BOOTSTRAPPED,
    STAGE_FOUND,
    STAGE_QUALIFIED,
    STAGE_REJECTED,
    STAGE_ROBUST,
    bootstrap_verdict,
    fingerprint,
    holdout_is_open,
    record_holdout_result,
    record_plateau,
    register_holdout_opening,
)
from equity_scout.matrix.signals import SIGNALS  # noqa: E402

DEFAULT_CHECKPOINT = Path("data/matrix_cells.jsonl")
SLICE_ORDER = ("1min", "5min", "15min", "60min", "1D", "1W", "1M")
# Bootstrap block length per slice: never shorter than the holding period, or the blocks stop
# being independent of each other and the standard error is understated again.
BLOCK_FOR_SLICE = {"1min": "W", "5min": "W", "15min": "W", "60min": "M",
                   "1D": "M", "1W": "M", "1M": "M"}


def stream_cells(path: Path, *, window: str) -> dict[tuple, list[dict]]:
    """Group the checkpoint's cells by (asset_class, signal, threshold, slice, hold, cost, context).

    Streamed line by line: the checkpoints are gigabytes (4.2 / 30.6 / 26.2 GB as of
    2026-08-19), and reading one into memory is not an option.
    """
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            cell = json.loads(line)
            if cell.get("window") != window:
                continue
            key = (
                cell["asset_class"], cell["signal"], cell["threshold"], cell["slice"],
                cell["hold_bars"], cell["cost_bps"], cell.get("context", "none"),
            )
            grouped[key].append(cell)
    return grouped


def pooled_from_groups(grouped: dict[tuple, list[dict]]) -> list[dict]:
    out = []
    for key, cells in grouped.items():
        asset_class, signal, threshold, slice_name, hold_bars, cost_bps, context = key
        out.append(pool_cells(
            cells, asset_class=asset_class, signal=signal, threshold=threshold,
            slice=slice_name, hold_bars=hold_bars, cost_bps=cost_bps, context=context,
        ))
    return out


def _resample(frame, slice_name: str):
    """Minute bars -> the cell's own slice. Mirrors what the matrix run itself does."""
    rule = {"1min": "1min", "5min": "5min", "15min": "15min", "60min": "60min",
            "1D": "1D", "1W": "1W", "1M": "1ME"}[slice_name]
    if slice_name == "1min":
        return frame
    return frame.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


def bootstrap_plateau(
    plateau: dict, tickers: list[str], years: list[int], *, window: str, entry_next_open: bool = False
) -> dict | None:
    """Re-measure one plateau's trades with the calendar-block bootstrap.

    A plateau spans several thresholds/slices/holds. Its trades are the UNION over its member
    parameter combinations — that is the region's own claim ("it works across this
    neighbourhood"), so that is what has to be tested.
    """
    spec = SIGNALS.get(plateau["signal"])
    if spec is None:
        return None
    per_ticker = []
    frames = load_minutes(tickers, years=years)
    cut = HOLD_OUT_START
    for _ticker, frame in frames.items():
        if frame is None or len(frame) == 0:
            continue
        for slice_name in plateau["slices"]:
            try:
                bars = _resample(frame, slice_name)
            except (KeyError, ValueError):
                continue
            if window == "search":
                bars = bars.loc[bars.index < cut]
            else:
                bars = bars.loc[bars.index >= cut]
            if len(bars) < 50:
                continue
            for threshold in plateau["thresholds"]:
                try:
                    signal = spec.detect(bars, threshold=threshold)
                except (KeyError, ValueError, TypeError):
                    continue
                for hold in plateau["hold_bars"]:
                    gross, stamps = trade_returns_with_times(bars, signal, hold_bars=hold)
                    if len(gross) == 0:
                        continue
                    if entry_next_open and "open" in bars.columns:
                        # Robustness variant: enter at the NEXT bar's open. The signal close can
                        # sit on the wrong side of the spread precisely because the signal
                        # selected for it.
                        opens = bars["open"].to_numpy(dtype=float)
                        closes = bars["close"].to_numpy(dtype=float)
                        positions = bars.index.get_indexer(stamps)
                        keep = (positions >= 0) & (positions + 1 + hold < len(closes))
                        positions = positions[keep]
                        if len(positions) == 0:
                            continue
                        gross = (closes[positions + 1 + hold] / opens[positions + 1] - 1.0) * 10_000.0
                        stamps = bars.index[positions]
                    per_ticker.append((gross - plateau["cost_bps"], stamps))
    if not per_ticker:
        return None
    net, times = pool_trades(per_ticker)
    if len(net) == 0:
        return None
    block = BLOCK_FOR_SLICE.get(plateau["slices"][0], "M")
    return block_bootstrap(net, times, block=block).as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--matrix-db", default=DEFAULT_MATRIX_DB_PATH)
    parser.add_argument("--tickers", nargs="*", default=None,
                        help="restrict the bootstrap re-measurement (default: the plateau's own)")
    parser.add_argument("--years", nargs="*", type=int,
                        default=list(range(2016, 2023)))
    parser.add_argument("--max-candidates", type=int, default=20,
                        help="bootstrap at most this many plateaus per run")
    parser.add_argument("--open-holdout", action="store_true",
                        help="spend the hold-out on the candidates that passed gates 1-3")
    parser.add_argument("--hypothesis", default="",
                        help="required with --open-holdout: what is being claimed, in advance")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.checkpoint.exists():
        print(f"Checkpoint fehlt: {args.checkpoint}", file=sys.stderr)
        return 1
    if args.open_holdout and not args.hypothesis.strip():
        print("--open-holdout verlangt --hypothesis: eine Hypothese, die NACH dem Ergebnis "
              "formuliert wird, ist keine Hypothese.", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"Lese Zellen aus {args.checkpoint} ({args.checkpoint.stat().st_size / 1e9:.1f} GB) …")
    grouped = stream_cells(args.checkpoint, window="search")
    pooled = pooled_from_groups(grouped)
    print(f"  {len(pooled)} gepoolte Zellen")

    plateaus = find_plateaus(pooled, slice_order=SLICE_ORDER)
    print(f"  {len(plateaus)} Plateaus im Suchfenster (Gate 1)")
    if not plateaus:
        print("Keine Plateaus — nichts zu qualifizieren. Das ist ein Ergebnis, kein Fehler.")
        return 0

    tickers = args.tickers or sorted({c["ticker"] for cells in grouped.values() for c in cells})
    candidates = plateaus[:args.max_candidates]
    survivors: list[tuple[dict, dict]] = []

    for plateau in candidates:
        key = fingerprint(plateau)
        if not args.dry_run:
            record_plateau(args.matrix_db, plateau, now=now, stage=STAGE_FOUND)

        boot = bootstrap_plateau(plateau, tickers, args.years, window="search")
        if boot is None:
            print(f"  {plateau['signal']}: Trades nicht reproduzierbar — übersprungen")
            continue
        passes, reason = bootstrap_verdict(boot)
        inflation = boot.get("inflation_factor")
        print(f"  {plateau['signal']:18s} {plateau['slices']} t={boot.get('t')} "
              f"(naiv {boot.get('naive_t')}, Faktor "
              f"{f'{inflation:.1f}' if inflation else '?'}) -> "
              f"{'BESTANDEN' if passes else reason}")
        if not passes:
            if not args.dry_run:
                record_plateau(args.matrix_db, plateau, now=now, stage=STAGE_REJECTED,
                               bootstrap=boot, rejected_reason=f"Bootstrap: {reason}")
            continue
        if not args.dry_run:
            record_plateau(args.matrix_db, plateau, now=now, stage=STAGE_BOOTSTRAPPED,
                           bootstrap=boot)

        robust = bootstrap_plateau(plateau, tickers, args.years, window="search",
                                   entry_next_open=True)
        robust_ok, robust_reason = (bootstrap_verdict(robust) if robust
                                    else (False, "Robustheitsvariante nicht messbar"))
        print(f"    Robustheit (Entry am nächsten Open): "
              f"{'BESTANDEN' if robust_ok else robust_reason}")
        if not robust_ok:
            if not args.dry_run:
                record_plateau(args.matrix_db, plateau, now=now, stage=STAGE_REJECTED,
                               bootstrap=boot, robustness=robust or {},
                               rejected_reason=f"Robustheit: {robust_reason}")
            continue
        if not args.dry_run:
            record_plateau(args.matrix_db, plateau, now=now, stage=STAGE_ROBUST,
                           bootstrap=boot, robustness=robust)
        survivors.append((plateau, boot))
        print(f"    -> Kandidat für das Hold-out ({key[:60]}…)")

    print(f"\n{len(survivors)} von {len(candidates)} Kandidaten haben Gate 1-3 bestanden.")

    if not args.open_holdout:
        if survivors:
            print("Das Hold-out wurde NICHT geöffnet. Für den letzten Schritt: "
                  "--open-holdout --hypothesis \"…\" (einmalig, unwiderruflich).")
        return 0
    if not survivors:
        print("Nichts zu prüfen — das Hold-out bleibt unangetastet.")
        return 0
    if not holdout_is_open(args.matrix_db, HOLD_OUT_START):
        print(f"Hold-out ab {HOLD_OUT_START} ist bereits verbraucht.", file=sys.stderr)
        return 3

    print(f"\n=== HOLD-OUT ({HOLD_OUT_START}+) wird EINMAL geöffnet ===")
    if not args.dry_run:
        register_holdout_opening(
            args.matrix_db, window_start=HOLD_OUT_START, now=now,
            hypothesis=args.hypothesis,
            fingerprints=[fingerprint(p) for p, _ in survivors],
        )

    results = []
    for plateau, boot in survivors:
        out = bootstrap_plateau(plateau, tickers, list(range(2023, 2026)), window="holdout")
        passes, reason = (bootstrap_verdict(out) if out else (False, "nicht messbar"))
        print(f"  {plateau['signal']:18s} -> {'HÄLT' if passes else reason}")
        results.append({"fingerprint": fingerprint(plateau), "passes": passes,
                        "reason": reason, "result": out})
        if not args.dry_run:
            record_plateau(
                args.matrix_db, plateau, now=now,
                stage=STAGE_QUALIFIED if passes else STAGE_REJECTED,
                bootstrap=boot, holdout=out or {},
                rejected_reason=None if passes else f"Hold-out: {reason}",
            )
    if not args.dry_run:
        record_holdout_result(args.matrix_db, window_start=HOLD_OUT_START,
                              result={"hypothesis": args.hypothesis, "results": results})

    held = sum(1 for r in results if r["passes"])
    print(f"\n{held} von {len(results)} Plateaus haben das Hold-out überlebt und sind "
          f"jetzt handelbar.")
    if held == 0:
        print("Null ist ein Ergebnis: dieser Signalraum trägt an unseren Daten keinen Handel. "
              "Die Suche geht in einen anderen Raum, nicht in eine schwächere Statistik.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
