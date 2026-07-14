"""Refresh the combined universe snapshot from constituent sources.

Network script (scrapes Wikipedia) — not run in tests. Writes a committed CSV snapshot (the "latest"
export the live pipeline reads) plus a provenance note, and archives an `as_of`-dated snapshot in
SQLite — a CSV overwrite alone would silently discard which names were in the universe on past dates
(survivorship bias for any later backtest/ML use of history).
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.constituents import (
    INDEX_CONFIGS,
    ConstituentSource,
    CsvConstituentSource,
    NasdaqTraderSource,
    WikipediaIndexSource,
    WikipediaNikkei225Source,
    WikipediaSP500Source,
    WikipediaStoxx600Source,
    dedupe_by_ticker,
    source_count_report,
)
from equity_scout.data.universe_storage import init_universe_db, save_universe_snapshot
from equity_scout.models import Instrument

_FIELDS = ["ticker", "name", "exchange", "region", "currency", "sector"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-csv", default="data/universe_v1.csv",
                    help="Hand-curated global universe kept as a source.")
    ap.add_argument("--out", default="data/universe_combined.csv")
    ap.add_argument("--db", default=DEFAULT_DB_PATH,
                    help="DB to archive the dated universe snapshot in.")
    args = ap.parse_args()

    named_sources: list[tuple[str, ConstituentSource, int]] = [
        ("hand-curated v1 CSV", CsvConstituentSource(args.base_csv), 30),
        ("Wikipedia S&P 500", WikipediaSP500Source(), 400),
        ("Wikipedia STOXX 600", WikipediaStoxx600Source(), 400),
        ("Wikipedia Nikkei 225", WikipediaNikkei225Source(), 150),
    ]
    named_sources += [
        (cfg.name, WikipediaIndexSource(cfg), cfg.min_expected) for cfg in INDEX_CONFIGS
    ]
    # "Screen everything" source stays last: named sources win ticker collisions
    # (richer metadata) — every US-listed common stock incl. ADRs, free + keyless.
    named_sources.append(("NASDAQ Trader directory", NasdaqTraderSource(), 4000))

    fetched: list[list[Instrument]] = []
    counts: list[tuple[str, int, int]] = []
    for name, source, floor in named_sources:
        instruments = source.fetch()
        fetched.append(instruments)
        counts.append((name, len(instruments), floor))
    universe = dedupe_by_ticker([inst for batch in fetched for inst in batch])

    lines, warnings = source_count_report(counts)
    print("Universe sources:")
    for line in lines:
        print(line)
    for warning in warnings:
        print(f"  WARNING: {warning}")
    print(f"Combined (deduped): {len(universe)}")
    now = datetime.now(timezone.utc)

    out = Path(args.out)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        for inst in universe:
            writer.writerow({f: getattr(inst, f) for f in _FIELDS})

    init_universe_db(args.db)
    as_of = now.date().isoformat()
    save_universe_snapshot(args.db, as_of=as_of, instruments=universe)

    prov = out.with_suffix(".PROVENANCE.md")
    retrieved = now.isoformat(timespec="seconds")
    prov.write_text(
        f"# Provenance: {out.name}\n\n"
        f"- Retrieved: {retrieved}\n"
        f"- Sources: hand-curated `{args.base_csv}` + Wikipedia 'List of S&P 500 companies'"
        f" + Wikipedia 'STOXX Europe 600' + Wikipedia 'Nikkei 225'\n"
        f"- Count: {len(universe)} instruments (deduped by ticker)\n"
        f"- Caveat: Wikipedia tables are unofficial and may change format; re-run to refresh.\n"
        f"- Historized: snapshot archived in `{args.db}` (`universe_snapshots`, as_of={as_of}).\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(universe)} instruments to {out} (+ provenance, + snapshot as_of={as_of} in {args.db})")


if __name__ == "__main__":
    main()
