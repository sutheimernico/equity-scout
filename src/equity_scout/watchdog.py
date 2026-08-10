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

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from equity_scout.state_storage import get_state, set_state

# The crontab's own clock — slot weekdays and wall-clock hours are defined in it, not in UTC
# (02:30 local is 00:30 or 01:30 UTC depending on DST; only the local weekday is stable).
SCHEDULER_TZ = "Europe/Berlin"

CHAIN_SLAS: dict[str, timedelta] = {
    "crypto": timedelta(hours=2),  # */15 cron, around the clock; 2h = several missed cycles
}


@dataclass(frozen=True)
class ChainSchedule:
    """A chain that runs on a weekday cadence, not continuously.

    Alarming such a chain on a flat age SLA is wrong: the nightly slot is Tue–Sat (the
    Saturday run books Friday's close), so on Sunday and Monday its last run is legitimately
    48–72h old and a 26h SLA cried wolf every weekend (measured 2026-08-10: "nightly
    überfällig seit 64 h" while the chain was exactly on schedule). We therefore compare
    against the last slot that was actually DUE — a chain is silent only when it missed a
    planned slot. `hour`/`minute` are the EARLIEST trigger (the cron line), because the
    heartbeat is written when the chain finishes, which can precede the systemd slot.
    """

    hour: int
    minute: int
    weekdays: frozenset[int]  # Python weekday(): Monday=0 … Sunday=6
    slack: timedelta = timedelta(hours=2)


CHAIN_SCHEDULES: dict[str, ChainSchedule] = {
    # cron `0 18 * * 1-5` + user timer 18:05
    "daily": ChainSchedule(hour=18, minute=0, weekdays=frozenset({0, 1, 2, 3, 4})),
    # cron `30 2 * * 2-6` + user timer 02:35 — Tue–Sat, no Sunday/Monday slot
    "nightly": ChainSchedule(hour=2, minute=30, weekdays=frozenset({1, 2, 3, 4, 5})),
}
ALERT_COOLDOWN = timedelta(hours=24)
_SLOT_LOOKBACK_DAYS = 14  # a gap longer than this is not a missed slot but a dead project


def last_due_slot(schedule: ChainSchedule, now_local: datetime) -> datetime | None:
    """The most recent planned slot whose deadline (slot + slack) has already passed."""
    for back in range(_SLOT_LOOKBACK_DAYS + 1):
        day = (now_local - timedelta(days=back)).date()
        if day.weekday() not in schedule.weekdays:
            continue
        slot = datetime.combine(
            day, time(schedule.hour, schedule.minute), tzinfo=now_local.tzinfo
        )
        if slot + schedule.slack <= now_local:
            return slot
    return None


def overdue_chains(db_path: str, *, now: datetime) -> list[dict]:
    """Silent chains: [{chain, last, overdue_hours, missed_slot?}].

    Interval chains (`CHAIN_SLAS`) are judged on heartbeat age; cadence chains
    (`CHAIN_SCHEDULES`) on whether they missed a slot that was due.
    """
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
    now_local = now.astimezone(ZoneInfo(SCHEDULER_TZ))
    for chain, schedule in CHAIN_SCHEDULES.items():
        last = get_state(db_path, key=f"heartbeat_{chain}")
        if not last:
            continue
        slot = last_due_slot(schedule, now_local)
        if slot is None:
            continue
        last_dt = datetime.fromisoformat(last)
        if last_dt >= slot:
            continue
        out.append({
            "chain": chain, "last": last,
            "overdue_hours": (now - last_dt).total_seconds() / 3600.0,
            "missed_slot": slot.isoformat(timespec="minutes"),
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
        # Naming the missed slot keeps the alarm falsifiable: the reader can check the
        # crontab instead of guessing whether the age was even supposed to be smaller.
        missed = item.get("missed_slot")
        why = f"Slot {missed[:16]} verpasst" if missed else f"vor {item['overdue_hours']:.0f} h"
        lines.append(
            f"• {item['chain']}: letzter Lauf {item['last'][:16]} "
            f"({why}) — Laptop aus oder Kette kaputt?"
        )
    lines.append("Nächste Warnung frühestens in 24 h.")
    return "\n".join(lines)
