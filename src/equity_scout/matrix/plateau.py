"""Find PLATEAUS in the cell grid — the unit of evidence this whole package is built around.

The reasoning, in one paragraph: searching a large space and taking the best cell is guaranteed
to find something. With 7 signals x 4 thresholds x 8 slices x 5 holds x 4 cost levels the space
has thousands of cells, and at the 5 % level pure chance produces dozens of "significant"
winners. That failure mode already cost this project five weeks (the entry champion that claimed
AUC 0.6195 on 220 rows and delivered 0.5152 on 3281). A plateau is the answer: a rule must hold
across a CONNECTED region of its own parameter neighbourhood. Noise does not arrive in connected
blocks; a mechanism does — something that works at a 0.5 % threshold with a 3-bar hold does not
abruptly stop working at 1 % and 2 bars.

Adjacency is defined per axis: two cells are neighbours when they share signal, cost level and
asset class, and differ by exactly one step in exactly one of (threshold, slice, hold). Cost is
NOT an adjacency axis — a rule that only survives at 2 bp is not robust, it is a different
economic claim, so each cost level gets its own regions. Asset class is not one either, for the
same reason: "works on gold and on bonds" is a finding, not a single cell.
"""
from __future__ import annotations

from statistics import median

MIN_PLATEAU_CELLS = 4  # fewer cells cannot show that neighbours agree
PLATEAU_T = 2.0  # every member cell must clear this on its own
_ADJACENCY_AXES = ("threshold", "slice", "hold_bars")
# Grouping axes are never adjacency axes: each of their values gets its own regions, because
# "works only under this condition / only at this cost / only in this asset class" is a
# DIFFERENT claim from "works generally" — merging them would hide the finding.
_GROUP_AXES = ("signal", "cost_bps", "asset_class", "context")


def _axis_values(cells: list[dict], key: str, order: dict | None = None) -> list:
    values = {cell[key] for cell in cells}
    if order is not None:
        return sorted(values, key=lambda v: order.get(v, 0))
    return sorted(values)


def qualifying_cells(cells: list[dict]) -> list[dict]:
    """Cells that qualify for membership: measurable, positive after costs, individually
    significant. Everything else cannot be part of a plateau, including cells that are merely
    'not negative' — a plateau of coin flips is still a coin flip."""
    return [
        cell for cell in cells
        if cell.get("net_bp") is not None and cell.get("t") is not None
        and cell["net_bp"] > 0 and cell["t"] >= PLATEAU_T
    ]


def find_plateaus(cells: list[dict], *, slice_order: tuple[str, ...] = ()) -> list[dict]:
    """Connected regions of qualifying cells, one summary dict per region.

    `slice_order` gives the slice axis its true ordering (1min ... 1M); without it the axis
    would sort alphabetically and "1D" would sit next to "1M" instead of next to "60min".
    Regions smaller than MIN_PLATEAU_CELLS are dropped — that is the guard against lucky cells.
    """
    members = qualifying_cells(cells)
    if not members:
        return []
    order = {name: i for i, name in enumerate(slice_order)}
    # The slice axis comes from the DECLARED order, not from the slices present in `cells`.
    # Deriving it from the data would make two cells neighbours whenever the slice between
    # them is missing — e.g. 1D next to 1M when 1W fell under the sample floor — and silently
    # weld two unrelated regions into one "plateau".
    # The threshold axis is PER SIGNAL. A global axis would mix incompatible units — most
    # signals take a percentage, `consecutive_down` takes a bar COUNT — and two thresholds of one
    # signal could end up non-adjacent because another signal's value sits between them.
    thresholds_by_signal: dict[str, list] = {}
    for cell in cells:
        thresholds_by_signal.setdefault(cell["signal"], set()).add(cell["threshold"])
    thresholds_by_signal = {k: sorted(v) for k, v in thresholds_by_signal.items()}
    steps = {
        "slice": list(slice_order) or _axis_values(cells, "slice"),
        "hold_bars": _axis_values(cells, "hold_bars"),
    }
    index = {
        # `.get(axis, "none")` keeps pre-context cells readable: a matrix run without the
        # condition axis is simply one where every cell has no condition.
        tuple(cell.get(axis, "none") for axis in (*_GROUP_AXES, *_ADJACENCY_AXES)): cell
        for cell in members
    }

    def neighbours(key: tuple):
        group, position = key[: len(_GROUP_AXES)], dict(zip(_ADJACENCY_AXES, key[len(_GROUP_AXES):]))
        signal = group[_GROUP_AXES.index("signal")]
        for axis in _ADJACENCY_AXES:
            values = (
                thresholds_by_signal[signal] if axis == "threshold" else steps[axis]
            )
            at = values.index(position[axis])
            for offset in (-1, 1):
                nxt = at + offset
                if 0 <= nxt < len(values):
                    moved = dict(position)
                    moved[axis] = values[nxt]
                    candidate = (*group, *(moved[a] for a in _ADJACENCY_AXES))
                    if candidate in index:
                        yield candidate

    seen: set = set()
    plateaus: list[dict] = []
    for key in index:
        if key in seen:
            continue
        region, stack = [], [key]
        seen.add(key)
        while stack:  # flood fill
            current = stack.pop()
            region.append(index[current])
            for candidate in neighbours(current):
                if candidate not in seen:
                    seen.add(candidate)
                    stack.append(candidate)
        if len(region) < MIN_PLATEAU_CELLS:
            continue
        plateaus.append({
            "signal": region[0]["signal"],
            "cost_bps": region[0]["cost_bps"],
            "asset_class": region[0]["asset_class"],
            "context": region[0].get("context", "none"),
            "size": len(region),
            "thresholds": sorted({c["threshold"] for c in region}),
            "slices": sorted({c["slice"] for c in region}, key=lambda s: order.get(s, 0)),
            "hold_bars": sorted({c["hold_bars"] for c in region}),
            "median_net_bp": median(c["net_bp"] for c in region),
            "worst_net_bp": min(c["net_bp"] for c in region),
            "worst_t": min(c["t"] for c in region),
            "total_trades": sum(c["n"] for c in region),
        })
    return sorted(plateaus, key=lambda p: (-p["size"], -p["median_net_bp"]))
