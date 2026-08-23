"""Dead-man watchdog (v12 W1, review 2026-07-20): the always-on promise is only
trustworthy when a silently dead chain makes noise.

Every guarded chain records a heartbeat in the main DB on success. The 24/7 crypto cron
(the only scheduler that runs around the clock) checks them against per-chain SLAs and
sends ONE Telegram warning per chain per cooldown window. Honesty rules: a chain that has
never beaten is not alarmed (monitoring starts with its first heartbeat), and when the
whole laptop was asleep the alarm text says exactly that — offline time IS downtime.
If the machine itself is off, nothing here can fire; an external monitor would be a paid
service and is Nico's call (documented, never signed up autonomously). What CAN be done from
inside is to notice the outage afterwards — `scheduler_gap` compares each run against the
previous one and prices the gap in trading minutes, which is the only failure mode the
heartbeat SLAs are structurally blind to."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from equity_scout.market_hours import session_minutes_between
from equity_scout.state_storage import get_state, set_state

# The crontab's own clock — slot weekdays and wall-clock hours are defined in it, not in UTC
# (02:30 local is 00:30 or 01:30 UTC depending on DST; only the local weekday is stable).
SCHEDULER_TZ = "Europe/Berlin"

CHAIN_SLAS: dict[str, timedelta] = {
    "crypto": timedelta(hours=2),  # */15 cron, around the clock; 2h = several missed cycles
    # Catalyst radar (v16). The news sweep is the only radar leg that runs around the clock,
    # so it is the one that can be judged on a flat age. 2h = 120 missed minute cycles: well
    # past a transient outage, well short of crying wolf over a restart.
    "news_sweep": timedelta(hours=2),
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
    # Catalyst ignition scan: every minute Mon-Fri inside the US session. Judged as a cadence
    # chain, not on a flat age — its heartbeat is legitimately ~65h old on a Monday morning,
    # and a flat SLA would have repeated the weekend false alarm the nightly chain taught us
    # about on 2026-08-10. Earliest slot: 09:30 ET = 15:30 Berlin (winter 16:30, absorbed by
    # the slack).
    "catalyst_scan": ChainSchedule(hour=15, minute=30,
                                   weekdays=frozenset({0, 1, 2, 3, 4}),
                                   slack=timedelta(hours=3)),
    # Gap-fade signal window: 09:00-09:28 ET = 15:00 Berlin (winter 16:00, absorbed by the
    # slack). Added 2026-08-20 after the lane spent its first four trading days failing on
    # every single cron slot without a single alarm — it has no continuous heartbeat, so
    # only a missed-slot check can tell "no gap was deep enough" from "the lane is broken".
    # Honest limit: a chain that never beat ONCE is never alarmed (see the test of that
    # name), so this entry would not have caught that very outage. It catches the next one.
    "gapfade": ChainSchedule(hour=15, minute=0, weekdays=frozenset({0, 1, 2, 3, 4}),
                             slack=timedelta(hours=3)),
    # cron `0 18 * * 1-5` + user timer 18:05
    "daily": ChainSchedule(hour=18, minute=0, weekdays=frozenset({0, 1, 2, 3, 4})),
    # cron `30 2 * * 2-6` + user timer 02:35 — Tue–Sat, no Sunday/Monday slot
    "nightly": ChainSchedule(hour=2, minute=30, weekdays=frozenset({1, 2, 3, 4, 5})),
}
ALERT_COOLDOWN = timedelta(hours=24)
_SLOT_LOOKBACK_DAYS = 14  # a gap longer than this is not a missed slot but a dead project

# The watchdog's own cadence: it rides the */15 crypto slot. Three missed cycles is the
# threshold — one late run is a slow crypto fetch, three in a row is the scheduler.
WATCHDOG_CADENCE = timedelta(minutes=15)
SCHEDULER_GAP_THRESHOLD = 3 * WATCHDOG_CADENCE
LAST_GAP_KEY = "watchdog_last_gap"


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


def scheduler_gap(db_path: str, *, now: datetime) -> dict | None:
    """The stretch since the previous watchdog run, if the scheduler itself was away.

    The heartbeat SLAs cannot see this failure by construction. The watchdog rides in the
    same cron command as the crypto lane and runs AFTER it, so on the first run back the
    heartbeat it reads is one second old — a box that slept through a whole afternoon looks
    exactly like a healthy one. Measured on 2026-08-22/23: the host was away 19:01-03:30 and
    again 03:56-13:48, and not one chain reported anything.

    What the caller must do: read this BEFORE writing the new heartbeat, or the gap it would
    measure is zero. Returns None on the first run ever (nothing to compare against) and
    whenever the box simply kept running.
    """
    previous = get_state(db_path, key="heartbeat_watchdog")
    if not previous:
        return None
    since = datetime.fromisoformat(previous)
    gap = now - since
    if gap <= SCHEDULER_GAP_THRESHOLD:
        return None
    return {
        "since": previous,
        "until": now.isoformat(timespec="seconds"),
        "hours": gap.total_seconds() / 3600.0,
        # The only number that decides whether this outage cost anything.
        "session_minutes": session_minutes_between(since, now),
    }


def record_gap(db_path: str, gap: dict, *, now: datetime) -> None:
    """Persist the most recent gap so a later reader can ask what the box missed."""
    set_state(db_path, key=LAST_GAP_KEY, value=json.dumps(gap))


def build_gap_text(gap: dict) -> str:
    """The alert. Leads with the trading minutes, because a long weekend outage and a short
    Tuesday one look identical on duration and could not differ more in what they cost."""
    minutes = gap["session_minutes"]
    verdict = (
        f"{minutes} Handelsminuten verpasst — in dieser Zeit hat keine Lane gehandelt."
        if minutes
        else "0 Handelsminuten betroffen (Markt war ohnehin zu) — kein Handelsschaden."
    )
    return (
        "⏸️ Watchdog: der Scheduler selbst war weg\n"
        f"• {gap['since'][:16]} → {gap['until'][:16]} ({gap['hours']:.1f} h ohne Lauf)\n"
        f"• {verdict}\n"
        "Ursache ist fast immer Windows-Standby; die Heartbeat-SLAs können das nicht sehen, "
        "weil die Ketten beim Aufwachen zuerst laufen und der Wächter danach."
    )
