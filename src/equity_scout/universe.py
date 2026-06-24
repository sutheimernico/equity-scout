"""Load the static v1 universe from CSV. Global ambition starts as index members later."""
from __future__ import annotations

import csv
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
