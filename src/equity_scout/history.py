"""Run-history helpers: how the picks in a bucket churn between two runs."""
from __future__ import annotations


def pick_churn(prev: list[str], curr: list[str]) -> dict:
    """Compare two ordered ticker lists for one bucket. Returns added/removed/stable (sorted)."""
    p, c = set(prev), set(curr)
    return {
        "added": sorted(c - p),
        "removed": sorted(p - c),
        "stable": sorted(c & p),
    }
