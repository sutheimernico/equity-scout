# Trading Copilot — Phase 6: Dashboard Redesign (Trading-Terminal Identity)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reskin the whole dashboard into a distinctive dark "trading-terminal" identity and add four new copilot surfaces — **Radar**, **Inbox**, **Arena** (the headline: Du vs. Autopilot vs. Markt), **Model** — on the existing React/Vite/TS stack, no rewrite.

**Architecture:** The lever: every component styles itself through CSS variables in `index.css`'s `:root`, so **rewriting the token block + base rules reskins the entire existing dashboard for free**. Phase 6 = (1) a new dark-terminal token system + shell/nav + responsive breakpoints (reskins Strategien/ML/Screener/Assistent automatically), (2) a typed `api.ts` layer for the four copilot endpoints, (3) four new surface components built in the new style reusing existing primitives (`EquityChart`, `ui/Bar`, `StatTile`, `ui/Metric`, `Badge`, `Chip`, `format.ts`). No backend change — the four endpoints already exist and return live DB data.

**Tech Stack:** React 19, Vite 7, TypeScript 5.8 (strict, `noUnusedLocals/Parameters`), single global `index.css` (no Tailwind/CSS-modules). **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-04-trading-copilot-design.md` (§8)
**Builds on:** Phases 1–4 (`/api/radar`, `/api/inbox` + decision POST, `/api/arena`, `/api/model`).

**Conventions that bind every task:**
- User-facing strings **German** with correct umlauts (ADR 0001); code/comments English.
- No hardcoded colors/spacing in components — use the CSS variables (Task 1 defines them). A component with a raw hex is a review reject.
- Gate before EVERY commit: `cd frontend && npm run typecheck && npm run build` — both clean (tsc strict + vite build). The backend suite must stay green too (`.venv/bin/python -m pytest -q` → 376) but Phase 6 touches no Python, so it should be untouched — verify once at the phase gate.
- Frontend has **no test runner** (no vitest/eslint). The gate is typecheck + build + correct data wiring; visual quality is Nico's sign-off (spec §8). So tasks are NOT TDD — they are build-clean + typecheck-clean + exact-field-mapping.
- Keep the existing `useRevealOnScroll` + `prefers-reduced-motion` handling. Add explicit responsive breakpoints (the app currently only has fluid `auto-fit` grids).
- One commit per task; include plan-doc checkbox edits.
- React idioms (Nico is growing here — keep them clean and conventional): stable `key`s on lists (never index), effect cleanup for any subscription/interval, `useState` lazy-init for derived initial state, no fetching in render (fetch in `useEffect` with an `ignore` flag to avoid setState-after-unmount). Each new component briefly comments any non-obvious pattern in one line.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/index.css` | rewrite `:root` + shell/nav rules; add breakpoints | dark-terminal token system (reskins everything) |
| `frontend/src/api.ts` | modify | add Radar/Inbox/Arena/Model types + fetchers + `decidePitch` |
| `frontend/src/components/RadarPanel.tsx` | create | watchlist: entry-zone bars, proximity, composite, sub-signals |
| `frontend/src/components/InboxPanel.tsx` | create | pitch cards + [Kaufen]/[Ablehnen]/[Später] decision POST |
| `frontend/src/components/ArenaPanel.tsx` | create | Du vs Autopilot vs SPY equity curves, KPIs, positions, trades |
| `frontend/src/components/ModelPanel.tsx` | create | champion metrics, registry, resolved-prediction stats, honesty banner |
| `frontend/src/components/ui/DisclaimerBar.tsx` | create | per-surface German disclaimer strip |
| `frontend/src/App.tsx` | modify | new nav with the copilot surfaces; per-view disclaimer; default = Arena |

Exact endpoint shapes are in the spec recon; each surface task restates the fields it consumes.

---

### Task 1: Dark trading-terminal design system + shell

**Files:** `frontend/src/index.css` (rewrite the `:root` token block + `.topbar`/`.nav`/`.content` shell rules + card/table base; ADD responsive breakpoints), `frontend/src/App.tsx` (only if a class rename is needed — prefer keeping class names so existing components inherit the reskin).

**Design direction (commit to it — this is the identity):** dark, data-dense, restrained motion; sibling to the portfolio's "Kinetic Terminal". Near-black blue-violet base, phosphor-green primary signal, amber attention, tabular mono numerals, hairline borders.

- [x] **Step 1: Rewrite the `:root` token block** in `index.css` (replace the existing light tokens; keep the SAME variable NAMES so every component reskins for free — only add new ones):

```css
:root {
  color-scheme: dark;
  /* surfaces — near-black with a blue-violet tint */
  --bg-base: #08080f;
  --bg-surface: #10101c;
  --bg-inset: #171726;
  --bg-raised: #1c1c2e;
  /* hairline borders */
  --border-faint: rgba(180, 190, 255, 0.06);
  --border-soft: rgba(180, 190, 255, 0.10);
  --border-strong: rgba(180, 190, 255, 0.18);
  /* text */
  --text-strong: #eef0ff;
  --text: #b9bcd6;
  --text-muted: #6f7296;
  /* accents — phosphor terminal */
  --accent: #3ef2a0;          /* primary: brand + positive signal */
  --accent-hover: #5cf7b3;
  --accent-subtle: rgba(62, 242, 160, 0.12);
  --violet: #8b6cff;          /* secondary: brand continuity w/ portfolio */
  --violet-subtle: rgba(139, 108, 255, 0.14);
  --positive: #3ef2a0;
  --negative: #ff5470;
  --warning: #f5b23e;
  /* type */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", "JetBrains Mono", "Fira Code", ui-monospace, Menlo, monospace;
  --text-xs: 0.75rem; --text-sm: 0.875rem; --text-md: 1rem;
  --text-lg: 1.25rem; --text-xl: 1.875rem;
  /* spacing / radii / motion — keep existing scale names */
  --space-1: 4px; --space-2: 8px; --space-3: 16px; --space-4: 24px; --space-5: 32px; --space-6: 40px;
  --radius-sm: 8px; --radius-md: 12px; --radius-lg: 18px; --radius-pill: 9999px;
  --raised: 0 1px 0 rgba(255,255,255,0.03), 0 8px 24px rgba(0,0,0,0.45);
  --raised-hover: 0 1px 0 rgba(255,255,255,0.05), 0 12px 32px rgba(0,0,0,0.55);
  --ease: cubic-bezier(0.22, 1, 0.36, 1); --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-fast: 120ms; --dur-mid: 240ms; --dur-slow: 420ms;
}
body { background: var(--bg-base); color: var(--text); font-family: var(--font-sans); }
.tnum, .num, td.num, .metric-value { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
```

- [x] **Step 2: Restyle the shell** — `.topbar` (sticky, hairline bottom border, brand in mono with a phosphor dot), `.nav`/`.nav-link` (pill tabs; active = `--accent-subtle` bg + `--accent` text; hover lift), `.content`/`.view`, generic `.card`/`.panel` (`--bg-surface`, `--border-soft`, `--raised`), and the `.aurora` (retune to a faint phosphor/violet drift on the dark base, keep `aria-hidden` + reduced-motion). Numbers everywhere use the mono/tnum treatment.

- [x] **Step 3: Add responsive breakpoints** at the bottom of `index.css`:

```css
@media (max-width: 720px) {
  .topbar { flex-direction: column; gap: var(--space-2); align-items: stretch; }
  .nav { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; }
  .content { padding: var(--space-3); }
  /* any multi-col grid collapses to one column */
  [class$="-grid"], .kpi-row { grid-template-columns: 1fr !important; }
}
```

- [x] **Step 4: Gate** — `cd frontend && npm run typecheck && npm run build`. Both clean. The existing four views now render in the dark identity (build succeeds; no component code changed).
- [x] **Step 5: Commit** `feat(ui): dark trading-terminal design system reskinning the dashboard`.

---

### Task 2: Typed API layer for the four surfaces

**Files:** `frontend/src/api.ts` (append; mirror the existing `interface` + `fetchX` pattern exactly).

- [x] **Step 1: Add the types + fetchers** (field names EXACT per the endpoint shapes):

```typescript
// --- Radar ---
export interface SignalReading { name: string; score: number; reason: string; }
export interface WatchlistEntry {
  ticker: string; name: string; bucket: string; price: number;
  entry_zone_low: number; entry_zone_high: number; proximity: number; in_zone: boolean;
  composite: number; readings: SignalReading[]; zone_note: string;
  breakdown: Record<string, number>;
}
export interface Watchlist {
  created_at: string; entries: WatchlistEntry[];
  skipped: Record<string, string>; watchlist_id: number;
}
export interface RadarResponse { watchlist: Watchlist | null; disclaimer: string; }
export const fetchRadar = () => getJSON<RadarResponse>("/api/radar");

// --- Inbox ---
export type PitchStatus = "open" | "buy" | "pass" | "later";
export interface Pitch {
  id: number; created_at: string; ticker: string; watchlist_id: number; price: number;
  composite: number; zone_low: number; zone_high: number; pitch: string;
  status: PitchStatus; decided_at: string | null; telegram_message_id: number | null;
}
export interface InboxResponse { pitches: Pitch[]; disclaimer: string; }
export const fetchInbox = () => getJSON<InboxResponse>("/api/inbox");
export interface DecisionResponse { ok?: boolean; pitch?: Pitch; error?: string; disclaimer: string; }
export async function decidePitch(id: number, action: "buy" | "pass" | "later"): Promise<DecisionResponse> {
  const r = await fetch(`/api/inbox/${id}/decision`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return r.json(); // 200/409/422 all carry a JSON body
}

// --- Arena ---
export interface LanePosition {
  ticker: string; name: string; shares: number; cost_basis: number;
  last_price: number | null; opened_at: string;
}
export interface LaneTrade {
  id: number; created_at: string; lane: string; ticker: string; side: string;
  shares: number; fill_price: number; cost: number; reason: string; pitch_id: number | null;
}
export interface Lane {
  lane: string; initial_capital: number; total_value: number; total_return: number;
  benchmark_return: number; open_positions: LanePosition[];
  equity_curve: [string, number, number][]; trades: LaneTrade[];
}
export interface ArenaResponse { available: boolean; lanes: Lane[]; disclaimer: string; }
export const fetchArena = () => getJSON<ArenaResponse>("/api/arena");

// --- Model ---
export interface RegistryEntry {
  version: number; created_at: string; model_kind: string; n_train: number;
  metrics: Record<string, number | null>; is_champion: boolean;
}
export interface ResolvedStats {
  n_resolved: number; n_open: number; hit_rate: number | null; rank_ic: number | null;
  by_score_bucket: Record<string, number>;
}
export interface ModelResponse {
  available: boolean;
  champion: { version: number; created_at: string; model_kind: string; metrics: Record<string, number | null> } | null;
  registry: RegistryEntry[]; resolved: ResolvedStats; drift: null; disclaimer: string;
}
export const fetchModel = () => getJSON<ModelResponse>("/api/model");
```

If the file has no shared `getJSON` helper, either add one (`async function getJSON<T>(url): Promise<T> { const r = await fetch(url); if (!r.ok) throw new Error(`${url} → ${r.status}`); return r.json(); }`) or follow the existing per-endpoint inline pattern — match whatever `api.ts` already does.

- [x] **Step 2: Gate** `cd frontend && npm run typecheck` (no build needed; nothing consumes these yet — tsc `noUnusedLocals` may flag unused fetchers, so if it errors, this task commits together with Task 3's first consumer OR mark the fetchers used via a re-export; simplest: land Task 2 + Task 3 in sequence and only gate-build after Task 3). Pragmatic: run `npm run typecheck` to confirm types are well-formed; if `noUnusedLocals` blocks, proceed to Task 3 before the build gate and commit both once green.
- [x] **Step 3: Commit** `feat(ui): add typed api layer for radar/inbox/arena/model`.

---

### Task 3: Radar surface

**Files:** `frontend/src/components/RadarPanel.tsx`.

Consumes `RadarResponse`. Layout: a header (created_at, count, disclaimer) + a data-dense table/card-grid of `entries` (already sorted best-composite-first). Per entry: ticker + name + bucket chip; a **composite meter** (0–100 = `composite*100`) using `ui/Bar`; the **entry zone** as a small track showing `entry_zone_low`–`entry_zone_high` with the current `price` marked and `in_zone` highlighted in `--accent`; `proximity` as a signed % (`format.pct`); the three `readings` as labelled sub-scores (dip_quality/value_gap/momentum → German labels "Dip-Qualität"/"Bewertungslücke"/"Momentum") with their `reason` in a `Disclosure`/tooltip; `zone_note` shown. `skipped` listed compactly below ("übersprungen: TICKER — Grund"). Empty (`watchlist === null`) → an honest German empty state ("Noch keine Watchlist — `run_radar.py` ausführen.").

- [x] **Step 1: Build the component** (fetch in `useEffect` with an `ignore` flag; loading/error/empty states; German labels; `role="img"`+`aria-label` on any SVG/meter; numbers in `.tnum`). Reuse `ui/Bar`, `Chip`, `Disclosure`, `format.pct`/`num`/`eur`. Component + dedicated CSS block in `index.css` (matches every existing panel's style; tokens only).
- [ ] **Step 2: Gate** typecheck + build — `npm run typecheck` clean. **App-wiring (nav entry + mount) + the `npm run build` gate are deferred to Task 7** to avoid repeated App edits; the component is exported and will build-render there.
- [x] **Step 3: Commit** `feat(ui): add radar surface (watchlist, entry zones, sub-signals)`.

---

### Task 4: Inbox surface

**Files:** `frontend/src/components/InboxPanel.tsx`.

Consumes `InboxResponse`; POSTs via `decidePitch`. Open pitches first (the API already orders open-first). Each pitch: ticker, score (`composite*100`), price, zone, created_at, the `pitch` text (pre-rendered German, may be multi-line — render with preserved line breaks), and for `status === "open"` three buttons **[Kaufen] [Ablehnen] [Später]** calling `decidePitch(id, "buy"|"pass"|"later")`. On success (`ok`), update that pitch's status/decided_at in local state (optimistic-then-confirm: disable buttons while the request is in flight; on 409 refetch the inbox — someone/the receiver already decided it; on 422 show a small error). Decided pitches show the outcome as a `Badge` (grün=gekauft/rot=abgelehnt/grau=später) with `decided_at`.

- [x] **Step 1: Build the component** (in-flight state per pitch id via a `Set<number>`; a `decide(id, action)` handler that awaits `decidePitch`, then updates state or refetches on 409; disable all three buttons for that pitch while pending; keyboard-accessible buttons). German throughout. Component + dedicated CSS block in `index.css` (tokens only; buy CTA uses dark `var(--bg-base)` text on the light accent fill). **Also:** `decidePitch` now returns the HTTP `status` (added `status: number` to `DecisionResponse`, `disclaimer` made optional) — the given return shape could not distinguish 200/409/422 otherwise; this is the minimal correct change to implement the 409-refetch vs 422-inline split.
- [ ] **Step 2: Gate** typecheck + build — `npm run typecheck` clean. **App-wiring (nav entry + mount) + the `npm run build` gate are deferred to Task 7** to avoid repeated App edits; the component is exported and will build-render there.
- [x] **Step 3: Commit** `feat(ui): add decision inbox surface with one-tap buy/pass/later`.

---

### Task 5: Arena surface (the headline)

**Files:** `frontend/src/components/ArenaPanel.tsx`.

Consumes `ArenaResponse`. This is the showpiece — "Du vs. Autopilot vs. Markt". Top: a KPI row of `StatTile`s per lane (total_value as `format.eur`, total_return and benchmark_return as signed %, open position count). Center: an **equity-curve chart** overlaying both lanes + SPY. Reuse/extend `EquityChart` — it already draws a primary line + a dashed benchmark from `[date,value][]`; here you need THREE series (nico, autopilot, benchmark). Either render two `EquityChart`s (each lane vs its SPY) side by side, OR extend EquityChart to accept an array of named series with per-series color from tokens (`--accent` autopilot, `--violet` nico, `--text-muted` dashed SPY) — prefer the multi-series extension if clean, else two charts with a shared legend. Map each lane's `equity_curve` `[valued_on, total_value, benchmark_value]` → the series. Below: per lane, `open_positions` (ticker/shares/cost_basis/last_price/unrealized %) and recent `trades` (side/ticker/shares/fill_price/reason, buy=grün sell=rot). `available === false` → German empty state ("Arena noch leer — `run_lanes.py` ausführen.").

- [x] **Step 1: Build the component** + any `EquityChart` multi-series extension (keep the existing single-series callers working — add an optional `series?: {label,points,color,dashed}[]` prop that, when present, supersedes the primary/benchmark props; document the back-compat). Colors from tokens only. SVG `aria-label` describing the comparison. `format.eur`/`pct`/`maxDrawdown`.
- [ ] **Step 2: Gate** typecheck + build — `npm run typecheck` clean (whole project, so the EquityChart extension is confirmed back-compatible with all four existing single-series callers). **App-wiring (Arena nav entry + mount + default view) + the `npm run build` gate are deferred to Task 7** to avoid repeated App edits; the component is exported and will build-render there.
- [x] **Step 3: Commit** `feat(ui): add arena surface — Du vs Autopilot vs Markt equity race`.

---

### Task 6: Model surface

**Files:** `frontend/src/components/ModelPanel.tsx`.

Consumes `ModelResponse`. An honesty-forward panel. Top: a prominent German banner — "Der Score bewertet die Einstiegs-Attraktivität (Out-of-Sample), ist keine Prognose und keine Anlageberatung." Champion card: version, model_kind, created_at, and the OOS `metrics` (AUC/Brier/Rank-IC — label AUC "Trefferwahrscheinlichkeit (AUC, OOS)", show `null` metrics honestly as "—" not a fake number). Registry: a compact table of `registry` versions (version, created_at, model_kind, n_train, key metric, champion flag as a `Badge`). Resolved-prediction stats: `n_resolved`/`n_open`, `hit_rate` (or "noch keine aufgelösten Vorhersagen" when `n_resolved === 0`), `rank_ic`, and `by_score_bucket` as a small bar set (mean realized relative return per score bucket — the honest "does a higher score actually pay off" view; positive green / negative red). `drift` is null in v1 → omit or show "—". `available === false` → "Noch kein Modell trainiert — `run_train_entry.py` ausführen."

- [x] **Step 1: Build the component** (null-safe metric rendering — never fabricate a number for `null`; `by_score_bucket` may be empty → honest empty note). Reuse `ui/Metric`, `ui/Bar`, `Badge`, `format`.
- [ ] **Step 2: Gate** typecheck + build — `npm run typecheck` clean. **App-wiring (Model nav entry + mount) + the `npm run build` gate are deferred to Task 7** to avoid repeated App edits; the component is exported and will build-render there.
- [x] **Step 3: Commit** `feat(ui): add model surface (champion, registry, resolved-prediction honesty)`.

---

### Task 7: App shell integration + per-view disclaimer + phase gate

**Files:** `frontend/src/App.tsx`, `frontend/src/components/ui/DisclaimerBar.tsx`.

- [ ] **Step 1: `DisclaimerBar`** — a small component taking the `disclaimer` string from any surface response and rendering it as a subtle footer strip (`--text-muted`, hairline top border). Each surface renders it from its own response (they all carry `disclaimer`).
- [ ] **Step 2: Nav integration** — extend the `View` union + `NAV` array so the copilot surfaces lead: **Arena** (default), **Radar**, **Inbox**, **Model**, then the existing **Strategien / ML / Screener / Assistent**. German labels. Confirm each mounts its panel; the `key={view}` reveal still fires. Group the copilot four visually distinct from the research four if cheap (a divider/label), else a flat tab strip is fine.
- [ ] **Step 3: Full gate** — `cd frontend && npm run typecheck && npm run build` (clean), and `.venv/bin/python -m pytest -q` (still 376 — no backend change) + `.venv/bin/ruff check .`.
- [ ] **Step 4: Serve smoke (no visual judgment, just liveness)** — build, then `.venv/bin/python scripts/run_api.py --db equity_scout.db` briefly and `curl -s localhost:8000/ | grep -c '<div id="root"'` (or TestClient GET "/") to confirm the built dashboard serves and the four `/api/*` return 200. Record. (The live DB has a watchlist, pitches, arena lanes, and a champion model from earlier phases, so all four surfaces have real data to render.)
- [ ] **Step 5: README + outcome + log** — add a short "Dashboard" paragraph to the README copilot section (five surfaces, dark terminal, `npm run build` + serve); append the outcome section to THIS plan (what shipped, the EXplicit note that visual sign-off is Nico's per spec §8, the responsive/a11y state, and any deferrals); append one `AUTOPILOT_LOG.md` line. Commit `docs: record phase-6 dashboard outcome`.

---

## Self-review notes (spec coverage)

- Spec §8 distinctive trading-terminal identity: Task 1 (dark tokens reskin the whole app via CSS-var indirection).
- Spec §8 four surfaces Radar/Inbox/Arena/Model: Tasks 3–6; Arena is the headline + default view.
- Spec §8 sibling to portfolio "Kinetic Terminal": dark base + `--violet` continuity + phosphor accent + mono numerals.
- Spec §8 public deployment shows aggregated data only: the surfaces render whatever the API returns; the API already exposes only aggregate/watchlist/lane data (personal decisions live in the local DB but the inbox surface is for Nico's own local instance — note in the outcome that a public deploy would point at a sanitized DB, same as the existing dashboard's stance).
- Spec §8 visual sign-off is Nico's: the phase gate does liveness only; the look is explicitly handed to Nico.
- Honesty: Model surface never fabricates a number for a `null` metric; the score is framed as OOS-rank-not-forecast; every surface carries its DISCLAIMER via `DisclaimerBar`.
- Deliberate cuts: no dark/light toggle (committed single dark identity per spec); `drift` panel omitted (null in v1); no new charting dependency (extend `EquityChart`); TradingView embed (`StockChart`) untouched and not used by the new surfaces.
- No-test-runner reality: the gate is `tsc --noEmit` + `vite build` + data-shape correctness; visual/UX quality is Nico's review, not automatable here.
