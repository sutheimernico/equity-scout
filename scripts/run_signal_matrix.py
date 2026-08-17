#!/usr/bin/env python3
"""Run the signal matrix over minute-to-month slices, then look for PLATEAUS.

Nico's brief (2026-08-17): not one parameter and not one time slice, but the whole space — and
the unit of interest is "a selection of winning cells", i.e. a connected region, not a champion.
Plus: does behaviour differ between stocks, indices, commodities, bonds, currencies? Asset class
is therefore an axis, not a footnote.

Three phases, deliberately separated so a night run survives interruption:

1. **Cells** — per ticker, every (signal x threshold x slice x hold x cost) cell for the search
   window AND the hold-out, appended to a JSONL checkpoint. A ticker already in the checkpoint is
   skipped, so re-running continues instead of restarting. Memory stays flat: one ticker's bars
   at a time, never all 70 million rows at once.
2. **Pool** — cells grouped by asset class, trade-weighted (see grid.pool_cells).
3. **Plateaus** — flood fill over the pooled search-window cells, then the surviving plateaus are
   re-measured on the hold-out. The hold-out is opened ONCE and the fact is printed.

Usage:
    uv run python scripts/run_signal_matrix.py                     # everything on disk
    uv run python scripts/run_signal_matrix.py --tickers SPY GLD   # subset
    uv run python scripts/run_signal_matrix.py --phase cells       # only fill the checkpoint
    uv run python scripts/run_signal_matrix.py --phase report      # only pool + plateaus
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from equity_scout.data.minute_bars import load_minutes  # noqa: E402
from equity_scout.matrix.grid import (  # noqa: E402
    COST_BPS,
    HOLD_BARS,
    HOLD_OUT_START,
    MIN_TRADES,
    cell_from_returns,
    pool_cells,
    split_periods,
    trade_returns,
)
from equity_scout.matrix.plateau import find_plateaus  # noqa: E402
from equity_scout.matrix.signals import SIGNALS  # noqa: E402
from equity_scout.matrix.timeframes import INTRADAY_SLICES, TIME_SLICES, resample_bars  # noqa: E402

from scripts.fetch_minute_history import (  # noqa: E402
    FULL_YEARS,
    MINUTE_UNIVERSE,
    asset_class,
)

CHECKPOINT = Path("data/matrix_cells.jsonl")


def cells_for_ticker(bars, ticker: str, window: str) -> list[dict]:
    """Every cell of the axis product for one ticker and one period window.

    Cost is the innermost axis on purpose: the trades are identical across cost levels, so they
    are computed once per (signal, threshold, slice, hold) and each cost level only subtracts a
    constant. That is a factor len(COST_BPS) of work saved, which is the difference between a
    night run and a week.
    """
    rows: list[dict] = []
    klass = asset_class(ticker)
    for slice_label in TIME_SLICES:
        resampled = resample_bars(
            bars, slice_label, keep_incomplete=slice_label in INTRADAY_SLICES
        )
        if len(resampled) < MIN_TRADES:
            continue  # this slice cannot reach the sample floor for this ticker
        for signal_name, spec in SIGNALS.items():
            for threshold in spec.thresholds:
                flags = spec.detect(resampled, threshold=threshold)
                for hold in HOLD_BARS:
                    gross = trade_returns(resampled, flags, hold_bars=hold)
                    for cost in COST_BPS:
                        cell = cell_from_returns(gross, cost_bps=cost)
                        rows.append({
                            "ticker": ticker, "asset_class": klass, "window": window,
                            "signal": signal_name, "threshold": threshold,
                            "slice": slice_label, "hold_bars": hold, "cost_bps": cost,
                            **cell,
                        })
    return rows


def done_tickers(path: Path) -> set[str]:
    """Tickers already in the checkpoint — the resume set."""
    if not path.exists():
        return set()
    seen = set()
    with path.open() as handle:
        for line in handle:
            try:
                seen.add(json.loads(line)["ticker"])
            except (json.JSONDecodeError, KeyError):
                continue  # a torn last line from a kill is skipped, not fatal
    return seen


def phase_cells(tickers: list[str], years: list[int], path: Path) -> None:
    pending = [t for t in tickers if t not in done_tickers(path)]
    print(f"Phase 1 — Zellen: {len(pending)} Ticker offen "
          f"({len(tickers) - len(pending)} schon im Checkpoint)", flush=True)
    started = time.time()
    for i, ticker in enumerate(pending, start=1):
        loaded = load_minutes([ticker], years=years)
        if ticker not in loaded:
            print(f"  {ticker}: keine Bars auf Platte — übersprungen", flush=True)
            continue
        search, held = split_periods(loaded[ticker])
        rows = []
        if len(search):
            rows += cells_for_ticker(search, ticker, "search")
        if len(held):
            rows += cells_for_ticker(held, ticker, "holdout")
        with path.open("a") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        elapsed = time.time() - started
        print(f"  [{i}/{len(pending)}] {ticker}: {len(loaded[ticker]):,} Bars -> "
              f"{len(rows)} Zellen ({elapsed / i:.0f}s/Ticker, "
              f"~{(len(pending) - i) * elapsed / i / 60:.0f} min übrig)", flush=True)


def pooled_cells(path: Path, window: str) -> list[dict]:
    """Cells of one window, pooled per asset class over the tickers in it."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    with path.open() as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("window") != window:
                continue
            key = (row["asset_class"], row["signal"], row["threshold"], row["slice"],
                   row["hold_bars"], row["cost_bps"])
            groups[key].append(row)
    out = []
    for (klass, signal, threshold, slice_label, hold, cost), rows in groups.items():
        out.append(pool_cells(
            rows, asset_class=klass, signal=signal, threshold=threshold,
            slice=slice_label, hold_bars=hold, cost_bps=cost,
        ))
    return out


def phase_report(path: Path, out_path: str | None) -> int:
    search = pooled_cells(path, "search")
    if not search:
        print("Keine Zellen im Checkpoint — erst --phase cells laufen lassen.", file=sys.stderr)
        return 2
    measurable = [c for c in search if c["net_bp"] is not None]
    print(f"\nPhase 2 — Suchfenster: {len(search)} gepoolte Zellen, "
          f"{len(measurable)} über der Stichprobenschwelle ({MIN_TRADES} Trades)")

    plateaus = find_plateaus(search, slice_order=TIME_SLICES)
    print(f"\nPhase 3 — {len(plateaus)} Plateau(s) im Suchfenster:")
    for p in plateaus:
        print(f"  {p['signal']} / {p['asset_class']} @ {p['cost_bps']:.0f}bp — "
              f"{p['size']} Zellen, Median {p['median_net_bp']:+.2f} bp, "
              f"schlechtestes t {p['worst_t']:.2f}, Slices {p['slices']}, Holds {p['hold_bars']}")

    print(f"\n=== HOLD-OUT ({HOLD_OUT_START}+) wird jetzt EINMAL geöffnet ===")
    holdout = {
        (c["asset_class"], c["signal"], c["threshold"], c["slice"], c["hold_bars"], c["cost_bps"]): c
        for c in pooled_cells(path, "holdout")
    }
    survivors = [_validate(p, holdout) for p in plateaus]
    for s in survivors:
        median = "—" if s["median_net_bp"] is None else f"{s['median_net_bp']:+.2f} bp"
        print(f"  {s['signal']} / {s['asset_class']} @ {s['cost_bps']:.0f}bp: "
              f"{'BESTÄTIGT' if s['holds'] else 'GEFALLEN'} — {s['positive_cells']}/{s['cells']} "
              f"Zellen positiv, Median {median}")

    _write_doc(out_path, search, plateaus, survivors)
    return 0


def _validate(plateau: dict, holdout: dict) -> dict:
    """Re-measure exactly the plateau's own cells on the hold-out. No new search, no tuning."""
    values = []
    for threshold in plateau["thresholds"]:
        for slice_label in plateau["slices"]:
            for hold in plateau["hold_bars"]:
                key = (plateau["asset_class"], plateau["signal"], threshold, slice_label,
                       hold, plateau["cost_bps"])
                cell = holdout.get(key)
                if cell is not None and cell["net_bp"] is not None:
                    values.append(cell["net_bp"])
    positive = [v for v in values if v > 0]
    return {
        "signal": plateau["signal"], "asset_class": plateau["asset_class"],
        "cost_bps": plateau["cost_bps"], "search_median_bp": plateau["median_net_bp"],
        "cells": len(values), "positive_cells": len(positive),
        "median_net_bp": sorted(values)[len(values) // 2] if values else None,
        # A plateau "holds" only if the MAJORITY of its own cells stay positive out of sample.
        # One surviving cell out of nine is a coin, not a confirmation.
        "holds": bool(values) and len(positive) > len(values) / 2,
    }


def _write_doc(out, search: list[dict], plateaus: list[dict], survivors: list[dict]) -> None:
    path = Path(out or f"docs/research/{date.today().isoformat()}-signal-matrix.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    measurable = [c for c in search if c["net_bp"] is not None]
    by_class: dict[str, int] = defaultdict(int)
    for cell in measurable:
        by_class[cell["asset_class"]] += 1
    lines = [
        f"# Signal-Matrix: Plateaus statt Siegerzellen ({date.today().isoformat()})",
        "",
        "Nicos Vorgabe: nicht ein Parameter und nicht eine Zeitscheibe, sondern der ganze Raum —",
        "und gesucht wird eine ZUSAMMENHÄNGENDE REGION, keine Gewinnerzelle. Reproduzierbar über",
        "`uv run python scripts/run_signal_matrix.py`; Plan:",
        "`docs/superpowers/plans/2026-08-17-signal-matrix-plateaus.md`.",
        "",
        "## Messraum",
        "",
        f"- {len(SIGNALS)} Signale x je 4 Schwellen x {len(TIME_SLICES)} Zeitscheiben "
        f"(1min bis 1M) x {len(HOLD_BARS)} Haltedauern x {len(COST_BPS)} Kostenstufen",
        f"- {len(search)} gepoolte Zellen, davon **{len(measurable)}** über der "
        f"Stichprobenschwelle ({MIN_TRADES} Trades)",
        "- messbare Zellen je Anlageklasse: "
        + ", ".join(f"{k} {v}" for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])),
        f"- Suchfenster bis {HOLD_OUT_START}, Hold-out danach — **einmal** geöffnet",
        "",
        "## Plateaus im Suchfenster",
        "",
        "| Signal | Klasse | Kosten | Zellen | Median netto | schlecht. t | Slices | Holds |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in plateaus:
        lines.append(
            f"| {p['signal']} | {p['asset_class']} | {p['cost_bps']:.0f} bp | {p['size']} | "
            f"{p['median_net_bp']:+.2f} bp | {p['worst_t']:.2f} | "
            f"{', '.join(p['slices'])} | {p['hold_bars']} |"
        )
    if not plateaus:
        lines += [
            "| — | — | — | — | — | — | — | — |",
            "",
            "**Kein Plateau gefunden.** Das ist ein Ergebnis, kein Fehler: in diesem Raum gibt es",
            "keine zusammenhängende Region, die nach Kosten positiv UND einzeln signifikant ist.",
            "Damit ist die Minutenskala jetzt auf zweistelligen Millionen Bars gemessen statt auf",
            "sieben Tagen — die Frage „wir haben nie richtig hingeschaut“ ist beantwortet.",
        ]
    lines += ["", "## Hold-out", "",
              "| Signal | Klasse | Kosten | Zellen positiv | Median netto | Suchfenster | Urteil |",
              "|---|---|---|---|---|---|---|"]
    for s in survivors:
        median = "—" if s["median_net_bp"] is None else f"{s['median_net_bp']:+.2f} bp"
        lines.append(
            f"| {s['signal']} | {s['asset_class']} | {s['cost_bps']:.0f} bp | "
            f"{s['positive_cells']}/{s['cells']} | {median} | "
            f"{s['search_median_bp']:+.2f} bp | {'BESTÄTIGT' if s['holds'] else 'GEFALLEN'} |"
        )
    if not survivors:
        lines.append("| — | — | — | — | — | — | — |")
    lines += [
        "",
        "## Grenzen dieser Messung",
        "",
        "- **Feed-Bruch:** gemessen auf SIP (konsolidierte Tape), live handeln die Lanes IEX "
        "(~2-3 % des Volumens). Ein bestätigtes Plateau ist ein Kandidat, kein Live-Edge — der "
        "erste Schritt eines Folgeplans ist eine Signal-vs-Fill-Messung.",
        "- **Universum:** die liquidesten Instrumente ihrer Klasse, und Rohstoffe/Währungen als "
        "ETFs (Rollkosten, Tracking-Fehler) statt als Futures. Das ist der billigste Fall für "
        "Handelskosten: was hier scheitert, scheitert überall teurer. Die Umkehrung gilt nicht.",
        "- **Kein Hebel, kein Echtgeld.** Hebel multipliziert einen gesicherten Erwartungswert; "
        "nichts hier sichert einen.",
        "- **Nur regulärer Handel** (09:30-16:00 ET). Pre-/After-Market hat ein Vielfaches der "
        "Spreads, eine Kostenachse von 2-20 bp gilt dort nicht.",
        "- **Long-only.** Leihkosten sind in diesem Projekt nicht messbar, nur schätzbar.",
    ]
    path.write_text("\n".join(lines) + "\n")
    print(f"\nDoku geschrieben: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="*", default=list(MINUTE_UNIVERSE))
    parser.add_argument("--years", type=int, nargs="*", default=list(FULL_YEARS))
    parser.add_argument("--phase", choices=("all", "cells", "report"), default="all")
    parser.add_argument("--checkpoint", default=str(CHECKPOINT))
    parser.add_argument("--out", default=None, help="research doc path (default: docs/research/)")
    args = parser.parse_args()

    path = Path(args.checkpoint)
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.phase in ("all", "cells"):
        phase_cells(args.tickers, args.years, path)
    if args.phase == "cells":
        return 0
    return phase_report(path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
