"""Refresh the combined universe snapshot from constituent sources.

Network script (scrapes Wikipedia) — not run in tests. Writes a committed CSV snapshot plus a
provenance note, so live runs read a stable file instead of scraping every time.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from equity_scout.data.constituents import (
    CsvConstituentSource,
    WikipediaNikkei225Source,
    WikipediaSP500Source,
    WikipediaStoxx600Source,
    combine_sources,
)

_FIELDS = ["ticker", "name", "exchange", "region", "currency", "sector"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-csv", default="data/universe_v1.csv",
                    help="Hand-curated global universe kept as a source.")
    ap.add_argument("--out", default="data/universe_combined.csv")
    args = ap.parse_args()

    sources = [
        CsvConstituentSource(args.base_csv),
        WikipediaSP500Source(),
        WikipediaStoxx600Source(),
        WikipediaNikkei225Source(),
    ]
    universe = combine_sources(sources)

    out = Path(args.out)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        writer.writeheader()
        for inst in universe:
            writer.writerow({f: getattr(inst, f) for f in _FIELDS})

    prov = out.with_suffix(".PROVENANCE.md")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prov.write_text(
        f"# Provenance: {out.name}\n\n"
        f"- Retrieved: {now}\n"
        f"- Sources: hand-curated `{args.base_csv}` + Wikipedia 'List of S&P 500 companies'"
        f" + Wikipedia 'STOXX Europe 600' + Wikipedia 'Nikkei 225'\n"
        f"- Count: {len(universe)} instruments (deduped by ticker)\n"
        f"- Caveat: Wikipedia tables are unofficial and may change format; re-run to refresh.\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(universe)} instruments to {out} (+ provenance)")


if __name__ == "__main__":
    main()
