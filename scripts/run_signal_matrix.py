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
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from equity_scout.data.minute_bars import load_minutes  # noqa: E402
from equity_scout.data.news_history import items_for_ticker, load_news  # noqa: E402
from equity_scout.matrix.grid import (  # noqa: E402
    COST_BPS,
    HOLD_BARS,
    HOLD_OUT_START,
    MIN_TRADES,
    cell_from_returns,
    split_periods,
    trade_returns,
)
from equity_scout.matrix.contexts import CONTEXTS, recent_signal_gate  # noqa: E402
from equity_scout.matrix.plateau import find_plateaus  # noqa: E402
from equity_scout.matrix.signals import SIGNALS  # noqa: E402
from equity_scout.matrix.timeframes import INTRADAY_SLICES, TIME_SLICES, resample_bars  # noqa: E402

from scripts.fetch_minute_history import (  # noqa: E402
    FULL_YEARS,
    MINUTE_UNIVERSE,
    asset_class,
)

CHECKPOINT = Path("data/matrix_cells.jsonl")
GATE_WINDOW_BARS = 10  # how long a signal counts as "recently fired" when it acts as a condition


VIX_SNAPSHOT = "data/prices/vix_level.csv"  # written by run_autotrader's VolTarget collector


def _vix_closes():
    """Daily VIX closes for the calm/stressed conditions, or None when the snapshot is absent.

    Absent means those two conditions never hold and are dropped from the axis — a missing fear
    gauge must not silently become "calm", which is the direction that would invent trades.
    """
    from equity_scout.data.etf_panel import load_snapshot

    try:
        panel = load_snapshot(VIX_SNAPSHOT)
        return panel.closes["^VIX"].dropna()
    except Exception as err:  # noqa: BLE001 — an unreadable snapshot is a dropped axis, not a crash
        print(f"Warnung: VIX-Snapshot nicht lesbar ({type(err).__name__}: {err}) — "
              "Bedingungen calm_market/stressed_market entfallen.", file=sys.stderr)
        return None


def build_conditions(*, pairs: bool) -> dict:
    """The condition axis: {name: mask(bars, news_stamps=, vix_closes=)}.

    Without `pairs` it is the market-context set (time of day, trend, volume regime, news window,
    VIX bands). With `pairs` every SIGNAL additionally becomes a condition via
    `recent_signal_gate`, which is what "every parameter against every parameter" requires — and
    the reason it has to be a STATE rather than a coincidence is written up in contexts.py.

    Gates use each signal's MIDDLE threshold only. Crossing all four thresholds of the gate with
    all four of the signal would quadruple an already large space for a distinction the plateau
    logic cannot use: the gate is a condition, not the thing under test.
    """
    conditions = {name: spec.mask for name, spec in CONTEXTS.items()}
    if pairs:
        for name, spec in SIGNALS.items():
            middle = spec.thresholds[len(spec.thresholds) // 2]
            conditions[f"after_{name}"] = recent_signal_gate(
                spec.detect, threshold=middle, window_bars=GATE_WINDOW_BARS
            )
    return conditions


def combine_conditions(conditions: dict, depth: int) -> dict:
    """Add AND-combinations of conditions up to `depth` — Nico's "maybe it takes three or four
    parameters together".

    The combinatorics are brutal and that is the point of measuring rather than arguing: 22
    single conditions give 231 pairs, 1540 triples and 7315 quadruples. Each AND cuts the sample
    further, so most deep cells land under MIN_TRADES and report their count instead of a number.
    That is the honest answer to "how deep can we go" — the matrix states it per cell rather than
    me asserting a limit.

    Two guards keep the space from being nonsense rather than merely large:
    - `none` never enters a combination (it is the baseline, and "none AND x" is just "x").
    - Time-of-day conditions are mutually exclusive, so combining two of them yields an empty
      mask. They are excluded from each other's combinations instead of being measured as zero.
    """
    from itertools import combinations

    exclusive = {"first_hour", "midday", "last_hour"}
    base = {k: v for k, v in conditions.items() if k != "none"}
    out = dict(conditions)
    for size in range(2, depth + 1):
        for names in combinations(sorted(base), size):
            if len(exclusive.intersection(names)) > 1:
                continue  # an empty intersection by construction
            masks = [base[n] for n in names]
            out["+".join(names)] = _and_masks(masks)
    return out


def _and_masks(masks: list):
    """One callable that ANDs several condition masks over the same bars."""
    def combined(bars, **kwargs):
        result = masks[0](bars, **kwargs)
        for mask in masks[1:]:
            result = result & mask(bars, **kwargs)
        return result

    return combined


def cells_for_ticker(
    bars, ticker: str, window: str, *, conditions: dict | None = None,
    news_stamps=None, vix_closes=None,
) -> list[dict]:
    """Every cell of the axis product for one ticker and one period window.

    Two axes are innermost on purpose, both for runtime:
    - **Cost** does not change WHICH trades happen, only what they earn, so trades are computed
      once per (signal, threshold, slice, hold, condition) and each cost level subtracts a
      constant. Factor len(COST_BPS) saved.
    - **Conditions** are masks over the same bars, so each is a cheap AND against flags that were
      already computed once per (signal, threshold, slice).
    """
    rows: list[dict] = []
    klass = asset_class(ticker)
    conditions = conditions or {"none": CONTEXTS["none"].mask}
    for slice_label in TIME_SLICES:
        resampled = resample_bars(
            bars, slice_label, keep_incomplete=slice_label in INTRADAY_SLICES
        )
        if len(resampled) < MIN_TRADES:
            continue  # this slice cannot reach the sample floor for this ticker
        masks = {
            name: mask(resampled, news_stamps=news_stamps, vix_closes=vix_closes)
            for name, mask in conditions.items()
        }
        # A condition that never holds for this ticker/slice is dropped rather than measured as
        # an empty cell — 'no news in this instrument's history' is coverage, not a result.
        masks = {name: m for name, m in masks.items() if bool(m.any())}
        for signal_name, spec in SIGNALS.items():
            for threshold in spec.thresholds:
                flags = spec.detect(resampled, threshold=threshold)
                for condition_name, condition in masks.items():
                    gated = flags & condition if condition_name != "none" else flags
                    for hold in HOLD_BARS:
                        gross = trade_returns(resampled, gated, hold_bars=hold)
                        if len(gross) < MIN_TRADES:
                            # One row records the count so coverage stays visible, but the four
                            # cost variants of an unmeasurable cell carry no extra information.
                            rows.append({
                                "ticker": ticker, "asset_class": klass, "window": window,
                                "signal": signal_name, "threshold": threshold,
                                "slice": slice_label, "hold_bars": hold, "cost_bps": COST_BPS[0],
                                "context": condition_name, "n": len(gross),
                                "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None,
                            })
                            continue
                        for cost in COST_BPS:
                            rows.append({
                                "ticker": ticker, "asset_class": klass, "window": window,
                                "signal": signal_name, "threshold": threshold,
                                "slice": slice_label, "hold_bars": hold, "cost_bps": cost,
                                "context": condition_name,
                                **cell_from_returns(gross, cost_bps=cost),
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


def phase_cells(
    tickers: list[str], years: list[int], path: Path, *, pairs: bool, depth: int = 1
) -> None:
    conditions = build_conditions(pairs=pairs)
    if depth > 1:
        conditions = combine_conditions(conditions, depth)
    news = load_news(years) if any(
        "news" in spec.needs for spec in CONTEXTS.values()
    ) else None
    vix = _vix_closes()
    print(f"Bedingungen: {len(conditions)} "
          f"({'Signal-Paare aktiv' if pairs else 'nur Marktkontext'}), "
          f"News: {0 if news is None else len(news):,} Artikel, "
          f"VIX: {0 if vix is None else len(vix)} Tage", flush=True)
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
        stamps = None
        if news is not None and not news.empty:
            stamps = items_for_ticker(news, ticker)["created_at"]
        rows = []
        for frame, label in ((search, "search"), (held, "holdout")):
            if not len(frame):
                continue
            rows += cells_for_ticker(
                frame, ticker, label, conditions=conditions,
                news_stamps=stamps, vix_closes=vix,
            )
        with path.open("a") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        elapsed = time.time() - started
        print(f"  [{i}/{len(pending)}] {ticker}: {len(loaded[ticker]):,} Bars -> "
              f"{len(rows)} Zellen ({elapsed / i:.0f}s/Ticker, "
              f"~{(len(pending) - i) * elapsed / i / 60:.0f} min übrig)", flush=True)


def asset_classes_in(path: Path) -> list[str]:
    """The asset classes present in the checkpoint — the outer loop of the report phase."""
    seen = set()
    with path.open() as handle:
        for line in handle:
            try:
                seen.add(json.loads(line)["asset_class"])
            except (json.JSONDecodeError, KeyError):
                continue
    return sorted(seen)


def pooled_cells(path: Path, window: str, *, klass: str | None = None) -> list[dict]:
    """Cells of one window (optionally one asset class), pooled over the tickers in it.

    Aggregates INCREMENTALLY — running sums per key instead of collecting the rows. With the
    condition axis the checkpoint reaches ~7.7 million rows / 2+ GB, and holding the rows per key
    would need gigabytes of RAM. Reading the file once per asset class costs seconds and keeps
    memory proportional to the number of keys of ONE class.
    """
    acc: dict[tuple, dict] = {}
    with path.open() as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("window") != window:
                continue
            if klass is not None and row["asset_class"] != klass:
                continue
            key = (row["asset_class"], row["signal"], row["threshold"], row["slice"],
                   row["hold_bars"], row["cost_bps"], row.get("context", "none"))
            slot = acc.get(key)
            if slot is None:
                slot = acc[key] = {"n": 0, "tickers": 0, "tickers_measurable": 0,
                                   "w": 0.0, "gross": 0.0, "net": 0.0, "hit": 0.0,
                                   "t_num": 0.0, "t_w": 0.0}
            n = row["n"]
            slot["n"] += n
            slot["tickers"] += 1
            if row["net_bp"] is None:
                continue
            slot["tickers_measurable"] += 1
            slot["w"] += n
            slot["gross"] += row["gross_bp"] * n
            slot["net"] += row["net_bp"] * n
            slot["hit"] += row["hit_rate"] * n
            if row["t"] is not None:
                slot["t_num"] += row["t"] * (n ** 0.5)
                slot["t_w"] += n
    out = []
    for (klass_, signal, threshold, slice_label, hold, cost, context), slot in acc.items():
        cell = {
            "asset_class": klass_, "signal": signal, "threshold": threshold,
            "slice": slice_label, "hold_bars": hold, "cost_bps": cost, "context": context,
            "n": slot["n"], "tickers": slot["tickers"],
            "tickers_measurable": slot["tickers_measurable"],
            "gross_bp": None, "net_bp": None, "t": None, "hit_rate": None,
        }
        if slot["w"] > 0:
            cell["gross_bp"] = slot["gross"] / slot["w"]
            cell["net_bp"] = slot["net"] / slot["w"]
            cell["hit_rate"] = slot["hit"] / slot["w"]
            if slot["t_w"] > 0:
                # Stouffer-style pooled t, as in grid.pool_cells — conservative on purpose.
                cell["t"] = slot["t_num"] / (slot["t_w"] ** 0.5)
        out.append(cell)
    return out


def phase_report(path: Path, out_path: str | None) -> int:
    classes = asset_classes_in(path)
    if not classes:
        print("Keine Zellen im Checkpoint — erst --phase cells laufen lassen.", file=sys.stderr)
        return 2
    print(f"\nPhase 2 — Pooling je Anlageklasse: {', '.join(classes)}")
    plateaus: list[dict] = []
    counted = {"cells": 0, "measurable": 0}
    per_class: dict[str, int] = {}
    for klass in classes:
        cells = pooled_cells(path, "search", klass=klass)
        measurable_here = [c for c in cells if c["net_bp"] is not None]
        counted["cells"] += len(cells)
        counted["measurable"] += len(measurable_here)
        per_class[klass] = len(measurable_here)
        found = find_plateaus(cells, slice_order=TIME_SLICES)
        plateaus.extend(found)
        print(f"  {klass}: {len(cells):,} Zellen, {len(measurable_here):,} messbar, "
              f"{len(found)} Plateau(s)", flush=True)
    print(f"\nGesamt: {counted['cells']:,} gepoolte Zellen, "
          f"{counted['measurable']:,} über der Stichprobenschwelle ({MIN_TRADES} Trades)")
    plateaus = sorted(plateaus, key=lambda p: (-p["size"], -p["median_net_bp"]))
    print(f"\nPhase 3 — {len(plateaus)} Plateau(s) im Suchfenster:")
    for p in plateaus:
        print(f"  {p['signal']} [{p['context']}] / {p['asset_class']} "
              f"@ {p['cost_bps']:.0f}bp — "
              f"{p['size']} Zellen, Median {p['median_net_bp']:+.2f} bp, "
              f"schlechtestes t {p['worst_t']:.2f}, Slices {p['slices']}, Holds {p['hold_bars']}")

    print(f"\n=== HOLD-OUT ({HOLD_OUT_START}+) wird jetzt EINMAL geöffnet ===")
    holdout = {}
    for klass in sorted({p["asset_class"] for p in plateaus}):
        for cell in pooled_cells(path, "holdout", klass=klass):
            holdout[(cell["asset_class"], cell["signal"], cell["threshold"], cell["slice"],
                     cell["hold_bars"], cell["cost_bps"], cell["context"])] = cell
    survivors = [_validate(p, holdout) for p in plateaus]
    for s in survivors:
        median = "—" if s["median_net_bp"] is None else f"{s['median_net_bp']:+.2f} bp"
        print(f"  {s['signal']} [{s['context']}] / {s['asset_class']} "
              f"@ {s['cost_bps']:.0f}bp: "
              f"{'BESTÄTIGT' if s['holds'] else 'GEFALLEN'} — {s['positive_cells']}/{s['cells']} "
              f"Zellen positiv, Median {median}")

    _write_doc(out_path, counted, per_class, plateaus, survivors)
    return 0


def _validate(plateau: dict, holdout: dict) -> dict:
    """Re-measure exactly the plateau's own cells on the hold-out. No new search, no tuning."""
    values = []
    for threshold in plateau["thresholds"]:
        for slice_label in plateau["slices"]:
            for hold in plateau["hold_bars"]:
                key = (plateau["asset_class"], plateau["signal"], threshold, slice_label,
                       hold, plateau["cost_bps"], plateau.get("context", "none"))
                cell = holdout.get(key)
                if cell is not None and cell["net_bp"] is not None:
                    values.append(cell["net_bp"])
    positive = [v for v in values if v > 0]
    return {
        "signal": plateau["signal"], "asset_class": plateau["asset_class"],
        "context": plateau.get("context", "none"),
        "cost_bps": plateau["cost_bps"], "search_median_bp": plateau["median_net_bp"],
        "cells": len(values), "positive_cells": len(positive),
        "median_net_bp": sorted(values)[len(values) // 2] if values else None,
        # A plateau "holds" only if the MAJORITY of its own cells stay positive out of sample.
        # One surviving cell out of nine is a coin, not a confirmation.
        "holds": bool(values) and len(positive) > len(values) / 2,
    }


def _write_doc(out, counted: dict, by_class: dict, plateaus: list[dict],
               survivors: list[dict]) -> None:
    path = Path(out or f"docs/research/{date.today().isoformat()}-signal-matrix.md")
    path.parent.mkdir(parents=True, exist_ok=True)
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
        f"(1min bis 1M) x {len(HOLD_BARS)} Haltedauern x {len(COST_BPS)} Kostenstufen "
        f"x Bedingungen (Marktkontext + jedes Signal als Zustand)",
        "- Bedingungen sind KEINE Nachbarschaftsachse: „wirkt nur nach einer Meldung\" ist eine "
        "andere Behauptung als „wirkt immer\", also bekommt jede Bedingung eigene Regionen",
        f"- {counted['cells']:,} gepoolte Zellen, davon **{counted['measurable']:,}** über "
        f"der Stichprobenschwelle ({MIN_TRADES} Trades)",
        "- messbare Zellen je Anlageklasse: "
        + ", ".join(f"{k} {v}" for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])),
        f"- Suchfenster bis {HOLD_OUT_START}, Hold-out danach — **einmal** geöffnet",
        "",
        "## Plateaus im Suchfenster",
        "",
        "| Signal | Bedingung | Klasse | Kosten | Zellen | Median netto | schlecht. t | Slices | Holds |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in plateaus:
        lines.append(
            f"| {p['signal']} | {p['context']} | {p['asset_class']} | "
            f"{p['cost_bps']:.0f} bp | {p['size']} | "
            f"{p['median_net_bp']:+.2f} bp | {p['worst_t']:.2f} | "
            f"{', '.join(p['slices'])} | {p['hold_bars']} |"
        )
    if not plateaus:
        lines += [
            "| — | — | — | — | — | — | — | — | — |",
            "",
            "**Kein Plateau gefunden.** Das ist ein Ergebnis, kein Fehler: in diesem Raum gibt es",
            "keine zusammenhängende Region, die nach Kosten positiv UND einzeln signifikant ist.",
            "Damit ist die Minutenskala jetzt auf zweistelligen Millionen Bars gemessen statt auf",
            "sieben Tagen — die Frage „wir haben nie richtig hingeschaut“ ist beantwortet.",
        ]
    lines += ["", "## Hold-out", "",
              "| Signal | Bedingung | Klasse | Kosten | Zellen positiv | Median netto | Suchfenster | Urteil |",
              "|---|---|---|---|---|---|---|---|"]
    for s in survivors:
        median = "—" if s["median_net_bp"] is None else f"{s['median_net_bp']:+.2f} bp"
        lines.append(
            f"| {s['signal']} | {s['context']} | {s['asset_class']} | "
            f"{s['cost_bps']:.0f} bp | {s['positive_cells']}/{s['cells']} | {median} | "
            f"{s['search_median_bp']:+.2f} bp | {'BESTÄTIGT' if s['holds'] else 'GEFALLEN'} |"
        )
    if not survivors:
        lines.append("| — | — | — | — | — | — | — | — |")
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
    parser.add_argument("--pairs", action="store_true",
                        help="jedes Signal zusätzlich als Bedingung für jedes andere")
    parser.add_argument("--depth", type=int, default=1,
                        help="Kombinationstiefe der Bedingungen (1=einzeln, 2=Paare, ...)")
    parser.add_argument("--checkpoint", default=str(CHECKPOINT))
    parser.add_argument("--out", default=None, help="research doc path (default: docs/research/)")
    args = parser.parse_args()

    path = Path(args.checkpoint)
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.phase in ("all", "cells"):
        phase_cells(args.tickers, args.years, path, pairs=args.pairs, depth=args.depth)
    if args.phase == "cells":
        return 0
    return phase_report(path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
