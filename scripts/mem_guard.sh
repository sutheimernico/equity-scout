#!/usr/bin/env bash
# Run a heavy chain under a memory ceiling.
#
# Why this exists: on 2026-08-19 22:48 one matrix-chain python3 reached 10.1 GiB RSS
# inside a WSL VM capped at 15.8 GiB. The kernel OOM-killer fired at load average 13 and
# took the box with it -- three WSL restarts in five minutes, every attached Claude
# session gone, and the matrix run itself dead with a 0-byte log. .wslconfig now grants
# 20 GB + 24 GB swap, but headroom alone is not a guarantee: a runaway job must degrade
# into swap and, at worst, die alone -- never take the VM and the whole cron fleet with it.
#
# Two ceilings, both root-free (cgroup v2 delegates cpu/memory/pids to user-1000.slice):
#   MemoryHigh -- soft. Throttles allocation and reclaims into swap. Job keeps running.
#   MemoryMax  -- hard. cgroup-local OOM: kills this chain only, the VM never notices.
# Plus oom_score_adj=+500 (positive deltas need no privilege, and children inherit it) so
# that if a *global* OOM ever happens anyway, the kernel prefers this batch chain over an
# interactive session.
#
# Degrades open by design: no systemd-run, no user bus, unset XDG_RUNTIME_DIR -- the
# command still runs, merely uncapped. A missing ceiling must never block the autopilot.
#
# Usage: mem_guard.sh <command> [args...]
# Seams: EQUITY_SCOUT_MEM_HIGH / _MAX override the ceilings, EQUITY_SCOUT_MEM_GUARD=off
#        bypasses entirely, EQUITY_SCOUT_MEM_GUARD_LOG records which path was taken.
set -u

# Ceilings are derived from the VM's actual RAM, not hardcoded: the .wslconfig cap moved
# from 15.8 to 20 GiB on 2026-08-19 and will move again. A fixed 16G ceiling would have
# been silently above the old cap -- a guard that guards nothing is worse than none.
mem_fraction() {  # $1 = percent of MemTotal, rounded down to whole MiB
  awk -v pct="$1" '/^MemTotal:/ { printf "%dM", int($2 * pct / 100 / 1024) }' /proc/meminfo
}
HIGH="${EQUITY_SCOUT_MEM_HIGH:-$(mem_fraction 60)}"   # throttle + swap from here
MAX="${EQUITY_SCOUT_MEM_MAX:-$(mem_fraction 80)}"     # hard stop, still below the VM cap
GUARD_LOG="${EQUITY_SCOUT_MEM_GUARD_LOG:-}"

[ "$#" -gt 0 ] || { echo "mem_guard.sh: no command given" >&2; exit 2; }

note() { [ -n "$GUARD_LOG" ] && printf '%s\n' "$1" >> "$GUARD_LOG"; return 0; }

# Prefer this chain as the OOM victim over anything interactive. Best-effort: a
# read-only /proc (containers) must not abort the run.
echo 500 > /proc/self/oom_score_adj 2>/dev/null || true

if [ "${EQUITY_SCOUT_MEM_GUARD:-on}" = "off" ]; then
  note "bypass: EQUITY_SCOUT_MEM_GUARD=off"
  exec "$@"
fi

# cron gives us neither of these; lingering (loginctl enable-linger) keeps the user
# manager and its runtime dir alive around the clock, so deriving them is safe.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

if ! command -v systemd-run >/dev/null 2>&1; then
  note "uncapped: systemd-run not found"
  exec "$@"
fi

# --scope runs the command as our own child (not a forked service), so exit code, stdout
# and the caller's redirections all pass straight through -- the callers append to their
# own logs and must keep doing so.
if systemd-run --user --scope --quiet \
     -p MemoryHigh="$HIGH" -p MemoryMax="$MAX" -- "$@"; then
  rc=0
else
  rc=$?
fi

# 237 = EXIT_CGROUP: the scope could not be created (no user bus, delegation missing).
# The ceiling failed, the work did not run at all -- retry uncapped rather than silently
# skipping a night of training.
if [ "$rc" = 237 ] || [ "$rc" = 226 ]; then
  note "uncapped: scope setup failed (rc=$rc)"
  exec "$@"
fi

note "capped: high=$HIGH max=$MAX rc=$rc"
exit "$rc"
