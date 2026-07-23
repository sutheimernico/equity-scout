"""Drift scan for voices' generic-word exposure (v13 Q4). Informational, always exit 0.

`_GENERIC_FIRST_WORDS` is a manually curated snapshot (2026-07-15): headline words that
must never resolve to a ticker on their own. A universe refresh can create NEW exposed
words (a one-owner multi-word first word, or a fresh single-token company name) that
belong on that list. This scan computes the currently exposed words with the exact same
normalization voices uses, diffs them against the committed snapshot file, and prints
additions/removals for human review — the curation decision stays manual.

Usage:
    python scripts/scan_generic_words.py [--universe data/universe_combined.csv]
        [--snapshot data/voices_exposed_words.txt] [--update]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from equity_scout.evidence.voices import _GENERIC_FIRST_WORDS, _normalize_universe_name
from equity_scout.universe import load_universe

DEFAULT_UNIVERSE = "data/universe_combined.csv"
DEFAULT_SNAPSHOT = "data/voices_exposed_words.txt"


def exposed_words(universe: list[tuple[str, str]]) -> set[str]:
    """The words resolve_ticker would trust as a stand-alone name mention today: unique
    (one-owner) first words of multi-word names longer than 3 chars, plus single-token
    company names — minus everything the generic-word gate already blocks."""
    norm_names = {ticker: _normalize_universe_name(name) for ticker, name in universe}
    first_word_owners: dict[str, set[str]] = {}
    single_tokens: set[str] = set()
    for ticker, norm_name in norm_names.items():
        if not norm_name:
            continue
        if " " in norm_name:
            first_word_owners.setdefault(norm_name.split()[0], set()).add(ticker)
        else:
            single_tokens.add(norm_name)
    exposed = {
        word
        for word, owners in first_word_owners.items()
        if len(owners) == 1 and len(word) > 3 and word not in _GENERIC_FIRST_WORDS
    }
    exposed |= {word for word in single_tokens if word not in _GENERIC_FIRST_WORDS}
    return exposed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE)
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    ap.add_argument("--update", action="store_true", help="rewrite the snapshot file")
    args = ap.parse_args()

    instruments = load_universe(args.universe)
    current = exposed_words([(inst.ticker, inst.name) for inst in instruments])

    snapshot_path = Path(args.snapshot)
    if snapshot_path.exists():
        previous = {w for w in snapshot_path.read_text().split() if w}
        added = sorted(current - previous)
        removed = sorted(previous - current)
        print(f"Exponierte Wörter: {len(current)} (Snapshot: {len(previous)})")
        print(f"Neu seit Snapshot ({len(added)}): {' '.join(added) or '—'}")
        print(f"Weggefallen ({len(removed)}): {' '.join(removed) or '—'}")
        if added:
            print(
                "Review: Kandidaten für _GENERIC_FIRST_WORDS prüfen (generische englische"
                " Wörter blocken, echte Firmennamen stehen lassen), dann --update."
            )
    else:
        print(f"Kein Snapshot unter {snapshot_path} — erster Lauf; mit --update anlegen.")
        print(f"Aktuell exponierte Wörter: {len(current)}")

    if args.update:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text("\n".join(sorted(current)) + "\n")
        print(f"Snapshot aktualisiert: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
