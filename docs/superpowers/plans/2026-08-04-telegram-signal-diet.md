# Telegram Signal Diet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the three Telegram surfaces (daily digest, nightly Auto-Depot push, pitch captions) from full reports into short signals — measured target: digest from 55 lines / 2.313 chars down to ≤ 16 lines, caption from up to 980 chars down to ≤ 4 lines — without losing any information that is not visible elsewhere.

**Architecture:** Three message classes replace "everything, every day": LOUD (action needed / malfunction — its own message), QUIET (one daily head, 1× per day), NEVER (reference material — dashboard only). The digest keeps its single `build_digest` renderer (no compact/full split: `SMTP_*` is unconfigured, so Telegram is the only consumer besides stdout); depth moves behind deep links into the phone cockpit (`DASH_URL/?view=…`, one tap) instead of being inlined. The nightly Auto-Depot push gains a materiality threshold so 12 rebalances of ~60 USD stop producing 12 lines.

**Tech Stack:** Python 3.13, stdlib only for the Telegram transport (`src/equity_scout/telegram_client.py`), pytest. Telegram HTML (`parse_mode="HTML"`), where `<a href>` is allowed and every dynamic value must pass `escape_html`.

---

## Binding principles for every task

1. **Never delete what is not visible elsewhere.** Checked on 2026-08-04: the measured evidence hit-rates (`stats_by_source`) are rendered by NO frontend component — `frontend/src/api.ts:950` only declares the type. The earnings calendar has no API endpoint at all. Both therefore get condensed to one line, not removed. The Auto-Depot / Arena detail blocks DO have dashboard equivalents (`/api/autodepot`, `/api/shortterm`, `DepotsView.tsx`) and may shrink to a headline.
2. **One `<b>` pair and one `<a>` pair per line.** `telegram_client.split_message` cuts at line boundaries; a tag spanning lines can be severed (see its docstring).
3. **Escape every dynamic value**, URLs included — a raw `&` in a URL breaks HTML parsing.
4. **Honest absence beats a padded line.** Where a value is missing, say so; never invent a number.
5. **Traffic-light emoji (🟢🟡🔴) mean state only.** One section icon per block, nothing decorative on top.

## File Structure

| File | Responsibility after this plan |
|---|---|
| `src/equity_scout/digest.py` | `build_digest` renders the ≤ 16-line daily head; new `_link` helper turns section heads into cockpit deep links; `build_proof_report` unchanged |
| `scripts/run_digest.py` | passes `dash_url` into `build_digest`; drops the weekly `DASH_URL` hint line (every section head links now) |
| `scripts/run_autotrader.py` | `build_event_message` applies the materiality threshold; new `MATERIAL_DELTA_WEIGHT` constant |
| `src/equity_scout/pitch.py` | `build_pitch_caption` renders 4 lines; the dropped depth stays reachable via `build_pitch(html=True)` behind the existing "🔎 Details" button |
| `tests/test_digest.py` | adjusted assertions + new tests for the condensed sections and deep links |
| `tests/test_autotrader_events.py` | new: materiality threshold tests |
| `tests/test_pitch.py` | adjusted caption assertions |

---

### Task 1: Auto-Depot block — 7 lines to 3

**Files:**
- Modify: `src/equity_scout/digest.py:128-179`
- Test: `tests/test_digest.py`

Current render (measured 2026-08-04):

```
🤖 Auto-Depot (Stand 2026-08-03): 100,020 USD (86,878 EUR)
  🔴 Heute: -1,073 $ (-1.06 %)
  Gesamt +0.0 % vs SPY +1.2 % · Exposure 59 % · Drawdown 1.1 %
  Trades (Fill: next-open): ↓AIRT ↓BIL ↓GLD ↓IEF ↓MU · +7 weitere
  ⚠ Einzeltitel-Limit 10% griff bei: SPY, VEU
  (Anker-Phase: Sleeves gleichgewichtet — noch zu wenig Forward-Historie für einen Performance-Tilt)
```

Target render: headline with the day move folded in, one context line, trades summarised by materiality, risk events kept (they are LOUD content). Exposure/Drawdown/Anker-Phase move to the dashboard (`DepotsView.tsx` shows them).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_digest.py`:

```python
AUTODEPOT = {
    "as_of": "2026-08-03", "equity": 100020.0, "equity_eur": 86878.0,
    "day_pnl": -1073.0, "day_return": -0.0106, "total_return": 0.0004,
    "benchmark_return": 0.012, "gross_exposure": 0.59, "drawdown": 0.011,
    "breaker_stage": 0, "mode": "anchor",
    "trades": [
        {"ticker": "MU", "delta_weight": -0.041},
        {"ticker": "AIRT", "delta_weight": -0.0006},
        {"ticker": "BIL", "delta_weight": -0.0006},
    ],
    "risk_events": ["Einzeltitel-Limit 10% griff bei: SPY, VEU"],
}


def test_autodepot_headline_folds_in_the_day_move():
    """One line for what the depot is worth and what it did today — not two."""
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "🤖 Auto-Depot 100.020 $ (86.878 €) · 🔴 heute −1,1 %" in text


def test_autodepot_context_line_keeps_only_total_vs_benchmark():
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "  Gesamt +0,0 % vs SPY +1,2 %" in text
    assert "Exposure" not in text  # dashboard: DepotsView
    assert "Drawdown" not in text
    assert "Anker-Phase" not in text


def test_autodepot_trades_summarise_immaterial_moves():
    """12 rebalances of 60 $ must not become 12 lines: name the material ones,
    count the rest."""
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "  Trades: ↓MU 4,1 % · +2 kleine" in text


def test_autodepot_risk_events_stay_visible():
    """Risk interventions are LOUD content — they never get summarised away."""
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "  ⚠ Einzeltitel-Limit 10% griff bei: SPY, VEU" in text


def test_autodepot_breaker_stage_still_reported():
    """A gripping breaker is the one detail that must survive the diet."""
    text = build_digest(
        [], date_label="2026-08-04", autodepot={**AUTODEPOT, "breaker_stage": 2}
    )
    assert "⛔ Drawdown-Breaker aktiv: komplett Cash" in text


def test_autodepot_stale_stand_is_flagged():
    text = build_digest(
        [], date_label="2026-08-04", autodepot={**AUTODEPOT, "stale_days": 3}
    )
    assert "⚠️ Stand 3 Handelstage alt" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_digest.py -k autodepot -v`
Expected: FAIL — the current renderer produces `🤖 Auto-Depot (Stand 2026-08-03): 100,020 USD …` and separate `🔴 Heute:` / `Exposure` lines.

- [ ] **Step 3: Add the German number formatter**

German digit grouping (`100.020`, `−1,1 %`) is what makes these lines readable on a phone; Python's `,`/`.` defaults are English. Add near the top of `src/equity_scout/digest.py`, after the `_VERDICT_ORDER` block:

```python
# German number rendering: thousands dot, decimal comma, U+2212 minus for negatives.
# Telegram shows these lines next to German prose, so English 1,234.5 reads as a typo.
# PUBLIC (no underscore) because scripts/run_autotrader.py formats the same figures in
# Task 5 — one formatter, so the two Telegram surfaces cannot drift.
def format_de(value: float, digits: int = 0) -> str:
    formatted = f"{abs(value):,.{digits}f}".replace(",", " ").replace(".", ",")
    formatted = formatted.replace(" ", ".")
    return f"−{formatted}" if value < 0 else formatted


def format_de_pct(value: float, digits: int = 1) -> str:
    """Signed percent from a RATIO (0.012 -> '+1,2 %')."""
    sign = "+" if value >= 0 else "−"
    return f"{sign}{format_de(abs(value) * 100, digits)} %"
```

- [ ] **Step 4: Replace the Auto-Depot block**

In `src/equity_scout/digest.py`, replace the whole `if autodepot is not None:` block (lines 128-179) with:

```python
    if autodepot is not None:
        eur = (
            f" ({format_de(autodepot['equity_eur'])} €)"
            if autodepot.get("equity_eur") is not None
            else ""
        )
        day = ""
        if autodepot.get("day_pnl") is not None:
            emoji = "🟢" if autodepot["day_pnl"] >= 0 else "🔴"
            # The day RETURN carries the meaning; the absolute P&L is one tap away in
            # the cockpit. Falls back to the absolute figure when no return was stored.
            move = (
                format_de_pct(autodepot["day_return"])
                if autodepot.get("day_return") is not None
                else f"{format_de(autodepot['day_pnl'])} $"
            )
            day = f" · {emoji} heute {move}"
        lines.append(_link(
            f"🤖 Auto-Depot {format_de(autodepot['equity'])} ${eur}{day}", "depots"
        ))
        if autodepot.get("stale_days"):
            lines.append(_line(
                f"  ⚠️ Stand {autodepot['stale_days']} Handelstage alt — Kette prüfen"
            ))
        lines.append(_line(
            f"  Gesamt {format_de_pct(autodepot['total_return'])}"
            f" vs SPY {format_de_pct(autodepot['benchmark_return'])}"
        ))
        lines.append(_line(f"  {_trade_summary(autodepot.get('trades') or [])}"))
        for detail in autodepot.get("risk_events") or []:
            lines.append(_line(f"  ⚠ {detail}"))
        stage_note = {1: "Drawdown-Breaker aktiv: halbes Exposure",
                      2: "Drawdown-Breaker aktiv: komplett Cash"}
        stage = autodepot.get("breaker_stage", 0)
        if stage in stage_note:
            lines.append(_line(f"  ⛔ {stage_note[stage]}"))
```

`_link` arrives in Task 4; until then add this temporary shim right above `build_digest` so Tasks 1-3 stay runnable, and DELETE it in Task 4 Step 3:

```python
def _link_shim(text: str, view: str) -> str:  # replaced by build_digest's _link in Task 4
    return text
```

and inside `build_digest`, next to the existing `_head` / `_line` helpers:

```python
    def _link(text: str, view: str) -> str:  # noqa: ARG001 - view used from Task 4 on
        return _head(text)
```

- [ ] **Step 5: Add the trade summariser**

Add above `build_digest` in `src/equity_scout/digest.py`:

```python
# A rebalance that moves less than 1 % of the book is bookkeeping, not news: the nightly
# advance routinely produces a dozen of them (12 trades, largest ~60 USD, on 2026-08-03).
# Name the material ones, count the rest — the full list lives in the cockpit.
MATERIAL_DELTA_WEIGHT = 0.01
TRADE_NAME_CAP = 3


def _trade_summary(trades: list[dict]) -> str:
    """'Trades: ↓MU 4,1 % · +2 kleine' — or an honest 'Keine Trades'."""
    if not trades:
        return "Keine Trades an diesem Stand."
    material = sorted(
        (t for t in trades if abs(t["delta_weight"]) >= MATERIAL_DELTA_WEIGHT),
        key=lambda t: abs(t["delta_weight"]), reverse=True,
    )
    named = [
        f"{'↑' if t['delta_weight'] > 0 else '↓'}{t['ticker']}"
        f" {format_de(abs(t['delta_weight']) * 100, 1)} %"
        for t in material[:TRADE_NAME_CAP]
    ]
    rest = len(trades) - len(named)
    parts = named or []
    if rest > 0:
        parts.append(f"+{rest} kleine")
    return "Trades: " + " · ".join(parts)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_digest.py -k autodepot -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add src/equity_scout/digest.py tests/test_digest.py
git commit -m "feat(digest): condense Auto-Depot block to three lines with material trades"
```

---

### Task 2: Arena block — 8 lines to 1 (plus malfunctions)

**Files:**
- Modify: `src/equity_scout/digest.py:180-220`
- Test: `tests/test_digest.py`

Current render: one label line plus one Prüfstand line PER lane (3 lanes = 6 lines) plus a total. The Prüfstand counters (`1/30 Trades · 15/60 Tage · PF ∞`) change by single digits per day — that is a dashboard table, not a signal. What IS a signal: a lane with no data (a broken feed) and a lane that just passed its test bench.

- [ ] **Step 1: Write the failing tests**

```python
SHORTTERM = [
    {"lane": "event", "label": "Event-Swing", "day_pnl": 0.0, "total_return": 0.005,
     "benchmark_ticker": "SPY", "benchmark_return": 0.022, "trades_today": 0,
     "promotion": {"realized_trades": 1, "days_active": 15, "profit_factor": None,
                   "eligible": False}},
    {"lane": "intraday", "label": "Intraday-Session", "day_pnl": 0.0,
     "total_return": -0.018, "stale_days": 7,
     "promotion": {"realized_trades": 10, "days_active": 15, "profit_factor": 0.22,
                   "eligible": False}},
    {"lane": "crypto", "label": "Crypto", "day_pnl": 0.0, "total_return": 0.0,
     "benchmark_ticker": "BTC-USD", "benchmark_return": -0.024,
     "promotion": {"realized_trades": 0, "days_active": 15, "profit_factor": None,
                   "eligible": False}},
]


def test_arena_renders_one_summary_line():
    text = build_digest([], date_label="2026-08-04", shortterm=SHORTTERM)
    assert "⚡ Arena 3 Lanes · beste Event-Swing +0,5 % · heute ±0 $" in text
    assert "Prüfstand" not in text  # per-lane counters live in the cockpit


def test_arena_reports_a_stale_lane_because_that_is_a_malfunction():
    text = build_digest([], date_label="2026-08-04", shortterm=SHORTTERM)
    assert "  ⚠ Intraday-Session: 7 Tage keine Daten" in text


def test_arena_announces_a_lane_that_passed_its_test_bench():
    lanes = [{**SHORTTERM[0], "promotion": {**SHORTTERM[0]["promotion"], "eligible": True}}]
    text = build_digest([], date_label="2026-08-04", shortterm=lanes)
    assert "  ✅ Event-Swing hat den Prüfstand bestanden" in text


def test_arena_marks_a_promoted_lane():
    lanes = [{**SHORTTERM[0], "promoted": True}]
    text = build_digest([], date_label="2026-08-04", shortterm=lanes)
    assert "  🎓 Event-Swing verdient jetzt Depot-Kapital" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_digest.py -k arena -v`
Expected: FAIL — current output is `⚡ Kurzfrist-Arena:` plus per-lane lines.

- [ ] **Step 3: Replace the Arena block**

Replace the whole `if shortterm:` block (lines 180-220) with:

```python
    if shortterm:
        best = max(shortterm, key=lambda lane: lane["total_return"])
        day_values = [
            lane["day_pnl"] for lane in shortterm if lane.get("day_pnl") is not None
        ]
        day_note = ""
        if day_values:
            total_day = sum(day_values)
            # "±0 $" instead of "🟢 +0 $": a zero day is not a green day.
            day_note = (
                " · heute ±0 $" if total_day == 0
                else f" · heute {format_de(total_day)} $"
            )
        lines.append(_link(
            f"⚡ Arena {len(shortterm)} Lanes · beste {best['label']}"
            f" {format_de_pct(best['total_return'])}{day_note}",
            "depots",
        ))
        # Only malfunctions and state CHANGES get their own line — a lane grinding
        # through its test bench does not.
        for lane in shortterm:
            if lane.get("stale_days"):
                lines.append(_line(
                    f"  ⚠ {lane['label']}: {lane['stale_days']} Tage keine Daten"
                ))
            if lane.get("promoted"):
                lines.append(_line(f"  🎓 {lane['label']} verdient jetzt Depot-Kapital"))
            elif (lane.get("promotion") or {}).get("eligible"):
                lines.append(_line(
                    f"  ✅ {lane['label']} hat den Prüfstand bestanden"
                    " — Aufnahme beim nächsten Nightly-Lauf"
                ))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_digest.py -k arena -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/digest.py tests/test_digest.py
git commit -m "feat(digest): reduce Arena block to one line plus malfunctions"
```

---

### Task 3: Chances, pitches, earnings, evidence — 4 sections to 4 lines

**Files:**
- Modify: `src/equity_scout/digest.py:222-313`
- Test: `tests/test_digest.py`

Four changes, one task because they share the tail of `build_digest`:

1. **Chances:** a red verdict is not a chance. Show green/yellow only, on ONE line; when none qualify, say so.
2. **Open pitches:** the same six names with identical `verdict_why` have been repeating since 2026-07-16. One count line plus the NEW ones (`created_at >= decided_since`).
3. **Earnings:** 11 lines to one — today's tickers named, the rest counted.
4. **Evidence hit-rates:** 5 lines to one. Not deletable (rendered nowhere in the frontend, checked 2026-08-04), so it condenses to resolved-vs-open plus the best measured source once anything resolves.

- [ ] **Step 1: Write the failing tests**

```python
def test_chances_render_one_line_without_red_verdicts():
    """A red verdict is not a chance — the line names only what the model likes."""
    opportunities = [
        {"ticker": "GOOD", "composite": 0.75, "in_zone": True,
         "breakdown": {"value": 0.9, "quality": 0.8, "momentum": 0.7, "growth": 0.6},
         "readings": [{"reason": "solide", "score": 0.6}]},
        {"ticker": "BAD", "composite": 0.30, "in_zone": True,
         "breakdown": {"value": 0.2, "quality": 0.1, "momentum": 0.1, "growth": 0.1},
         "readings": [{"reason": "schwach", "score": 0.05}]},
    ]
    text = build_digest([], date_label="2026-08-04", opportunities=opportunities)
    assert "🎯 Chancen: GOOD 75" in text
    assert "BAD" not in text


def test_chances_say_so_when_nothing_qualifies():
    opportunities = [
        {"ticker": "BAD", "composite": 0.30, "in_zone": True,
         "breakdown": {"value": 0.2, "quality": 0.1, "momentum": 0.1, "growth": 0.1},
         "readings": [{"reason": "schwach", "score": 0.05}]},
    ]
    text = build_digest([], date_label="2026-08-04", opportunities=opportunities)
    assert "🎯 Keine attraktive Chance heute — Nichtstun ist die richtige Aktion." in text


def test_open_pitches_collapse_to_a_count_and_the_new_ones():
    """Repeating yesterday's list every day is noise; only new pitches earn a line."""
    pitches = [
        {"id": 1, "ticker": "NEW", "status": "open", "composite": 0.6, "price": 10.0,
         "created_at": "2026-08-04T10:00:00+00:00", "decided_at": None,
         "verdict": "green", "verdict_why": "starke Signale"},
        {"id": 2, "ticker": "OLD", "status": "open", "composite": 0.5, "price": 20.0,
         "created_at": "2026-07-16T10:00:00+00:00", "decided_at": None,
         "verdict": "yellow", "verdict_why": "gemischt"},
    ]
    text = build_digest(
        pitches, date_label="2026-08-04", decided_since="2026-08-03T18:00:00+00:00"
    )
    assert "📬 2 Pitches offen · 1 neu" in text
    assert "  🟢 NEW · 60/100 · 10.00" in text
    assert "OLD" not in text  # unchanged since 2026-07-16 — cockpit, not phone


def test_open_pitches_without_new_ones_stay_a_single_line():
    pitches = [
        {"id": 2, "ticker": "OLD", "status": "open", "composite": 0.5, "price": 20.0,
         "created_at": "2026-07-16T10:00:00+00:00", "decided_at": None,
         "verdict": "yellow", "verdict_why": "gemischt"},
    ]
    text = build_digest(
        pitches, date_label="2026-08-04", decided_since="2026-08-03T18:00:00+00:00"
    )
    assert "📬 1 Pitch offen · nichts neu" in text
    assert "OLD" not in text


def test_earnings_collapse_to_one_line_naming_today():
    earnings = [
        {"ticker": "CAT", "earnings_date": "2026-08-04"},
        {"ticker": "SHIP", "earnings_date": "2026-08-04"},
        {"ticker": "INSW", "earnings_date": "2026-08-05"},
    ]
    text = build_digest([], date_label="2026-08-04", earnings_this_week=earnings)
    assert "📅 Earnings heute: CAT, SHIP · 1 weitere diese Woche" in text


def test_earnings_line_without_any_today():
    earnings = [{"ticker": "INSW", "earnings_date": "2026-08-05"}]
    text = build_digest([], date_label="2026-08-04", earnings_this_week=earnings)
    assert "📅 Earnings: heute keine · 1 diese Woche" in text


def test_evidence_collapses_to_one_line_while_nothing_is_resolved():
    stats = {
        "congress": {"n_resolved": 0, "n_open": 880, "hit_rate": 0.0,
                     "mean_relative_return": 0.0},
        "news_theme": {"n_resolved": 0, "n_open": 160, "hit_rate": 0.0,
                       "mean_relative_return": 0.0},
    }
    text = build_digest([], date_label="2026-08-04", evidence_stats=stats)
    assert "🔬 Evidenz: 1.040 offen, noch keine Auflösung" in text
    assert "Trefferquote" not in text


def test_evidence_line_names_the_best_measured_source_once_resolved():
    stats = {
        "congress": {"n_resolved": 12, "n_open": 880, "hit_rate": 0.58,
                     "mean_relative_return": 0.021},
        "news_theme": {"n_resolved": 4, "n_open": 160, "hit_rate": 0.25,
                       "mean_relative_return": -0.01},
    }
    text = build_digest([], date_label="2026-08-04", evidence_stats=stats)
    assert "🔬 Evidenz: 16 aufgelöst · beste Quelle Kongress-Käufe 58 %" in text


def test_below_threshold_count_no_longer_appears():
    """A daily 'N names sat under the gate' count is dashboard bookkeeping."""
    text = build_digest([], date_label="2026-08-04", below_threshold=26)
    assert "Qualitätsschwelle" not in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_digest.py -k "chances or open_pitches or earnings or evidence or below_threshold" -v`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Replace the tail of `build_digest`**

Replace everything from `if opportunities:` (line 235) through the `if evidence_stats:` block's end (line 313) with:

```python
    if opportunities:
        attractive = []
        for entry in opportunities:
            try:
                verdict = compute_verdict(entry)
            except KeyError:
                # Minimal/pre-v8 watchlist entries lack "breakdown" — skip the entry
                # instead of crashing the digest over one missing field.
                continue
            if verdict["level"] != "red":
                attractive.append(
                    f"{entry['ticker']} {round(entry['composite'] * 100)}"
                )
        if attractive:
            lines.append(_link("🎯 Chancen: " + " · ".join(attractive), "radar"))
        else:
            lines.append(_line(
                "🎯 Keine attraktive Chance heute — Nichtstun ist die richtige Aktion."
            ))
    if earnings_this_week:
        today = [e["ticker"] for e in earnings_this_week if e["earnings_date"] == date_label]
        rest = len(earnings_this_week) - len(today)
        if today:
            lines.append(_line(
                f"📅 Earnings heute: {', '.join(today)} · {rest} weitere diese Woche"
            ))
        else:
            lines.append(_line(f"📅 Earnings: heute keine · {rest} diese Woche"))
    open_pitches = _dedupe_open([p for p in pitches if p["status"] == "open"])
    decided = [
        p for p in pitches
        if p["status"] != "open"
        and (decided_since is None or (p["decided_at"] or "") >= decided_since)
    ]
    if not open_pitches:
        lines.append(_line(
            "📬 Keine offenen Pitches — nichts zu tun ist gerade die richtige Aktion."
        ))
    else:
        fresh = [
            p for p in open_pitches
            if decided_since is None or p["created_at"] >= decided_since
        ]
        # "N Pitch(es) offen" uses the count so no singular/plural agreement is needed;
        # only FRESH pitches get a line — repeating yesterday's list is what made the
        # digest a wall of text (Nico, 2026-08-04).
        noun = "Pitch" if len(open_pitches) == 1 else "Pitches"
        suffix = f"{len(fresh)} neu" if fresh else "nichts neu"
        lines.append(_link(
            f"📬 {len(open_pitches)} {noun} offen · {suffix}", "inbox"
        ))
        for p in fresh[:OPEN_PITCH_CAP]:
            icon = VERDICT_EMOJI.get(p.get("verdict"), "📬")
            lines.append(_line(
                f"  {icon} {p['ticker']} · {round(p['composite'] * 100)}/100"
                f" · {p['price']:.2f}"
            ))
    if decided:
        lines.append(_line(
            "✅ Entschieden: " + " · ".join(
                f"{_STATUS_ICON.get(p['status'], p['status'])} {p['ticker']}"
                for p in decided
            )
        ))
    if evidence_stats:
        resolved = sum(entry["n_resolved"] for entry in evidence_stats.values())
        open_count = sum(entry["n_open"] for entry in evidence_stats.values())
        if resolved == 0:
            lines.append(_line(
                f"🔬 Evidenz: {format_de(open_count)} offen, noch keine Auflösung"
            ))
        else:
            best = max(
                (e for e in evidence_stats.items() if e[1]["n_resolved"] > 0),
                key=lambda item: item[1]["hit_rate"],
            )
            lines.append(_line(
                f"🔬 Evidenz: {format_de(resolved)} aufgelöst · beste Quelle"
                f" {_SOURCE_LABEL.get(best[0], best[0])}"
                f" {round(best[1]['hit_rate'] * 100)} %"
            ))
```

Then delete the now-unused `below_threshold` rendering. Keep the PARAMETER in the signature (callers pass it) but mark it explicitly:

```python
    below_threshold: int | None = None,  # noqa: ARG001 - accepted for callers, no longer rendered
```

- [ ] **Step 4: Delete the alerts section**

The "📌 Heute aufgefallen" block (lines 222-234) duplicates what the chances line already says and its reasons can carry 90-char press headlines. Delete lines 222-234 entirely, and mark the parameter the same way:

```python
    alerts_today: list[dict] | None = None,  # noqa: ARG001 - dashboard renders alerts (VoicesPanel)
```

Verified 2026-08-04: alerts ARE dashboard-visible via `/api/evidence` → `recent_alerts` → `VoicesPanel.tsx`, so this is a safe removal under principle 1.

- [ ] **Step 5: Fix the pre-existing assertions that intentionally change**

In `tests/test_digest.py`, these existing tests assert the OLD long-form layout and must be updated to the new one (run the suite to see the exact failures):

- `test_build_digest_lists_open_and_decided` → `"Offene Pitches: 1"` becomes `"📬 1 Pitch offen"`.
- `test_build_digest_decided_since_window_pins_line_and_drops_old` → the pinned line becomes `"✅ Entschieden: ✅ Kaufentscheidung ABC"`.
- `test_build_digest_empty_state` → `"Keine offenen Pitches"` becomes `"📬 Keine offenen Pitches"`.
- `test_build_digest_appends_measured_evidence_stats` → replace with the two new evidence tests from Step 1 (delete the old one).
- `test_build_digest_omits_evidence_section_when_empty` → keep, assert `"🔬 Evidenz"` absent.
- `test_open_pitch_line_carries_stored_verdict`, `test_open_pitch_without_verdict_falls_back_to_mailbox_icon`, `test_open_pitch_with_verdict_but_no_why_renders_icon_only` → pass `decided_since` older than `created_at` so the pitch counts as FRESH and still renders a line; drop the `verdict_why` assertions (the why moved to the pitch itself).
- `test_opportunities_render_live_verdict` → assert the one-line form.
- `test_open_pitches_sorted_green_first_and_capped`, `test_open_pitches_exactly_at_cap_has_no_rest_line`, `test_open_pitches_one_over_cap_says_1_weitere`, `test_open_pitches_newest_first_within_verdict_band`, `test_open_pitches_dedupe_keeps_newest_per_ticker` → keep the dedupe/sort/cap behaviour but make every fixture pitch FRESH (`created_at` after `decided_since`, or omit `decided_since`); the `… N weitere im Dashboard.` line is gone, so replace that assertion with a count check on rendered ticker lines.

- [ ] **Step 6: Run the full digest tests**

Run: `.venv/bin/python -m pytest tests/test_digest.py -v`
Expected: PASS (all, ~28 tests).

- [ ] **Step 7: Commit**

```bash
git add src/equity_scout/digest.py tests/test_digest.py
git commit -m "feat(digest): collapse chances, pitches, earnings and evidence to one line each"
```

---

### Task 4: Deep links into the phone cockpit

**Files:**
- Modify: `src/equity_scout/digest.py` (`build_digest` signature + `_link`)
- Modify: `scripts/run_digest.py:346-420`
- Test: `tests/test_digest.py`

This is what lets the digest stay short: every section head becomes a tap into the cockpit view that holds the depth. Query-param links (`?view=depots`) are deliberate — the dashboard is served by `StaticFiles(html=True)` mounted at `/`, so a PATH route like `/depots` would 404 while a query param always resolves to `index.html`. The frontend consumes it in the companion plan (`2026-08-04-mobile-focus-app.md`, Task 1); before that lands, an unknown `?view=` is simply ignored and the app opens on "Heute" — harmless.

- [ ] **Step 1: Write the failing tests**

```python
def test_section_heads_link_into_the_cockpit_in_html_mode():
    text = build_digest(
        [], date_label="2026-08-04", autodepot=AUTODEPOT,
        dash_url="https://wsl-claude.tailnet.ts.net:8420", html=True,
    )
    assert (
        '<b><a href="https://wsl-claude.tailnet.ts.net:8420/?view=depots">'
        "🤖 Auto-Depot" in text
    )


def test_plain_text_mode_never_links():
    """stdout/SMTP rendering stays link-free — a bare URL is noise there."""
    text = build_digest(
        [], date_label="2026-08-04", autodepot=AUTODEPOT,
        dash_url="https://example.test", html=False,
    )
    assert "<a href" not in text
    assert "🤖 Auto-Depot" in text


def test_without_dash_url_heads_stay_plain_bold():
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT, html=True)
    assert "<a href" not in text
    assert "<b>🤖 Auto-Depot" in text


def test_dash_url_is_escaped():
    text = build_digest(
        [], date_label="2026-08-04", autodepot=AUTODEPOT,
        dash_url="https://host/?a=1&b=2", html=True,
    )
    assert "&amp;b=2" in text  # a raw & would break Telegram's HTML parser
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_digest.py -k "link or dash_url" -v`
Expected: FAIL — `build_digest` has no `dash_url` parameter yet (TypeError).

- [ ] **Step 3: Implement `_link` and delete the shim**

In `src/equity_scout/digest.py`: delete the `_link_shim` function added in Task 1, add the parameter to `build_digest`'s signature right before `html`:

```python
    dash_url: str | None = None,
```

and replace the temporary `_link` helper inside `build_digest` with:

```python
    def _link(text: str, view: str) -> str:
        """Section head as a deep link into the phone cockpit's matching view.

        Query param (not a path) because the dashboard is served by StaticFiles at "/" —
        `/depots` would 404, `?view=depots` always resolves to index.html. Plain-text
        mode never links: a bare URL adds noise to the stdout/SMTP rendering.
        """
        if not (html and dash_url):
            return _head(text)
        url = escape_html(f"{dash_url.rstrip('/')}/?view={view}")
        return f'<b><a href="{url}">{escape_html(text)}</a></b>'
```

- [ ] **Step 4: Wire it in `run_digest.py`**

In `scripts/run_digest.py`, inside `render`, add to the `build_digest(...)` call:

```python
            dash_url=os.environ.get("DASH_URL") or None,
```

Then delete the weekly `DASH_URL` hint (the `show_dash_hint` / `DASH_URL_WEEK_KEY` machinery, lines ~344-352 and the two `if show_dash_hint:` append blocks plus the `mark_sent` branch): every section head links now, so a weekly reminder line is redundant. Leave `DASH_URL_WEEK_KEY`'s stored state alone — an orphan `app_state` row is harmless and deleting it would need a migration.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_digest.py tests/test_run_digest_guard.py -v`
Expected: PASS. If a guard test asserts the dash-hint behaviour, delete that test — the feature is gone.

- [ ] **Step 6: Commit**

```bash
git add src/equity_scout/digest.py scripts/run_digest.py tests/
git commit -m "feat(digest): deep-link section heads into the phone cockpit"
```

---

### Task 5: Materiality threshold for the nightly Auto-Depot push

**Files:**
- Modify: `scripts/run_autotrader.py:302-320`
- Test: `tests/test_autotrader_events.py` (create)

Current behaviour: any advance with ≥ 1 trade sends up to 10 lines, one per trade — including 60-USD rebalances. Target: material trades named, immaterial ones counted, and NO push at all when nothing material happened and no risk event fired (a silent nightly no-op beats a push that trains you to ignore pushes).

- [ ] **Step 1: Write the failing test**

Create `tests/test_autotrader_events.py`:

```python
"""Nightly Auto-Depot push: materiality threshold (Telegram diet, 2026-08-04).

A dozen sub-1 % rebalances used to produce a dozen lines; only material moves and risk
events are worth a push at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from scripts.run_autotrader import build_event_message


@dataclass
class FakeTrade:
    ticker: str
    delta_weight: float
    notional: float


@dataclass
class FakeEvent:
    detail: str


@dataclass
class FakeValuation:
    created_at: str
    trades: list
    risk_events: list


def test_no_message_when_only_immaterial_trades_happened():
    valuation = FakeValuation(
        "2026-08-03",
        [FakeTrade("XLK", -0.0006, 60.0), FakeTrade("BIL", 0.0006, 60.0)],
        [],
    )
    assert build_event_message(valuation) is None


def test_immaterial_trades_still_push_when_a_risk_event_fired():
    valuation = FakeValuation(
        "2026-08-03",
        [FakeTrade("XLK", -0.0006, 60.0)],
        [FakeEvent("Einzeltitel-Limit 10% griff bei: SPY")],
    )
    message = build_event_message(valuation)
    assert message is not None
    assert "⚠ Einzeltitel-Limit 10% griff bei: SPY" in message
    assert "1 kleine Rebalance" in message


def test_material_trades_are_named_with_direction_and_size():
    valuation = FakeValuation(
        "2026-08-03",
        [FakeTrade("MU", -0.041, 4100.0), FakeTrade("XLK", -0.0006, 60.0)],
        [],
    )
    message = build_event_message(valuation)
    assert "🤖 Auto-Depot 2026-08-03" in message
    assert "• VERKAUF MU 4,1 % (~4.100 $)" in message
    assert "1 kleine Rebalance" in message


def test_quiet_advance_stays_silent():
    assert build_event_message(FakeValuation("2026-08-03", [], [])) is None
    assert build_event_message(None) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_autotrader_events.py -v`
Expected: FAIL — the current builder emits a line per trade and returns a message for immaterial-only advances.

- [ ] **Step 3: Rewrite `build_event_message`**

In `scripts/run_autotrader.py`, replace `EVENT_TRADE_CAP = 10` and `build_event_message` (lines 302-320) with:

```python
# Same threshold as the digest's trade summary (digest.MATERIAL_DELTA_WEIGHT): a move
# below 1 % of the book is bookkeeping. Imported rather than re-declared so the two
# surfaces can never disagree about what "material" means.
EVENT_TRADE_CAP = 5


def build_event_message(valuation: AutoDepotValuation | None) -> str | None:
    """One bundled nightly push, or None when nothing material happened.

    Diet rule (2026-08-04): a push must earn the notification. Material trades
    (|Δweight| >= digest.MATERIAL_DELTA_WEIGHT) and risk events do; a night of pure
    sub-1 % rebalancing does not — that detail lives in the digest and the cockpit.
    """
    from equity_scout.digest import MATERIAL_DELTA_WEIGHT, format_de

    if valuation is None:
        return None
    material = sorted(
        (t for t in valuation.trades if abs(t.delta_weight) >= MATERIAL_DELTA_WEIGHT),
        key=lambda t: abs(t.delta_weight), reverse=True,
    )
    if not material and not valuation.risk_events:
        return None
    lines = [f"🤖 Auto-Depot {valuation.created_at}"]
    for t in material[:EVENT_TRADE_CAP]:
        side = "KAUF" if t.delta_weight > 0 else "VERKAUF"
        lines.append(
            f"• {side} {t.ticker} {format_de(abs(t.delta_weight) * 100, 1)} %"
            f" (~{format_de(t.notional)} $)"
        )
    hidden = len(valuation.trades) - min(len(material), EVENT_TRADE_CAP)
    if hidden > 0:
        # "kleine Rebalance" stays invariant for 1 and n — no plural branch needed.
        lines.append(f"… {hidden} kleine Rebalance")
    for event in valuation.risk_events:
        lines.append(f"⚠ {event.detail}")
    lines.append("(Paper-Depot · nächtlicher Lauf · Details im Digest)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_autotrader_events.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/run_autotrader.py tests/test_autotrader_events.py
git commit -m "feat(autotrader): push nightly events only when material"
```

---

### Task 6: Pitch caption — 4 lines, depth behind the existing Details button

**Files:**
- Modify: `src/equity_scout/pitch.py:272-339`
- Test: `tests/test_pitch.py`

The caption currently carries head + verdict + up to 4 number lines + analyst target + F-score + evidence + press + risk, up to 980 chars — and 5-10 of these arrive in a row. Everything below the risk line is already reachable via the "🔎 Details" callback (`telegram_client.DETAIL_ACTION` → `build_pitch(html=True)`), which is unaffected by this task.

- [ ] **Step 1: Write the failing tests**

```python
def test_caption_is_four_lines():
    caption = build_pitch_caption(ENTRY, FUNDAMENTALS)
    assert len(caption.splitlines()) == 4


def test_caption_keeps_name_verdict_price_and_risk():
    caption = build_pitch_caption(ENTRY, FUNDAMENTALS)
    lines = caption.splitlines()
    assert lines[0] == "<b>📈 MU — Micron Technology</b>"
    assert lines[1].startswith("🟡 <b>Einstieg neutral</b> · 60/100")
    assert lines[2].startswith("💰 Kurs")
    assert "🎯 Zone" in lines[2]
    assert lines[3].startswith("⚠️ ")


def test_caption_drops_the_depth_that_the_details_button_serves():
    caption = build_pitch_caption(
        ENTRY, FUNDAMENTALS, evidence=EVIDENCE, press_lines=["Schlagzeile"],
        f_score={"score": 7, "evaluable": 9, "fiscal_year": 2025},
    )
    assert "Analysten" not in caption
    assert "Bilanz-Trend" not in caption
    assert "Schlagzeile" not in caption
    assert "👥" not in caption


def test_full_pitch_still_carries_the_dropped_depth():
    """The details path must keep everything the caption gave up."""
    text = build_pitch(
        ENTRY, FUNDAMENTALS, ask=lambda q, c: "Kurz.", html=True,
        f_score={"score": 7, "evaluable": 9, "fiscal_year": 2025},
    )
    assert "Analystensicht" in text
    assert "Bilanz-Trend" in text
```

Reuse the module's existing `ENTRY` / `FUNDAMENTALS` / `EVIDENCE` fixtures; if `EVIDENCE` does not exist there, build it from `evidence_summary_lines`' expected shape as the other tests in that file do.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pitch.py -k caption -v`
Expected: FAIL — the caption currently renders more blocks and more than 4 lines.

- [ ] **Step 3: Rewrite the caption builder**

In `src/equity_scout/pitch.py`, replace the body of `build_pitch_caption` after its docstring (keep the signature — callers in `scripts/run_notify.py` pass every argument) with:

```python
    cur = f" {fundamentals.currency}" if fundamentals and fundamentals.currency else ""
    score = round(entry["composite"] * 100)
    verdict = compute_verdict(entry)
    price = f"Kurs {entry['price']:.2f}{cur}"
    if eur_price is not None:
        price += f" (≈ {eur_price:.2f} €)"
    risk = _risk_line(entry)
    lines = [
        f"<b>📈 {entry['ticker']} — {escape_html(entry['name'])}</b>",
        f"{verdict['emoji']} <b>{verdict['label']}</b> · {score}/100 · "
        f"stark: {_top_factors(entry['breakdown'])}",
        f"💰 {price} · 🎯 Zone {entry['entry_zone_low']:.2f}–"
        f"{entry['entry_zone_high']:.2f}{cur}",
    ]
    if risk:
        lines.append(f"⚠️ {escape_html(risk if len(risk) <= 90 else risk[:89] + '…')}")
    caption = "\n".join(lines)
    if len(caption) <= _CAPTION_LIMIT:
        return caption
    plain = strip_html(caption)
    return plain if len(plain) <= _CAPTION_LIMIT else plain[: _CAPTION_LIMIT - 1] + "…"
```

Update the docstring's layout description to the 4-line form and note that analyst target, F-score, evidence, press and the model target/stop are served by the "🔎 Details" callback. The unused parameters stay in the signature for the callers; mark them:

```python
    evidence: list[dict] | None = None,  # noqa: ARG001 - served by the Details callback
    press_lines: list[str] | None = None,  # noqa: ARG001 - served by the Details callback
    target_stop: dict | None = None,  # noqa: ARG001 - served by the Details callback
    f_score: dict | None = None,  # noqa: ARG001 - served by the Details callback
    one_year_return: float | None = None,  # noqa: ARG001 - the chart photo already shows it
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_pitch.py -v`
Expected: PASS. Fix any existing caption assertion that pinned a dropped line (analyst target, F-score, 1-year return, evidence) by deleting that assertion — the depth moved, it is covered by `test_full_pitch_still_carries_the_dropped_depth`.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/pitch.py tests/test_pitch.py
git commit -m "feat(pitch): cut caption to four lines, depth via Details button"
```

---

### Task 7: Verify against the real data and record the outcome

**Files:**
- Create: `docs/sessions/2026-08-04_telegram-diet-verify.md`

- [ ] **Step 1: Render the real digest before/after**

Run this read-only reproduction (no sends, no DB writes) and record the numbers:

```bash
cd /home/nicosutheimer/private/equity-scout && .venv/bin/python - <<'PY'
import sys; sys.path.insert(0, ".")
from datetime import datetime, timedelta, timezone
from equity_scout.autotrader_storage import DEFAULT_AUTOTRADER_DB_PATH, load_depot
from equity_scout.butler import core_running_line
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.digest import build_digest
from equity_scout.earnings_storage import earnings_within
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.inbox_storage import load_pitches
from equity_scout.notify import DEFAULT_THRESHOLD
from equity_scout.radar_storage import load_latest_watchlist
from scripts.run_digest import (EARNINGS_LOOKAHEAD_DAYS, OPPORTUNITY_TOP_N, _load_panel,
                                collect_autodepot, collect_regime, collect_sector_line,
                                collect_shortterm)
db = DEFAULT_DB_PATH
now = datetime.now(timezone.utc); label = now.date().isoformat()
day_ago = (now - timedelta(hours=24)).isoformat(timespec="seconds")
wl = load_latest_watchlist(db) or {}
acct = load_depot(DEFAULT_AUTOTRADER_DB_PATH)
panel = _load_panel()
text = build_digest(
    load_pitches(db, limit=1000), date_label=label, decided_since=day_ago,
    evidence_stats=stats_by_source(db),
    opportunities=sorted(wl.get("entries", []), key=lambda e: e["composite"],
                         reverse=True)[:OPPORTUNITY_TOP_N],
    earnings_this_week=earnings_within(db, today=label, days=EARNINGS_LOOKAHEAD_DAYS),
    regime=collect_regime(panel), sector_line=collect_sector_line(panel),
    core_block=core_running_line(html=False),
    below_threshold=sum(1 for e in wl.get("entries", [])
                        if e["composite"] < DEFAULT_THRESHOLD),
    autodepot=collect_autodepot(today=label),
    shortterm=collect_shortterm(label,
                                promoted=frozenset(acct.promoted_lanes) if acct else frozenset()),
    html=False,
)
print(text)
print(f"\nCHARS: {len(text)}  LINES: {len(text.splitlines())}")
PY
```

Expected: ≤ 16 lines (baseline 2026-08-04: 55 lines / 2.313 chars). If it exceeds 16, find the section that grew and shorten it before continuing.

- [ ] **Step 2: Run the whole gate**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check .`
Expected: exit 0 for both (baseline before this plan: 1177 tests green).

- [ ] **Step 3: Send one real test message**

Run: `.venv/bin/python scripts/run_digest.py --force`
Then check the phone: one message, ≤ 16 lines, section heads tappable (they open the cockpit; the mobile focus layout arrives with the companion plan).

- [ ] **Step 4: Write the outcome doc**

Create `docs/sessions/2026-08-04_telegram-diet-verify.md` with: before/after line + char counts, which sections moved where, the measured digest text after the change, and anything still open.

- [ ] **Step 5: Commit**

```bash
git add docs/sessions/2026-08-04_telegram-diet-verify.md
git commit -m "docs: record Telegram diet verification"
```

---

## Deliberately not built

- **No compact/full digest split.** `SMTP_*` is unconfigured (checked 2026-08-04: `.env` holds only `COPILOT_TG_*`, `DASH_TOKEN`, `EDGAR_USER_AGENT`), so Telegram and stdout are the only consumers. Two renderers for one consumer is the abstraction YAGNI warns about; add it when e-mail actually gets configured.
- **No Telegram drill-down buttons.** Deep links into the cockpit deliver the same depth without a second navigation mechanic inside the receiver. Reconsider only if the cockpit turns out to be unreachable in practice.
- **No per-section env switches.** Configuration for a one-person notification stream is complexity without a second use case.
- **`stats_by_source` still has no dashboard rendering.** Out of scope here; the digest keeps a condensed line so nothing is lost. Worth a small `VoicesPanel` block later.

---

## Outcome (2026-08-04)

**Umgesetzt und verifiziert.** Digest 55 → 17 Zeilen (15 Inhalt + 2 Spacer), 2.313 → 718
Zeichen; Caption 4 Zeilen; nächtlicher Push nur bei Materialität. 1207 Tests grün, ruff
clean, echter Digest an Telegram gesendet.

Abweichungen:
- Tasks 1–4 inline statt per Subagent (eine Datei, gekoppelte Kette).
- 17 statt ≤ 16 Zeilen (zwei Leerzeilen als Struktur).
- **18 Tests in vier nicht im Plan erfassten Dateien brachen** und wurden nachgezogen:
  `test_autotrader_digest`, `test_digest_sections`, `test_digest_v8`,
  `test_shortterm_digest`. Lehre: der Plan hätte `grep -rl build_digest tests/` als
  ersten Schritt haben müssen.
- Review-Fund: über-Cap-materielle Trades wurden als „kleine Rebalance" gezählt — in
  „+N weitere über der Schwelle" und „N kleine Rebalance" getrennt (Commit 7c21417).
- Drei Absenz-Tests waren trivial wahr geworden und wurden geschärft (Commit e0a1f13).

Zusätzlich (nicht geplant, aber nötig): `DASH_URL` war in `.env` nie gesetzt — ohne den
Wert rendert der Digest keine Deeplinks. Auf `http://100.99.224.50:8420` gesetzt.

Details: `docs/sessions/2026-08-04_telegram-diet-and-mobile-focus-app.md`.
