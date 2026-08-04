import { useEffect, useState } from "react";

const LAST_SYNC_KEY = "es:lastSync";
const PROBE_INTERVAL_MS = 30_000;

export interface Freshness {
  online: boolean;
  lastSync: string | null;
}

/** Banner text, or null when the data is live and needs no label. */
export function describeFreshness({ online, lastSync }: Freshness): string | null {
  if (online) return null;
  if (!lastSync) return "Cockpit nicht erreichbar — keine gespeicherten Daten.";
  const when = new Date(lastSync).toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `Cockpit nicht erreichbar — Stand von ${when}.`;
}

/**
 * Tracks whether the FastAPI backend is actually reachable right now, independent of what
 * the service worker's cache says. /api/health touches no DB and no price feed, so a failure
 * here means the machine (or the tunnel) is down, not just a slow upstream fetch.
 */
export function useFreshness(): Freshness {
  // Assume reachable until a probe says otherwise — the banner must never flash on a
  // healthy load just because the first probe hasn't landed yet.
  const [state, setState] = useState<Freshness>(() => ({
    online: true,
    lastSync: localStorage.getItem(LAST_SYNC_KEY),
  }));

  useEffect(() => {
    let cancelled = false;

    async function probe() {
      try {
        // no-store bypasses the service worker's stale-while-revalidate cache on purpose:
        // a cached 200 from a machine that has since gone offline would make an unreachable
        // cockpit look online, which is exactly the lie this hook exists to catch.
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!res.ok) throw new Error(`/api/health returned ${res.status}`);
        const now = new Date().toISOString();
        localStorage.setItem(LAST_SYNC_KEY, now);
        if (!cancelled) setState({ online: true, lastSync: now });
      } catch {
        if (!cancelled) {
          setState({ online: false, lastSync: localStorage.getItem(LAST_SYNC_KEY) });
        }
      }
    }

    probe();
    const id = setInterval(probe, PROBE_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return state;
}
