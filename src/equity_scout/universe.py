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


# Yahoo exchange suffix -> ISO country, for splitting the coarse "EU" region tag into
# countries (filter feature). Non-EU region tags already are countries.
_SUFFIX_COUNTRY = {"PA": "FR", "DE": "DE", "MI": "IT", "MC": "ES", "AS": "NL", "SW": "CH",
                   "ST": "SE", "L": "GB", "BR": "BE", "OL": "NO", "CO": "DK", "HE": "FI",
                   "VI": "AT", "LS": "PT", "IR": "IE"}
REGION_GROUPS: dict[str, set[str]] = {
    "europe": {"EU", "UK"},
    "americas": {"US", "CA", "BR"},
    "asia": {"JP", "HK", "CN", "KR", "IN"},
    "oceania": {"AU"},
}


def country_of(region: str, ticker: str) -> str:
    """ISO country for a universe row. US-listed ADRs count as US (listing venue), same
    honest limitation as the region tag itself."""
    if region == "UK":
        return "GB"
    if region != "EU":
        return region
    _, _, suffix = ticker.rpartition(".")
    return _SUFFIX_COUNTRY.get(suffix, "EU") if suffix else "EU"


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
