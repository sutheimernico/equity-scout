# Mobile Focus App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing React dashboard into a phone app that opens on one of four focuses (Heute, Depot, Entscheiden, Beweis), is reachable from a Telegram deep link, and shows the last known state with an honest timestamp when the WSL cockpit is not running.

**Architecture:** No second stack and no rewrite — the PWA manifest, the icons and all four focus views (`TodayView`, `DepotsView`, `InboxPanel`, `ProofView`) already exist. Three additions: (1) URL-driven view state (`?view=depots`) so Telegram can deep-link and the app can restore where you were; (2) a mobile bottom tab bar with the four focuses plus a "Mehr" sheet for the remaining eight views, active below 720 px only — desktop stays exactly as it is; (3) a hand-written service worker (app shell precache + stale-while-revalidate for `/api/*`) plus a freshness banner that names the last successful contact.

**Tech Stack:** React 19, TypeScript 5.8, Vite 7 (existing). New dev dependency: `vitest` (see Task 1 — needs Nico's explicit OK). Service worker is plain JS in `frontend/public/sw.js`, no build plugin, no `vite-plugin-pwa`.

---

## Design constraints (checked against the codebase on 2026-08-04)

1. **Query param, not path routing.** FastAPI serves the built app via `StaticFiles(directory=dist, html=True)` mounted at `/` (`src/equity_scout/api.py:872`). A path route like `/depots` would 404; `?view=depots` always resolves to `index.html`. This is also what the digest links to (`2026-08-04-telegram-signal-diet.md`, Task 4).
2. **Auth is a cookie.** `DASH_TOKEN` is enforced by middleware; `?token=` is exchanged once for the httponly cookie `es_dash` (`api.py:140-167`). Service worker fetches carry cookies automatically, so no token handling belongs in the SW. `start_url: "/"` in the manifest stays correct.
3. **Desktop must not regress.** The sidebar/nav markup in `App.tsx:105-129` stays; the bottom bar is an ADDITIONAL element hidden above 720 px.
4. **No POST caching.** Pitch decisions (`POST /api/inbox/{id}/decision`) always go to the network. Offline means an honest error, not a queued write that silently fires later against stale state.
5. **Stale data must be labelled.** A cached number without a timestamp is a lie waiting to happen.

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/views.ts` | Create: the `View` union, the `NAV` table, `MOBILE_FOCUSES`, and `parseView` — pure, importable by tests and by `App.tsx` |
| `frontend/src/views.test.ts` | Create: `parseView` tests |
| `frontend/src/App.tsx` | Modify: view state from the URL, renders `<BottomNav>` and `<FreshnessBanner>` |
| `frontend/src/components/BottomNav.tsx` | Create: four focus tabs + "Mehr" sheet |
| `frontend/src/components/FreshnessBanner.tsx` | Create: live / "Stand von HH:MM" banner |
| `src/equity_scout/api.py` | Modify: new `/api/health` liveness endpoint (no DB, no feed) |
| `frontend/src/useFreshness.ts` | Create: polls `/api/health`, persists the last successful contact |
| `frontend/public/sw.js` | Create: app shell precache + stale-while-revalidate for `/api/*` |
| `frontend/src/main.tsx` | Modify: register the service worker in production builds only |
| `frontend/src/index.css` | Modify: bottom-nav + sheet + banner styles inside the existing `max-width: 720px` block |
| `frontend/package.json` | Modify: `vitest` dev dependency + `test` script |

---

### Task 1: Introduce vitest (DECISION — needs Nico's OK before starting)

**Files:**
- Modify: `frontend/package.json`

The frontend has no test runner today (checked: no `*.test.tsx`, no vitest/jest in `package.json`). This plan adds pure logic (`parseView`, freshness/stale computation) that should not ship untested, and the house rule is "new logic comes with a test". `vitest` is the Vite-native runner: one dev dependency, reuses the existing `vite.config.ts`, zero effect on the production bundle.

**If Nico declines:** skip this task, drop Task 2's Steps 1-2 and 5, and verify `parseView` manually in the browser instead — the rest of the plan is unaffected.

- [ ] **Step 1: Add the dependency and the script**

In `frontend/package.json`, add to `scripts`:

```json
    "test": "vitest run",
```

and to `devDependencies`:

```json
    "vitest": "^3.2.0",
```

- [ ] **Step 2: Install**

Run: `cd frontend && npm install`
Expected: `added N packages`, no peer-dependency errors against Vite 7.

- [ ] **Step 3: Verify the runner starts**

Run: `cd frontend && npm test`
Expected: `No test files found` (exit code 1 is fine here — it means vitest itself works).

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add vitest for pure-logic tests"
```

---

### Task 2: URL-driven view state

**Files:**
- Create: `frontend/src/views.ts`
- Create: `frontend/src/views.test.ts`
- Modify: `frontend/src/App.tsx:1-57` (extract), `App.tsx:98` (state)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/views.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { MOBILE_FOCUSES, NAV, parseView } from "./views";

describe("parseView", () => {
  it("defaults to today without a view param", () => {
    expect(parseView("")).toBe("today");
    expect(parseView("?foo=bar")).toBe("today");
  });

  it("reads a known view from the query string", () => {
    expect(parseView("?view=depots")).toBe("depots");
    expect(parseView("?view=inbox")).toBe("inbox");
  });

  it("ignores an unknown view instead of blowing up", () => {
    // A stale Telegram link must not break the app — it lands on Heute.
    expect(parseView("?view=nonsense")).toBe("today");
  });

  it("survives extra params and the token exchange param", () => {
    expect(parseView("?token=abc&view=proof")).toBe("proof");
  });
});

describe("nav tables", () => {
  it("exposes exactly the four phone focuses", () => {
    expect(MOBILE_FOCUSES).toEqual(["today", "depots", "inbox", "proof"]);
  });

  it("keeps every focus present in the full nav", () => {
    const keys = NAV.map((item) => item.key);
    for (const focus of MOBILE_FOCUSES) expect(keys).toContain(focus);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './views'`.

- [ ] **Step 3: Create `frontend/src/views.ts`**

Move the view/nav declarations out of `App.tsx` (lines 16-57) into the new module and add the parser:

```typescript
// View identity, navigation tables and URL parsing — extracted from App.tsx so tests and
// the bottom nav can share one source of truth.

export type View =
  | "today"
  | "funnel"
  | "radar"
  | "voices"
  | "inbox"
  | "depots"
  | "proof"
  | "strategies"
  | "model"
  | "ml"
  | "learning"
  | "chat";

// v6 IA (plan P6): visible group labels instead of an anonymous hairline, a "Heute" start
// page, all paper depots under ONE nav item, and unambiguous German names — "Entry-Modell"
// vs "Signal-Filter" ends the old Modell/Meta-Modell collision.
export type Group = "start" | "signale" | "entscheiden" | "forschung" | "mehr";

export const GROUP_LABELS: Record<Group, string> = {
  start: "",
  signale: "Signale",
  entscheiden: "Entscheiden",
  forschung: "Forschung",
  mehr: "",
};

export const NAV: { key: View; label: string; group: Group }[] = [
  { key: "today", label: "Heute", group: "start" },
  { key: "funnel", label: "Screener", group: "signale" },
  { key: "radar", label: "Radar", group: "signale" },
  { key: "voices", label: "Stimmen", group: "signale" },
  { key: "inbox", label: "Inbox", group: "entscheiden" },
  { key: "depots", label: "Depots", group: "entscheiden" },
  { key: "proof", label: "Beweis", group: "entscheiden" },
  { key: "strategies", label: "Strategien", group: "forschung" },
  { key: "model", label: "Entry-Modell", group: "forschung" },
  { key: "ml", label: "Signal-Filter", group: "forschung" },
  { key: "learning", label: "Lernkurven", group: "forschung" },
  { key: "chat", label: "Assistent", group: "mehr" },
];

// The phone gets four tabs; everything else lives behind "Mehr". Order is the tab order.
export const MOBILE_FOCUSES: View[] = ["today", "depots", "inbox", "proof"];

export const MOBILE_LABELS: Record<string, string> = {
  today: "Heute",
  depots: "Depot",
  inbox: "Entscheiden",
  proof: "Beweis",
};

const VIEW_KEYS = new Set<string>(NAV.map((item) => item.key));

/** `?view=depots` -> "depots"; anything unknown or absent -> "today".
 *  Deliberately forgiving: a stale Telegram deep link must land somewhere sensible. */
export function parseView(search: string): View {
  const raw = new URLSearchParams(search).get("view");
  return raw && VIEW_KEYS.has(raw) ? (raw as View) : "today";
}
```

- [ ] **Step 4: Rewire `App.tsx`**

Replace `App.tsx` lines 16-57 (the `View`/`Group`/`GROUP_LABELS`/`NAV` declarations) with:

```typescript
import { GROUP_LABELS, NAV, parseView, type View } from "./views";
```

and replace line 98 (`const [view, setView] = useState<View>("today");`) with:

```typescript
  // View lives in the URL so Telegram can deep-link into a focus and a reload keeps it.
  // replaceState (not pushState): the phone's back gesture should leave the app, not walk
  // a tab history the user never built on purpose.
  const [view, setViewState] = useState<View>(() => parseView(window.location.search));
  const setView = useCallback((next: View) => {
    setViewState(next);
    const params = new URLSearchParams(window.location.search);
    params.set("view", next);
    params.delete("token"); // never leave the shared secret in the visible URL
    window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }, []);
```

Add `useCallback` to the existing React import in `App.tsx`.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test`
Expected: PASS (6 tests).

- [ ] **Step 6: Typecheck and build**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: exit 0 for both.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views.ts frontend/src/views.test.ts frontend/src/App.tsx
git commit -m "feat(frontend): drive view state from the URL for deep links"
```

---

### Task 3: Bottom tab bar with the four focuses

**Files:**
- Create: `frontend/src/components/BottomNav.tsx`
- Modify: `frontend/src/App.tsx` (render it)
- Modify: `frontend/src/index.css` (styles)

- [ ] **Step 1: Create the component**

Create `frontend/src/components/BottomNav.tsx`:

```tsx
import { useState } from "react";

import { GROUP_LABELS, MOBILE_FOCUSES, MOBILE_LABELS, NAV, type View } from "../views";

// Emoji as tab glyphs: the dashboard ships no icon set, and a one-dependency icon library
// for four tabs is not worth it. They match the digest's section icons on purpose.
const TAB_ICON: Record<string, string> = {
  today: "🏠",
  depots: "🤖",
  inbox: "📬",
  proof: "🧾",
};

export function BottomNav({
  view,
  onNavigate,
}: {
  view: View;
  onNavigate: (view: View) => void;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const inFocus = MOBILE_FOCUSES.includes(view);
  const rest = NAV.filter((item) => !MOBILE_FOCUSES.includes(item.key));

  return (
    <>
      {sheetOpen && (
        <div className="sheet-backdrop" onClick={() => setSheetOpen(false)}>
          <nav
            className="sheet"
            aria-label="Weitere Ansichten"
            onClick={(event) => event.stopPropagation()}
          >
            {rest.map((item, i) => (
              <div key={item.key}>
                {(i === 0 || rest[i - 1].group !== item.group) &&
                  GROUP_LABELS[item.group] && (
                    <span className="sheet-group">{GROUP_LABELS[item.group]}</span>
                  )}
                <button
                  className={view === item.key ? "sheet-link active" : "sheet-link"}
                  onClick={() => {
                    onNavigate(item.key);
                    setSheetOpen(false);
                  }}
                >
                  {item.label}
                </button>
              </div>
            ))}
          </nav>
        </div>
      )}
      <nav className="bottom-nav" aria-label="Fokus">
        {MOBILE_FOCUSES.map((key) => (
          <button
            key={key}
            className={view === key ? "bottom-tab active" : "bottom-tab"}
            aria-current={view === key ? "page" : undefined}
            onClick={() => onNavigate(key)}
          >
            <span className="bottom-icon" aria-hidden="true">
              {TAB_ICON[key]}
            </span>
            {MOBILE_LABELS[key]}
          </button>
        ))}
        <button
          // "Mehr" reads as active whenever the current view is not one of the four
          // focuses — otherwise a deep link to e.g. Radar shows no active tab at all.
          className={!inFocus ? "bottom-tab active" : "bottom-tab"}
          onClick={() => setSheetOpen((open) => !open)}
        >
          <span className="bottom-icon" aria-hidden="true">
            ⋯
          </span>
          Mehr
        </button>
      </nav>
    </>
  );
}
```

- [ ] **Step 2: Render it in `App.tsx`**

Add the import and place it after `</main>`, inside the fragment but outside `.shell`:

```tsx
import { BottomNav } from "./components/BottomNav";
```

```tsx
      </div>
      <BottomNav view={view} onNavigate={setView} />
    </>
```

- [ ] **Step 3: Add the styles**

Append to `frontend/src/index.css`:

```css
/* ===== Phone focus navigation (2026-08-04) ===== */
/* Desktop keeps the sidebar; the bottom bar exists only on phone widths. */
.bottom-nav {
  display: none;
}

@media (max-width: 720px) {
  .bottom-nav {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    position: fixed;
    inset: auto 0 0 0;
    z-index: 40;
    background: var(--surface, #0d0d16);
    border-top: 1px solid var(--border-soft);
    /* env() keeps the bar clear of the gesture area on phones that have one. */
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  .bottom-tab {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    /* 44 px is the smallest reliably tappable target. */
    min-height: 44px;
    padding: var(--space-2) 0;
    border: 0;
    background: none;
    color: var(--text-muted);
    font-size: 0.68rem;
    letter-spacing: 0.02em;
  }
  .bottom-tab.active {
    color: var(--accent);
  }
  .bottom-icon {
    font-size: 1.15rem;
    line-height: 1;
  }
  /* The fixed bar must not cover the last rows of content. */
  .content {
    padding-bottom: calc(64px + env(safe-area-inset-bottom, 0));
  }
  /* The horizontally scrolling 12-item nav is redundant on phones now. */
  .sidebar .nav,
  .sidebar .nav-group-label,
  .sidebar .nav-sep {
    display: none;
  }
  .sheet-backdrop {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: flex-end;
  }
  .sheet {
    width: 100%;
    max-height: 70vh;
    overflow-y: auto;
    background: var(--surface, #0d0d16);
    border-top: 1px solid var(--border-soft);
    border-radius: 14px 14px 0 0;
    padding: var(--space-3) var(--space-4)
      calc(var(--space-4) + env(safe-area-inset-bottom, 0));
  }
  .sheet-group {
    display: block;
    font-size: 0.68rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: var(--space-3) 0 var(--space-1);
  }
  .sheet-link {
    display: block;
    width: 100%;
    text-align: left;
    min-height: 44px;
    padding: var(--space-2) 0;
    border: 0;
    background: none;
    color: var(--text, #e8e8f0);
    font-size: 0.95rem;
  }
  .sheet-link.active {
    color: var(--accent);
  }
}
```

Before committing, confirm the CSS variables used here exist in `index.css`'s `:root` (`--surface`, `--text`, `--accent`, `--border-soft`, `--space-2/3/4`, `--text-muted`). Fallbacks are supplied for `--surface` and `--text`; if `--surface` does not exist, replace it with whatever the sidebar uses as its background.

- [ ] **Step 4: Verify on a phone viewport**

Run: `cd frontend && npm run dev` — then open the printed localhost URL, set the viewport to 390 × 844 in DevTools, and check: five tabs at the bottom, tapping switches views, the URL gains `?view=…`, "Mehr" opens the sheet with the other eight views, the sheet closes on backdrop tap, and content is not hidden behind the bar. Then widen past 720 px and confirm the sidebar is back and the bottom bar is gone.

- [ ] **Step 5: Typecheck, build, commit**

```bash
cd frontend && npm run typecheck && npm run build
git add frontend/src/components/BottomNav.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "feat(frontend): phone bottom nav with four focuses and a Mehr sheet"
```

---

### Task 4: Service worker — app shell plus stale-while-revalidate

**Files:**
- Create: `frontend/public/sw.js`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Write the service worker**

Create `frontend/public/sw.js` (plain JS, not processed by Vite — `public/` is copied verbatim):

```javascript
// equity-scout cockpit service worker.
//
// Two jobs: (1) the app shell opens instantly and works when WSL is down, (2) API reads
// fall back to the last successful response so the phone shows the last known state
// instead of a blank page. Every cached read is stamped so the UI can label it — a cached
// number without a timestamp is a lie waiting to happen.
//
// Deliberately NOT cached: POSTs (pitch decisions). Offline means an honest error, never a
// queued write that fires later against stale state.
//
// Bump CACHE_VERSION whenever the shell or this file changes; activate() drops the rest.
const CACHE_VERSION = "es-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest"];
const STAMP_HEADER = "x-sw-cached-at";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** Copy a response and stamp it with the time it was stored. */
async function stamped(response) {
  const body = await response.clone().blob();
  const headers = new Headers(response.headers);
  headers.set(STAMP_HEADER, new Date().toISOString());
  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const fresh = await fetch(request);
    // Only success responses are worth keeping — a 500 must not poison the cache.
    if (fresh.ok) await cache.put(request, await stamped(fresh));
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  if (cached) return cached;
  const fresh = await fetch(request);
  if (fresh.ok) await cache.put(request, fresh.clone());
  return fresh;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return; // decisions always hit the network
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  if (request.mode === "navigate") {
    // Navigation must never dead-end on a blank page: shell from cache when offline.
    event.respondWith(
      fetch(request).catch(() => caches.match("/index.html").then((r) => r || Response.error())),
    );
    return;
  }
  // Hashed build assets are immutable — cache-first is safe and makes cold starts fast.
  if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request));
  }
});
```

- [ ] **Step 2: Register it in production builds only**

In `frontend/src/main.tsx`, append after the `createRoot(...)` call:

```tsx
// Production only: a service worker in front of the Vite dev server serves stale modules
// and makes HMR behave in ways that cost more time than the offline test is worth.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // A failed registration is not fatal — the app just stays online-only.
    });
  });
}
```

- [ ] **Step 3: Build and verify registration**

Run: `cd frontend && npm run build && npm run preview`
Open the printed URL, then in DevTools → Application → Service Workers: status "activated". In Cache Storage, `es-v1` holds the shell entries.

- [ ] **Step 4: Verify the offline fallback**

With the preview server running, load the app, then check "Offline" in DevTools → Network and reload.
Expected: the app shell still renders (no browser error page). API panels show the last cached values or their own error state.

- [ ] **Step 5: Commit**

```bash
git add frontend/public/sw.js frontend/src/main.tsx
git commit -m "feat(frontend): service worker for app shell and cached API reads"
```

---

### Task 5: A cheap liveness endpoint for the probe

**Files:**
- Modify: `src/equity_scout/api.py` (next to the other read endpoints, before the `StaticFiles` mount)
- Test: `tests/test_api.py`

Task 6's banner polls every 30 seconds. It must NOT poll a data endpoint: `/api/regime` calls `build_regime`, which fetches SPY/^VIX/^TNX/^IRX through yfinance — a 30-second poll would hammer a rate-limited free feed for a liveness check. So add a dedicated endpoint that touches nothing.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py` (follow the file's existing client fixture/pattern):

```python
def test_health_endpoint_is_cheap_and_answers_ok(client):
    """The phone polls this every 30 s — it must not touch yfinance or the DB."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api.py -k health -v`
Expected: FAIL with 404.

- [ ] **Step 3: Add the endpoint**

In `src/equity_scout/api.py`, next to the other `@app.get` read endpoints:

```python
    @app.get("/api/health")
    def health() -> JSONResponse:
        # Liveness only: the phone cockpit polls this every 30 s to tell live data from
        # service-worker cache. Touches no DB and no feed on purpose — a data endpoint
        # here would mean a yfinance call twice a minute (see /api/regime).
        return JSONResponse({"ok": True})
```

The `DASH_TOKEN` middleware still guards it, which is wanted: an unauthenticated probe should not report the cockpit as reachable.

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_api.py -k health -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/api.py tests/test_api.py
git commit -m "feat(api): add cheap /api/health endpoint for the phone liveness probe"
```

---

### Task 6: Freshness banner — name the last successful contact

**Files:**
- Create: `frontend/src/useFreshness.ts`
- Create: `frontend/src/components/FreshnessBanner.tsx`
- Create: `frontend/src/useFreshness.test.ts`
- Modify: `frontend/src/App.tsx`

The banner answers one question: are these numbers live? It polls `/api/health` (Task 5) with `cache: "no-store"` so the service worker cannot make an offline app look online, and remembers the last success in `localStorage` — no SW header plumbing, no changes to the 25 fetch callsites in `api.ts`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/useFreshness.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { describeFreshness } from "./useFreshness";

describe("describeFreshness", () => {
  it("says nothing while the cockpit answers", () => {
    expect(describeFreshness({ online: true, lastSync: "2026-08-04T16:04:00.000Z" })).toBeNull();
  });

  it("names the last successful contact when offline", () => {
    const text = describeFreshness({
      online: false,
      lastSync: "2026-08-04T16:04:00.000Z",
    });
    // Local time formatting is the browser's job; the label must carry the marker word.
    expect(text).toContain("Stand von");
    expect(text).toContain("Cockpit nicht erreichbar");
  });

  it("admits it has nothing when there was never a successful contact", () => {
    expect(describeFreshness({ online: false, lastSync: null })).toBe(
      "Cockpit nicht erreichbar — keine gespeicherten Daten.",
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './useFreshness'`.

- [ ] **Step 3: Implement the hook and the label**

Create `frontend/src/useFreshness.ts`:

```typescript
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

/** Polls one cheap endpoint so the UI can tell live data from cached data.
 *  `cache: "no-store"` bypasses the service worker on purpose: a cached 200 would
 *  otherwise make an unreachable cockpit look online. */
export function useFreshness(): Freshness {
  const [state, setState] = useState<Freshness>(() => ({
    online: true,
    lastSync: localStorage.getItem(LAST_SYNC_KEY),
  }));

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      try {
        const response = await fetch("/api/health", { cache: "no-store" });
        if (!response.ok) throw new Error(String(response.status));
        const now = new Date().toISOString();
        localStorage.setItem(LAST_SYNC_KEY, now);
        if (!cancelled) setState({ online: true, lastSync: now });
      } catch {
        if (!cancelled) {
          setState({ online: false, lastSync: localStorage.getItem(LAST_SYNC_KEY) });
        }
      }
    };
    probe();
    const timer = window.setInterval(probe, PROBE_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return state;
}
```

Create `frontend/src/components/FreshnessBanner.tsx`:

```tsx
import { describeFreshness, useFreshness } from "../useFreshness";

export function FreshnessBanner() {
  const label = describeFreshness(useFreshness());
  if (!label) return null;
  return (
    <div className="freshness-banner" role="status">
      ⚠️ {label}
    </div>
  );
}
```

- [ ] **Step 4: Render it and style it**

In `App.tsx`, add the import and render it as the first child inside the fragment, before `.aurora`:

```tsx
import { FreshnessBanner } from "./components/FreshnessBanner";
```

```tsx
    <>
      <FreshnessBanner />
      <div className="aurora" aria-hidden="true" />
```

Append to `frontend/src/index.css`:

```css
/* Stale-data warning: sticky at the top on every width — it must never be scrolled past
   and forgotten while the numbers below it are old. */
.freshness-banner {
  position: sticky;
  top: 0;
  z-index: 60;
  padding: var(--space-2) var(--space-4);
  background: #3a2a12;
  color: #ffd9a0;
  font-size: 0.82rem;
  text-align: center;
}
```

- [ ] **Step 5: Run tests, typecheck, build**

Run: `cd frontend && npm test && npm run typecheck && npm run build`
Expected: PASS / exit 0.

- [ ] **Step 6: Verify against a stopped backend**

Run `npm run preview`, load the app (banner absent), stop the FastAPI service, wait up to 30 s.
Expected: the banner appears with a plausible "Stand von HH:MM"; the panels keep showing the cached values.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/useFreshness.ts frontend/src/useFreshness.test.ts \
        frontend/src/components/FreshnessBanner.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "feat(frontend): label cached data with the last successful contact"
```

---

### Task 7: Verify the whole loop and record the outcome

**Files:**
- Modify: `README.md` (phone cockpit section)
- Create: `docs/sessions/2026-08-04_mobile-focus-app-verify.md`

- [ ] **Step 1: Rebuild and restart the service**

```bash
cd frontend && npm run build
cd .. && ./scripts/install_dash_service.sh
```

Then print the URL Nico needs (`DASH_URL`, or the Tailscale hostname on port 8420) so he can open it on the phone.

- [ ] **Step 2: Walk the real deep-link loop on the phone**

1. Open `<DASH_URL>/?token=<DASH_TOKEN>` once — the cookie is set and the token disappears from the URL.
2. "Add to home screen" — confirm it opens standalone (no browser chrome).
3. From the Telegram digest, tap the "🤖 Auto-Depot" head — the app must open directly on the Depot focus.
4. Switch tabs, kill the app, reopen — the last focus is restored from the URL.
5. Decide one pitch under Entscheiden and confirm the decision lands (`/api/inbox/{id}/decision`).
6. Turn WSL off, reopen the app — banner with a timestamp, cached numbers visible.

- [ ] **Step 3: Update the README**

Document in `README.md` under the dashboard section: the four phone focuses, the `?view=` deep-link parameter and its values, the service worker's cache name (`es-v1`) and when to bump it, and the fact that decisions require connectivity.

- [ ] **Step 4: Write the outcome doc**

Create `docs/sessions/2026-08-04_mobile-focus-app-verify.md`: what was built, what the phone walk-through showed, deviations from this plan, and open points.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/sessions/2026-08-04_mobile-focus-app-verify.md
git commit -m "docs: record mobile focus app verification"
```

---

## Deliberately not built

- **No native app.** A PWA on the home screen covers "app on my phone" without a second toolchain; a real store build would need Play Store money and a release pipeline for a single-user cockpit reachable only over Tailscale.
- **No router library.** One query param and `replaceState` cover the whole need; `react-router` would be a dependency and a `StaticFiles` fallback problem for zero benefit.
- **No `vite-plugin-pwa`.** A 60-line hand-written worker is easier to reason about than a plugin's generated manifest injection, and it keeps the dependency count at one.
- **No offline write queue for pitch decisions.** A decision fired later against stale prices is worse than an error message now.
- **No push notifications from the app.** Telegram is already the push channel and works when the cockpit is off — Web Push would need a public endpoint and VAPID keys.

---

## Outcome (2026-08-04)

**Code-komplett und verifiziert, Live-Walk-Through am Handy steht aus (Needs Nico).**

Vier Fokus-Tabs unter 720 px, „Mehr"-Sheet für die restlichen acht Ansichten, View-State
in der URL, Service Worker `es-v1`, Freshness-Banner über den neuen `/api/health`.
11 vitest-Tests grün, `tsc --noEmit` exit 0, Build ok, `dist/sw.js` wird über Tailscale
ausgeliefert. Token-Gate über die Tailscale-Adresse geprüft: 401 ohne, 200 mit Token.

Abweichungen:
- `frontend/src/vite-env.d.ts` ergänzt — erste `import.meta.env`-Nutzung im Projekt,
  `tsc` scheiterte ohne den Vite-Ambient-Typ-Shim.
- Die `/api/*`-Strategie ist Netz-zuerst-mit-Cache-Fallback (wie in Task 4 beschrieben),
  nicht das Lehrbuch-Stale-while-Revalidate, das der Task-Titel nennt.
- Der Dash-Service brauchte einen Restart, damit `/api/health` existiert; das neue
  `dist/` allein hätte keinen gebraucht (StaticFiles liest pro Request).

Details und Walk-Through-Anleitung: `docs/sessions/2026-08-04_telegram-diet-and-mobile-focus-app.md`.
