"""Resolve the no-trade book: what would each rejected opportunity have done?

Nico's question (2026-08-16): "Möglichkeiten, die nicht getradet wurden aus Scoregründen —
vielleicht war der Score nicht gut genug, aber es hat trotzdem funktioniert. Woran lag das?"
This module answers it every night, with the SAME entry convention and exit rules the live
lane runs — a rejection judged under different rules would measure a lane that never existed
(same stance as lane_tuning).

Honesty boundary: simulated returns are GROSS. They answer "was the rejection right?", never
"would we have made money?" — a rejected trade paid no costs and moved no price.

Pure functions over handed-in price series; the runner script owns all I/O.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from equity_scout.exits import ExitRules
from equity_scout.lane_tuning import simulate_event

# After this many calendar days past the lane's own holding limit, an unresolvable rejection
# closes anyway ("Reihe zu Ende" / "keine Daten") — otherwise a delisted or never-quoted
# ticker keeps a row open forever and the open-count stops meaning anything.
GRACE_CALENDAR_DAYS = 14


def _age_days(seen_at: str, now: datetime) -> int:
    seen = pd.Timestamp(seen_at[:10]).date()
    return (now.date() - seen).days


def resolve_swing_rejections(
    rejections: list[dict],
    closes_by_ticker: dict[str, pd.Series],
    rules: ExitRules,
    *,
    now: datetime,
) -> list[dict]:
    """[{id, sim_return, sim_exit_reason, resolved_at}] for everything that is due.

    Entry is the close AFTER the event's day (lane_tuning.evaluate convention — the lane
    never fills on the event bar itself). A rejection resolves when a real exit rule fires
    in simulation; a series that has not decided yet stays open until the grace window
    closes it with whatever the last observation says.
    """
    resolved_at = now.isoformat(timespec="seconds")
    out: list[dict] = []
    for rejection in rejections:
        overdue = _age_days(rejection["seen_at"], now) > rules.max_holding_days + GRACE_CALENDAR_DAYS

        def _close(sim_return: float | None, reason: str) -> None:
            out.append({
                "id": rejection["id"], "resolved_at": resolved_at,
                "sim_return": sim_return, "sim_exit_reason": reason,
            })

        closes = closes_by_ticker.get(rejection["ticker"])
        if closes is None or closes.empty:
            if overdue:
                _close(None, "keine Daten")
            continue
        pos = closes.index.searchsorted(pd.Timestamp(rejection["seen_at"][:10]))
        entry_index = pos + 1
        if entry_index >= len(closes):
            if overdue:
                _close(None, "keine Daten")
            continue
        sim_return, reason = simulate_event(closes, entry_index, rules)
        if reason == "Reihe zu Ende" and not overdue:
            continue  # no rule has fired yet — cutting off now would truncate the long runs
        _close(sim_return, reason)
    return out
