"""Dead-man watchdog (v12 W1, review 2026-07-20): the always-on promise is only
trustworthy when a silently dead chain makes noise.

Every guarded chain records a heartbeat in the main DB on success. The 24/7 crypto cron
(the only scheduler that runs around the clock) checks them against per-chain SLAs and
sends ONE Telegram warning per chain per cooldown window. Honesty rules: a chain that has
never beaten is not alarmed (monitoring starts with its first heartbeat), and when the
whole laptop was asleep the alarm text says exactly that — offline time IS downtime.
If the machine itself is off, nothing here can fire; an external monitor would be a paid
service and is Nico's call (documented, never signed up autonomously)."""
from __future__ import annotations

from datetime import datetime, timedelta

from equity_scout.state_storage import get_state, set_state

CHAIN_SLAS: dict[str, timedelta] = {
    "daily": timedelta(hours=26),  # 18:05 slot + slack
    "nightly": timedelta(hours=26),  # 02:35 slot + slack
    "crypto": timedelta(hours=2),  # */15 cron; 2h = several missed cycles
}
ALERT_COOLDOWN = timedelta(hours=24)


def overdue_chains(db_path: str, *, now: datetime) -> list[dict]:
    """Chains whose last heartbeat exceeds their SLA: [{chain, last, overdue_hours}]."""
    out: list[dict] = []
    for chain, sla in CHAIN_SLAS.items():
        last = get_state(db_path, key=f"heartbeat_{chain}")
        if not last:
            continue
        age = now - datetime.fromisoformat(last)
        if age > sla:
            out.append({
                "chain": chain, "last": last,
                "overdue_hours": age.total_seconds() / 3600.0,
            })
    return out


def alerts_due(db_path: str, overdue: list[dict], *, now: datetime) -> list[dict]:
    """Overdue chains whose last alert lies outside the cooldown window."""
    due: list[dict] = []
    for item in overdue:
        last_alert = get_state(db_path, key=f"watchdog_alerted_{item['chain']}")
        if last_alert and now - datetime.fromisoformat(last_alert) < ALERT_COOLDOWN:
            continue
        due.append(item)
    return due


def mark_alerted(db_path: str, chains: list[str], *, now: datetime) -> None:
    for chain in chains:
        set_state(db_path, key=f"watchdog_alerted_{chain}", value=now.isoformat())


def build_alert_text(due: list[dict]) -> str:
    lines = ["🚨 Watchdog: Kette(n) ohne Lebenszeichen"]
    for item in due:
        lines.append(
            f"• {item['chain']}: letzter Lauf {item['last'][:16]} "
            f"(vor {item['overdue_hours']:.0f} h) — Laptop aus oder Kette kaputt?"
        )
    lines.append("Nächste Warnung frühestens in 24 h.")
    return "\n".join(lines)
