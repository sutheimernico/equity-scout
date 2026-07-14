"""Load the static v1 universe from CSV. Global ambition starts as index members later."""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from equity_scout.models import Instrument


def load_universe(csv_path: str | Path) -> list[Instrument]:
    rows: list[Instrument] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                Instrument(
                    ticker=row["ticker"].strip(),
                    name=row["name"].strip(),
                    exchange=row["exchange"].strip(),
                    region=row["region"].strip(),
                    currency=row["currency"].strip(),
                    sector=row["sector"].strip(),
                )
            )
    return rows


def apply_meta_overlay(
    instruments: list[Instrument], sectors: dict[str, str]
) -> list[Instrument]:
    """Fill 'Unknown' sectors from the persistent instrument_meta store. Never overwrites a
    sector the constituent source itself provided."""
    return [
        replace(inst, sector=sectors[inst.ticker])
        if inst.sector in ("", "Unknown") and sectors.get(inst.ticker)
        else inst
        for inst in instruments
    ]
