# Phone Cockpit: Potential, Chart, AI News and the Autotrader Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one daily look at the phone enough — the stock tab answers "is there anything interesting, and would this be a good entry?" at a glance (logo, company name, potential as a headline number, 1-year chart, AI-summarised news), and the autotrader tab answers "what did my traders do?" (current holdings plus the trades they made, short-term and long-term).

**Architecture:** No new stack. Two additions on the backend: a nightly step that generates the AI texts and stores a downsampled 1-year price series per stock in SQLite (LLM latency measured at 5.6 s warm / 27 s cold — far too slow for an HTTP request, so `/api/briefs` only ever reads the cache), and `/api/briefs` growing two fields that serve that cache. On the frontend the existing `StockList` becomes two honest sections ("Jetzt im Einstiegsbereich" from our own signal, "Höchstes Potenzial" from analyst consensus), gains an inline SVG sparkline, and the phone gets a compact autotrader view instead of the seven-tab desktop `DepotsView`.

**Tech Stack:** Python 3 / FastAPI / SQLite (raw `sqlite3`, existing style), local Ollama via `chat.ask_ollama` (`qwen2.5:7b`), React 19 / TypeScript 5.8 / Vite 7, vitest, pytest.

---

## Decisions Nico made on 2026-08-05 (these are settled — do not re-litigate)

1. **"Potenzial" is analyst consensus, clearly labelled.** No self-invented target. `entry.compute_target_stop` returns None because no `entry_tb` champion is registered, so `model_target` stays the honest `null` it is today.
2. **News are made visible, they do NOT change the ranking.** No evidence/news term enters the funnel score. Measured: `grep -n evidence src/equity_scout/radar.py src/equity_scout/signals.py src/equity_scout/engine.py` returns nothing today, and this plan keeps it that way.
3. **Telegram keeps one nudge per day.** The digest stays as-is (17 lines, deep links already shipped 2026-08-04). This plan does not touch `digest.py` or `notify.py`.

## Design constraints (each verified against the code on 2026-08-05)

1. **The LLM must never run inside an HTTP request.** Measured on this machine via `chat.ask_ollama` with a realistic fact block: **27.2 s cold, 5.6 s warm** per call. Two calls per stock. The phone card must open instantly, so generation happens in the 18:00 chain and `/api/briefs` reads SQLite only.
2. **Ollama is not running by default.** `systemctl is-active ollama` → `inactive`; models present locally: `qwen2.5:7b`, `qwen2.5:1.5b`, `llama3.1:8b`, `qwen2.5vl:7b`. Without Task 1 the nightly step produces nothing but honest nulls.
3. **The ranking contradicts the headline number.** Measured on the live watchlist (30 titles, run 2026-08-05T20:30Z): `rank_entries` puts in-zone first, so the top two rows are `9064.T` at **−7 %** and `9022.T` at **+15 %**, while `MU` at **+69 %** is rank 3 and `SNDK` at **+64 %** is rank 4. A single list sorted our way cannot deliver "potential at a glance", and sorting by upside would promote a third-party opinion above our own signal. Hence two labelled sections (Task 6).
4. **Analyst coverage is good but not complete.** Measured over the top 12: **11/12** have a target (`AIRT` has none). A missing target renders an honest gap, never a zero and never a dash pretending to be a number.
5. **Query param, not path routing.** FastAPI serves the built app via `StaticFiles(directory=dist, html=True)` mounted at `/` (`api.py:941`). `?view=…` resolves to `index.html`; a path route would 404. Existing `parseView` in `frontend/src/views.ts` already handles this.
6. **The DB lives in the repo root.** `constants.DEFAULT_DB_PATH = "equity_scout.db"` — the real file is `./equity_scout.db` (23 MB), NOT `data/equity_scout.db`. A relative path means every script must run from the repo root (`daily_copilot.sh` does `cd "$REPO_DIR"`).
7. **No external script in the PWA.** The existing `StockChart.tsx` loads `s3.tradingview.com` and hardcodes `colorTheme: "light"`. It stays where it is (desktop `PickCard`/`Portfolio`), but the phone card gets an inline SVG from our own data: the service worker can cache it, it survives WSL being off, and it matches the dark cockpit.
8. **Two tables, not one.** A price series is a fact that goes stale daily; a company description is an interpretation that never does. They get separate tables with separate freshness stamps (`as_of` vs `generated_at`) so the UI can label each correctly.
9. **`fetch_fundamentals_cached` already bounds the yfinance cost** of `/api/briefs` (6 h in-process TTL, all-None never cached — `fundamentals.py:80-101`). Raising `limit` from 5 to 12 does not add a per-visit network cost after the first warm-up.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/install_ollama_service.sh` | Create: `systemctl --user` unit so Ollama is up when the 18:00 chain runs |
| `src/equity_scout/insights.py` | Create: pure prompts + LLM output sanitising + price-series downsampling. No network, no DB |
| `src/equity_scout/insights_storage.py` | Create: `stock_insights` + `price_series` tables, upsert + load |
| `scripts/run_insights.py` | Create: the I/O runner — watchlist → headlines → Ollama → SQLite |
| `scripts/daily_copilot.sh` | Modify: new `insights` step after `radar` |
| `src/equity_scout/briefs.py` | Modify: `build_brief` takes `insight` + `chart` and passes them through |
| `src/equity_scout/api.py` | Modify: `/api/briefs` loads both caches, `limit` default 5 → 12 |
| `frontend/src/api.ts` | Modify: `StockBrief` gains `insight` + `chart`, `fetchBriefs` default 12, `AutodepotTrade` gains the v13 fill fields and `AutodepotResponse` gains `fill_convention` |
| `frontend/src/stocklist.ts` | Create: pure section-split logic (`splitSections`) |
| `frontend/src/stocklist.test.ts` | Create: tests for the split |
| `frontend/src/sparkline.ts` | Create: pure SVG path geometry |
| `frontend/src/sparkline.test.ts` | Create: geometry tests |
| `frontend/src/components/MiniYearChart.tsx` | Create: the inline SVG sparkline |
| `frontend/src/components/StockList.tsx` | Modify: two sections, potential as the headline number, AI text in the detail |
| `frontend/src/components/PhoneDepot.tsx` | Create: compact autotrader view for the phone |
| `frontend/src/components/DepotsView.tsx` | Modify: render `PhoneDepot` below 720 px, the tab bar above it |
| `frontend/src/index.css` | Modify: styles for the potential number, the sparkline and the phone depot |
| `tests/test_insights.py` | Create: pure tests for prompts, sanitising, downsampling |
| `tests/test_insights_storage.py` | Create: round-trip + upsert tests |
| `tests/test_briefs.py` | Modify: `build_brief` with and without an insight |
| `README.md` | Modify: the phone-cockpit section |

---

## Phase A — the nightly generator (Tasks 1–5)

### Task 1: Keep Ollama running

**Files:**
- Create: `scripts/install_ollama_service.sh`

Without a running Ollama the whole AI half of this plan degrades to honest nulls. It is a `systemctl --user` unit, the exact pattern `scripts/install_dash_service.sh` already uses (`UNIT_DIR="$HOME/.config/systemd/user"`).

- [ ] **Step 1: Write the installer**

Create `scripts/install_ollama_service.sh`:

```bash
#!/usr/bin/env bash
# Local Ollama as a systemd --user service.
#
# Why a service and not "start it when needed": the 18:00 chain generates the phone
# cockpit's AI texts (scripts/run_insights.py). A cold model load costs ~27 s, a warm
# call ~5.6 s (measured 2026-08-05), so the chain wants the server already up.
#
# Cost note: purely local inference. Ollama unloads an idle model after ~5 minutes, so
# the resting cost is the daemon, not the 4.7 GB of weights.
set -euo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
BIN="$(command -v ollama)"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/ollama.service" <<EOF
[Unit]
Description=Ollama local LLM server
After=network.target

[Service]
Type=simple
ExecStart=${BIN} serve
Restart=on-failure
RestartSec=5
# Keep one model resident across the chain's ~12 stocks instead of reloading per call.
Environment=OLLAMA_KEEP_ALIVE=15m

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ollama.service
systemctl --user --no-pager status ollama.service | head -5
```

- [ ] **Step 2: Make it executable and run it**

```bash
chmod +x scripts/install_ollama_service.sh
./scripts/install_ollama_service.sh
```

Expected: `Active: active (running)`.

Note: a stray `ollama serve` may already occupy port 11434 from a manual start. If the unit reports `address already in use`, kill the manual process (`pkill -f "ollama serve"`), then `systemctl --user restart ollama.service`.

- [ ] **Step 3: Verify the model answers through the service**

```bash
curl -s -m 120 http://127.0.0.1:11434/api/chat -d '{"model":"qwen2.5:7b","stream":false,"messages":[{"role":"user","content":"Antworte mit genau einem Wort: Test"}]}' | head -c 200
```

Expected: JSON containing a `message.content`.

- [ ] **Step 4: Commit**

```bash
git add scripts/install_ollama_service.sh
git commit -m "chore: run local Ollama as a user service for the nightly AI texts"
```

---

### Task 2: `insights.py` — pure prompts, sanitising, downsampling

**Files:**
- Create: `src/equity_scout/insights.py`
- Test: `tests/test_insights.py`

Everything in this module is pure: prompt construction, cleaning whatever the LLM returns, and reducing a year of closes to a sparkline-sized series. The network lives in Task 4's runner.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_insights.py`:

```python
"""Pure tests for insights.py — no network, no DB, no Ollama."""
from __future__ import annotations

from datetime import datetime

import pytest

from equity_scout.insights import (
    BUSINESS_QUESTION,
    NEWS_QUESTION,
    clean_llm_text,
    downsample_closes,
    fact_context,
    news_context,
)


# --- clean_llm_text ---------------------------------------------------------------

def test_clean_strips_a_chatty_preamble():
    # qwen2.5 likes to announce what it is about to do; the card has no room for it.
    raw = "Hier ist die Zusammenfassung: Das Unternehmen baut Speicherchips."
    assert clean_llm_text(raw) == "Das Unternehmen baut Speicherchips."


def test_clean_strips_markdown_and_bullets():
    raw = "**Zusammenfassung:**\n- Das Unternehmen baut Speicherchips.\n"
    assert clean_llm_text(raw) == "Das Unternehmen baut Speicherchips."


def test_clean_keeps_a_plain_sentence_untouched():
    raw = "Micron Technology stellt DRAM- und NAND-Speicher her."
    assert clean_llm_text(raw) == raw


def test_clean_truncates_at_a_sentence_boundary():
    raw = "Satz eins ist kurz. Satz zwei ist auch kurz. Satz drei fällt weg."
    # max_chars lands inside sentence three -> cut after sentence two, never mid-word.
    assert clean_llm_text(raw, max_chars=45) == "Satz eins ist kurz. Satz zwei ist auch kurz."


def test_clean_falls_back_to_a_hard_cut_when_one_sentence_is_too_long():
    raw = "Ein einziger sehr langer Satz ohne jeden Punkt darin"
    out = clean_llm_text(raw, max_chars=20)
    assert len(out) <= 21  # 20 + the ellipsis character
    assert out.endswith("…")


def test_clean_returns_none_for_empty_or_whitespace():
    assert clean_llm_text("") is None
    assert clean_llm_text("   \n  ") is None


# --- prompts ---------------------------------------------------------------------

def test_business_question_forbids_forecasts():
    # Same guardrail as pitch.py: the LLM interprets, it never predicts.
    assert "Prognose" in BUSINESS_QUESTION
    assert "Kursziel" in BUSINESS_QUESTION


def test_news_question_demands_a_no_news_answer():
    # An LLM handed zero headlines will otherwise invent some.
    assert "keine" in NEWS_QUESTION.lower()


def test_fact_context_carries_the_numbers_and_no_verdict():
    ctx = fact_context(
        ticker="MU", name="Micron Technology", sector="Technology",
        industry="Semiconductors", price=893.19, currency="USD",
    )
    assert "Micron Technology" in ctx
    assert "MU" in ctx
    assert "Semiconductors" in ctx
    assert "893" in ctx
    # No entry advice may leak into the business description's context.
    assert "Einstieg" not in ctx


def test_news_context_numbers_the_headlines():
    ctx = news_context(["Micron raises guidance", "Analysts lift target"])
    assert "1. Micron raises guidance" in ctx
    assert "2. Analysts lift target" in ctx


def test_news_context_is_empty_string_without_headlines():
    assert news_context([]) == ""


# --- downsample_closes -----------------------------------------------------------

def _series(n: int) -> tuple[list[datetime], list[float]]:
    dates = [datetime(2025, 1, 1) for _ in range(n)]
    return dates, [float(i) for i in range(n)]


def test_downsample_keeps_first_and_last_exactly():
    # The card computes the 1-year return from these endpoints — they must be the real ones.
    dates, closes = _series(250)
    out = downsample_closes(dates, closes, points=60)
    assert out["closes"][0] == closes[0]
    assert out["closes"][-1] == closes[-1]


def test_downsample_hits_the_requested_length():
    dates, closes = _series(250)
    assert len(downsample_closes(dates, closes, points=60)["closes"]) == 60


def test_downsample_passes_a_short_series_through_unchanged():
    dates, closes = _series(12)
    out = downsample_closes(dates, closes, points=60)
    assert out["closes"] == closes


def test_downsample_records_the_first_and_last_date():
    dates = [datetime(2025, 8, 5), datetime(2026, 8, 5)]
    out = downsample_closes(dates, [10.0, 12.0], points=60)
    assert out["first_date"] == "2025-08-05"
    assert out["last_date"] == "2026-08-05"


def test_downsample_rejects_an_empty_series():
    with pytest.raises(ValueError):
        downsample_closes([], [], points=60)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.insights'`.

- [ ] **Step 3: Write the module**

Create `src/equity_scout/insights.py`:

```python
"""Pure logic for the phone card's AI texts and its 1-year sparkline.

Two jobs, both deterministic and offline-testable:

1. Prompts + cleaning for the two LLM texts the card shows — one sentence on what the
   company does, and a short summary of its recent headlines. The LLM only ever
   INTERPRETS text and numbers it is handed (same guardrail as pitch.py / chat.py):
   no forecasts, no price targets, no recommendation. Whatever it returns is cleaned
   hard, because a local 7B model reliably adds preambles, markdown and bullets that
   have no room on a phone card.

2. Reducing a year of daily closes to a sparkline-sized series. First and last close
   survive downsampling exactly, because the card derives the 1-year return from those
   two endpoints — a smoothed endpoint would print a return the stock never had.

The network (Ollama, news feeds, yfinance) lives in scripts/run_insights.py; the SQLite
side lives in insights_storage.py. This module imports neither.
"""
from __future__ import annotations

import re
from datetime import datetime

# Sentence budgets. The card shows these on a 390 px screen: one line of business, a
# short paragraph of news. Longer text is not more informative, it is just scrolled past.
BUSINESS_MAX_CHARS = 180
NEWS_MAX_CHARS = 320

BUSINESS_QUESTION = (
    "Erklaere in genau EINEM deutschen Satz, womit dieses Unternehmen sein Geld verdient. "
    "Keine Prognose, kein Kursziel, keine Empfehlung, kein Bezug auf den Aktienkurs. "
    "Antworte nur mit dem Satz selbst, ohne Einleitung."
)

NEWS_QUESTION = (
    "Fasse die unten numerierten Schlagzeilen in maximal zwei deutschen Saetzen zusammen: "
    "worum geht es bei diesem Unternehmen aktuell? Nenne nur, was in den Schlagzeilen steht. "
    "Keine Prognose, kein Kursziel, keine Empfehlung. "
    "Wenn unten keine Schlagzeilen stehen, antworte genau: keine aktuellen Schlagzeilen. "
    "Antworte nur mit der Zusammenfassung selbst, ohne Einleitung."
)

# A 7B model announces itself before answering. These are the openers observed in
# practice; the pattern is anchored at the start and only fires when a colon follows,
# so a legitimate sentence containing "Zusammenfassung" survives.
_PREAMBLE = re.compile(
    r"^\s*(hier (ist|kommt|w[äa]re)[^:]{0,40}|zusammenfassung|antwort|kurzfassung|"
    r"sicher|gerne|nat[üu]rlich)\s*:\s*",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"[*_`#]+")
_BULLET = re.compile(r"^\s*[-•–]\s*", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def clean_llm_text(raw: str, *, max_chars: int = BUSINESS_MAX_CHARS) -> str | None:
    """Card-ready text from a raw local-LLM answer, or None when there is nothing left.

    Truncation prefers a sentence boundary: a card that ends mid-clause reads like a bug.
    Only when the very first sentence already exceeds the budget does it hard-cut with an
    ellipsis, which is honest about being cut off.
    """
    text = _MARKDOWN.sub("", raw or "")
    text = _BULLET.sub("", text)
    # Collapse the model's line breaks: the card is a flowing paragraph, not a list.
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())
    text = _PREAMBLE.sub("", text).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text

    kept: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        candidate = " ".join([*kept, sentence])
        if kept and len(candidate) > max_chars:
            break
        kept.append(sentence)
    joined = " ".join(kept).strip()
    if joined and len(joined) <= max_chars:
        return joined
    return text[:max_chars].rstrip() + "…"


def fact_context(
    *,
    ticker: str,
    name: str,
    sector: str | None,
    industry: str | None,
    price: float,
    currency: str | None,
) -> str:
    """Context for the business sentence: identity and classification only.

    Deliberately WITHOUT the entry zone or the score — this sentence must describe the
    company, and a model handed a verdict starts arguing the verdict.
    """
    lines = [f"Unternehmen: {name} ({ticker})"]
    classification = " / ".join(part for part in (sector, industry) if part)
    if classification:
        lines.append(f"Branche: {classification}")
    lines.append(f"Letzter Kurs: {price:.2f} {currency or ''}".strip())
    return "\n".join(lines)


def news_context(headlines: list[str]) -> str:
    """Numbered headlines as LLM context, or "" when there are none.

    Numbering is not decoration: it lets the summary be traced back to the exact
    headline that caused a claim, and the stored row keeps the same list.
    """
    if not headlines:
        return ""
    return "\n".join(f"{i}. {title}" for i, title in enumerate(headlines, start=1))


def downsample_closes(
    dates: list[datetime], closes: list[float], *, points: int = 60
) -> dict:
    """Reduce a 1-year daily series to `points` samples for the phone sparkline.

    Even index stepping (not averaging): the card draws a price line, and an averaged
    line hides the very drawdowns the shape is there to show. First and last close are
    always the real ones, so the rendered 1-year return matches reality.
    """
    if not closes or not dates:
        raise ValueError("cannot downsample an empty series")
    if len(closes) <= points:
        sampled = list(closes)
    else:
        step = (len(closes) - 1) / (points - 1)
        sampled = [closes[round(i * step)] for i in range(points)]
        sampled[0], sampled[-1] = closes[0], closes[-1]
    return {
        "first_date": dates[0].date().isoformat(),
        "last_date": dates[-1].date().isoformat(),
        "closes": sampled,
    }
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_insights.py -q`
Expected: PASS (16 tests).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check src/equity_scout/insights.py tests/test_insights.py
git add src/equity_scout/insights.py tests/test_insights.py
git commit -m "feat(insights): pure prompts, LLM output cleaning and sparkline downsampling"
```

---

### Task 3: `insights_storage.py` — two tables

**Files:**
- Create: `src/equity_scout/insights_storage.py`
- Test: `tests/test_insights_storage.py`

Two tables on purpose (design constraint 8): `stock_insights` holds interpretations that never go stale, `price_series` holds facts that go stale every trading day. `ticker` is the primary key in both — the current text/series replaces the old one, and no consumer wants the history of a derived sentence.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_insights_storage.py`:

```python
"""Round-trip tests for insights_storage.py against a temp SQLite file."""
from __future__ import annotations

from equity_scout.insights_storage import (
    init_insights_db,
    load_insights,
    load_price_series,
    save_insight,
    save_price_series,
)


def test_save_and_load_one_insight(tmp_path):
    db = str(tmp_path / "t.db")
    save_insight(
        db, ticker="MU", generated_at="2026-08-05T18:00:00+00:00",
        business="Micron baut Speicherchips.",
        news_summary="Micron hebt die Prognose an.",
        headlines=["Micron raises guidance"], model="qwen2.5:7b",
    )
    rows = load_insights(db)
    assert set(rows) == {"MU"}
    assert rows["MU"]["business"] == "Micron baut Speicherchips."
    assert rows["MU"]["headlines"] == ["Micron raises guidance"]
    assert rows["MU"]["model"] == "qwen2.5:7b"


def test_saving_the_same_ticker_twice_replaces_it(tmp_path):
    db = str(tmp_path / "t.db")
    for text in ("alt", "neu"):
        save_insight(
            db, ticker="MU", generated_at="2026-08-05T18:00:00+00:00",
            business=text, news_summary=None, headlines=[], model="qwen2.5:7b",
        )
    rows = load_insights(db)
    assert len(rows) == 1
    assert rows["MU"]["business"] == "neu"


def test_a_null_text_survives_the_round_trip(tmp_path):
    # A failed LLM call stores an honest null, and the card says so — it must not come
    # back as the string "None".
    db = str(tmp_path / "t.db")
    save_insight(
        db, ticker="AIRT", generated_at="2026-08-05T18:00:00+00:00",
        business=None, news_summary=None, headlines=[], model="qwen2.5:7b",
    )
    assert load_insights(db)["AIRT"]["business"] is None


def test_save_and_load_a_price_series(tmp_path):
    db = str(tmp_path / "t.db")
    save_price_series(
        db, ticker="MU", as_of="2026-08-05T18:00:00+00:00",
        first_date="2025-08-05", last_date="2026-08-05", closes=[10.0, 11.0, 12.5],
    )
    series = load_price_series(db)
    assert series["MU"]["closes"] == [10.0, 11.0, 12.5]
    assert series["MU"]["first_date"] == "2025-08-05"


def test_loading_from_a_fresh_db_returns_empty_dicts(tmp_path):
    # The API must survive a DB written before this migration existed.
    db = str(tmp_path / "fresh.db")
    assert load_insights(db) == {}
    assert load_price_series(db) == {}


def test_init_is_idempotent(tmp_path):
    db = str(tmp_path / "t.db")
    init_insights_db(db)
    init_insights_db(db)
    assert load_insights(db) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_insights_storage.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.insights_storage'`.

- [ ] **Step 3: Write the module**

Create `src/equity_scout/insights_storage.py`:

```python
"""SQLite persistence for the phone card's AI texts and its 1-year price series.

Same style as radar_storage.py: raw sqlite3, JSON snapshot columns, idempotent init
called from every entry point so a read never faces a table that does not exist yet.

TWO tables, deliberately not one: an insight is an interpretation with no natural
expiry (a company's business model does not change overnight), a price series is a fact
that is stale the next trading day. Separate `generated_at` / `as_of` stamps let the UI
label each honestly instead of inheriting one shared, wrong freshness.

`ticker` is the primary key in both: the newest text/series replaces the previous one.
Nobody wants the version history of a derived sentence, and both are cheap to regenerate.
"""
from __future__ import annotations

import json
import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH


def init_insights_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS stock_insights (
                ticker TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                business TEXT,
                news_summary TEXT,
                headlines TEXT NOT NULL DEFAULT '[]',
                model TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS price_series (
                ticker TEXT PRIMARY KEY,
                as_of TEXT NOT NULL,
                first_date TEXT NOT NULL,
                last_date TEXT NOT NULL,
                closes TEXT NOT NULL
            )"""
        )


def save_insight(
    db_path: str,
    *,
    ticker: str,
    generated_at: str,
    business: str | None,
    news_summary: str | None,
    headlines: list[str],
    model: str | None,
) -> None:
    """Upsert one stock's AI texts. A None text is stored as SQL NULL, never "None"."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_insights"
            " (ticker, generated_at, business, news_summary, headlines, model)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET"
            "  generated_at=excluded.generated_at, business=excluded.business,"
            "  news_summary=excluded.news_summary, headlines=excluded.headlines,"
            "  model=excluded.model",
            (
                ticker, generated_at, business, news_summary,
                json.dumps(headlines, ensure_ascii=False), model,
            ),
        )


def save_price_series(
    db_path: str,
    *,
    ticker: str,
    as_of: str,
    first_date: str,
    last_date: str,
    closes: list[float],
) -> None:
    """Upsert one stock's downsampled 1-year close series."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO price_series (ticker, as_of, first_date, last_date, closes)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET"
            "  as_of=excluded.as_of, first_date=excluded.first_date,"
            "  last_date=excluded.last_date, closes=excluded.closes",
            (ticker, as_of, first_date, last_date, json.dumps(closes)),
        )


def load_insights(db_path: str = DEFAULT_DB_PATH) -> dict[str, dict]:
    """Every stored insight keyed by ticker (the API joins this onto the watchlist)."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ticker, generated_at, business, news_summary, headlines, model"
            " FROM stock_insights"
        ).fetchall()
    return {
        row[0]: {
            "generated_at": row[1],
            "business": row[2],
            "news_summary": row[3],
            "headlines": json.loads(row[4] or "[]"),
            "model": row[5],
        }
        for row in rows
    }


def load_price_series(db_path: str = DEFAULT_DB_PATH) -> dict[str, dict]:
    """Every stored 1-year series keyed by ticker."""
    init_insights_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ticker, as_of, first_date, last_date, closes FROM price_series"
        ).fetchall()
    return {
        row[0]: {
            "as_of": row[1],
            "first_date": row[2],
            "last_date": row[3],
            "closes": json.loads(row[4]),
        }
        for row in rows
    }
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_insights_storage.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check src/equity_scout/insights_storage.py tests/test_insights_storage.py
git add src/equity_scout/insights_storage.py tests/test_insights_storage.py
git commit -m "feat(insights): persist AI texts and 1-year price series per ticker"
```

---

### Task 4: `run_insights.py` — the nightly runner

**Files:**
- Create: `scripts/run_insights.py`
- Modify: `scripts/daily_copilot.sh`

This is the only place in Phase A that touches the network. It follows `run_notify.py`'s conventions: repo root anchored before sibling imports (the 2026-08-04 crash that silenced pitches for two weeks came from exactly this), and every failure degrades to a stored null instead of aborting the chain.

- [ ] **Step 1: Check how run_notify.py anchors the repo root**

Run: `sed -n 1,50p scripts/run_notify.py`

Copy that anchoring idiom verbatim into the new script — do not invent a second one.

- [ ] **Step 2: Write the runner**

Create `scripts/run_insights.py`:

```python
#!/usr/bin/env python3
"""Generate the phone cockpit's AI texts + 1-year price series for the top watchlist
stocks and cache them in SQLite.

Runs in the 18:00 chain, never in an HTTP request: a warm local LLM call costs ~5.6 s
and a cold one ~27 s (measured 2026-08-05), so /api/briefs only ever reads what this
script wrote. Every step degrades on its own — a dead news feed, a missing Ollama or a
rate-limited yfinance each store an honest null for that field and the run continues.

Scope: the top --limit stocks by briefs.rank_entries, i.e. exactly the rows the phone
card shows. Generating all 30 watchlist names would cost ~6 minutes of inference and 30
keyless RSS requests for cards nobody scrolls to.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# The chain starts this file by path (`python scripts/run_insights.py`), which puts
# scripts/ on sys.path but NOT the repo root — the sibling imports below would fail
# exactly as run_notify.py's did on 2026-07-21. Anchor the root first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from equity_scout.briefs import rank_entries  # noqa: E402
from equity_scout.charts import fetch_year_closes  # noqa: E402
from equity_scout.chat import OLLAMA_MODEL, ChatError, ask_ollama  # noqa: E402
from equity_scout.constants import DEFAULT_DB_PATH  # noqa: E402
from equity_scout.fundamentals import fetch_fundamentals_cached  # noqa: E402
from equity_scout.insights import (  # noqa: E402
    BUSINESS_MAX_CHARS,
    BUSINESS_QUESTION,
    NEWS_MAX_CHARS,
    NEWS_QUESTION,
    clean_llm_text,
    downsample_closes,
    fact_context,
    news_context,
)
from equity_scout.insights_storage import save_insight, save_price_series  # noqa: E402
from equity_scout.press import fetch_press_lines  # noqa: E402
from equity_scout.radar_storage import load_latest_watchlist  # noqa: E402

# Headlines per stock fed to the summariser. Five is enough for "what is going on here"
# and keeps the prompt short enough that a 7B model stays on topic.
_HEADLINE_LIMIT = 5


def _ask(question: str, context: str, *, max_chars: int) -> str | None:
    """One LLM call, cleaned. Any Ollama failure is a null, never an exception."""
    try:
        return clean_llm_text(ask_ollama(question, context), max_chars=max_chars)
    except ChatError as exc:
        print(f"    LLM nicht verfügbar: {exc}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--limit", type=int, default=12,
        help="how many top-ranked watchlist stocks to generate for (default 12)",
    )
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db)
    entries = rank_entries((watchlist or {}).get("entries", []))[: args.limit]
    if not entries:
        print("Keine Watchlist — nichts zu erzeugen. (Lief der Radar?)")
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"Erzeuge Steckbrief-Texte für {len(entries)} Titel (Modell {OLLAMA_MODEL})")

    for entry in entries:
        ticker, name = entry["ticker"], entry["name"]
        print(f"  {ticker} — {name}")

        # Sector/industry come from the same cached .info payload the card already uses,
        # so this costs no extra yfinance call on a warm cache.
        fundamentals = fetch_fundamentals_cached(ticker)
        business = _ask(
            BUSINESS_QUESTION,
            fact_context(
                ticker=ticker, name=name,
                sector=fundamentals.sector, industry=fundamentals.industry,
                price=entry["price"], currency=fundamentals.currency,
            ),
            max_chars=BUSINESS_MAX_CHARS,
        )

        # fetch_press_lines swallows its own failures and returns [] — a dead feed means
        # "no headlines", which the summariser is told to answer honestly.
        headlines = fetch_press_lines(name, limit=_HEADLINE_LIMIT, width=140)
        news_summary = _ask(
            NEWS_QUESTION, news_context(headlines), max_chars=NEWS_MAX_CHARS
        ) if headlines else None

        save_insight(
            args.db, ticker=ticker, generated_at=now, business=business,
            news_summary=news_summary, headlines=headlines, model=OLLAMA_MODEL,
        )

        try:
            dates, closes = fetch_year_closes(ticker)
            series = downsample_closes(dates, closes)
            save_price_series(
                args.db, ticker=ticker, as_of=now,
                first_date=series["first_date"], last_date=series["last_date"],
                closes=series["closes"],
            )
        except Exception as exc:  # noqa: BLE001 - yfinance is rate-limited and flaky
            print(f"    kein Kursverlauf: {type(exc).__name__}: {exc}", file=sys.stderr)

    print("Fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke-test it against the live DB with two stocks**

```bash
.venv/bin/python scripts/run_insights.py --limit 2
```

Expected: two `  TICKER — Name` lines and `Fertig.`, no traceback. Then verify what landed:

```bash
.venv/bin/python -c "
from equity_scout.insights_storage import load_insights, load_price_series
ins, ser = load_insights('equity_scout.db'), load_price_series('equity_scout.db')
for t, row in ins.items():
    print(t, '| business:', row['business'])
    print('   news:', row['news_summary'])
    print('   headlines:', len(row['headlines']), '| closes:', len(ser.get(t, {}).get('closes', [])))
"
```

Expected: a German business sentence per ticker, and 60 closes. If `business` is None, Ollama is not reachable — fix Task 1 before continuing.

- [ ] **Step 4: Add the step to the daily chain**

In `scripts/daily_copilot.sh`, insert directly after the `radar` step (it needs the fresh watchlist) and before `earnings`:

```bash
step radar               "$PY" scripts/run_radar.py
# Phone-card AI texts + 1y sparkline series for the top watchlist names. Needs the
# fresh watchlist above; needs Ollama up (scripts/install_ollama_service.sh). ~12
# stocks x 2 warm LLM calls ~ 2-3 min, so it sits before the slower evidence steps.
step insights            "$PY" scripts/run_insights.py --limit 12
```

Also extend the chain description comment at the top of the file:

```bash
# Daily copilot chain: (Mondays: screener first) -> radar -> insights -> earnings ->
# evidence -> notify -> score watchlist -> resolve predictions -> resolve evidence ->
# resolve events -> lanes -> digest.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/run_insights.py scripts/daily_copilot.sh
git commit -m "feat(insights): nightly runner for AI texts and 1y series, wired into the daily chain"
```

---

### Task 5: `/api/briefs` serves the cache

**Files:**
- Modify: `src/equity_scout/briefs.py:51-89`
- Modify: `src/equity_scout/api.py:324-352`
- Test: `tests/test_briefs.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_briefs.py`:

```python
# --- insight + chart pass-through (2026-08-05) ------------------------------------

def test_build_brief_passes_the_insight_through():
    brief = build_brief(
        _entry(), Fundamentals(None, None, None, None),
        insight={
            "generated_at": "2026-08-05T18:00:00+00:00",
            "business": "Baut Speicherchips.",
            "news_summary": "Prognose angehoben.",
            "headlines": ["Guidance raised"],
            "model": "qwen2.5:7b",
        },
        chart={
            "as_of": "2026-08-05T18:00:00+00:00",
            "first_date": "2025-08-05",
            "last_date": "2026-08-05",
            "closes": [10.0, 12.0],
        },
    )
    assert brief["insight"]["business"] == "Baut Speicherchips."
    assert brief["insight"]["headlines"] == ["Guidance raised"]
    assert brief["chart"]["closes"] == [10.0, 12.0]


def test_build_brief_without_an_insight_is_an_honest_null():
    # Nothing generated yet (fresh DB, or a stock outside the generator's top-N).
    brief = build_brief(_entry(), None)
    assert brief["insight"] is None
    assert brief["chart"] is None


def test_briefs_endpoint_serves_the_cached_insight(tmp_path, monkeypatch):
    """Same seams as test_briefs_endpoint_orders_and_survives_one_bad_ticker above:
    the `_watchlist_entry` helper, `api_mod.create_app(str(db))`, and the CACHED
    fundamentals wrapper patched so the test never touches the network."""
    import equity_scout.api as api_mod

    from equity_scout.insights_storage import save_insight, save_price_series

    db = tmp_path / "insights_api.db"
    save_watchlist(str(db), Watchlist(
        created_at="2026-08-05T20:30:00",
        entries=[_watchlist_entry(ticker="MU", name="Micron Technology", in_zone=True)],
    ))
    save_insight(
        str(db), ticker="MU", generated_at="2026-08-05T18:00:00+00:00",
        business="Baut Speicherchips.", news_summary="Prognose angehoben.",
        headlines=["Guidance raised"], model="qwen2.5:7b",
    )
    save_price_series(
        str(db), ticker="MU", as_of="2026-08-05T18:00:00+00:00",
        first_date="2025-08-05", last_date="2026-08-05", closes=[10.0, 12.0],
    )
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda ticker: Fundamentals(None, None, None, None),
    )

    client = TestClient(api_mod.create_app(str(db)))
    payload = client.get("/api/briefs").json()["briefs"]
    assert payload[0]["insight"]["business"] == "Baut Speicherchips."
    assert payload[0]["chart"]["closes"] == [10.0, 12.0]


def test_briefs_endpoint_serves_a_null_insight_for_an_ungenerated_stock(tmp_path, monkeypatch):
    """A stock outside the generator's top-N must not break the card."""
    import equity_scout.api as api_mod

    db = tmp_path / "no_insights.db"
    save_watchlist(str(db), Watchlist(
        created_at="2026-08-05T20:30:00",
        entries=[_watchlist_entry(ticker="AAA")],
    ))
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda ticker: Fundamentals(None, None, None, None),
    )

    client = TestClient(api_mod.create_app(str(db)))
    payload = client.get("/api/briefs").json()["briefs"]
    assert payload[0]["insight"] is None
    assert payload[0]["chart"] is None
```

Note: the existing `test_briefs_endpoint_caps_the_limit` in this file asserts `limit=999` still returns 20. Raising the *default* from 5 to 12 leaves that hard cap untouched, so it stays green — verify that in Step 5 rather than assuming it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_briefs.py -q`
Expected: FAIL — `build_brief() got an unexpected keyword argument 'insight'`.

- [ ] **Step 3: Extend `build_brief`**

In `src/equity_scout/briefs.py`, change the signature and add the two fields. Replace the `def build_brief(entry: dict, fundamentals: Fundamentals | None) -> dict:` line with:

```python
def build_brief(
    entry: dict,
    fundamentals: Fundamentals | None,
    *,
    insight: dict | None = None,
    chart: dict | None = None,
) -> dict:
```

Extend the docstring with:

```
    `insight`/`chart` are the pre-generated caches from insights_storage (nightly
    `scripts/run_insights.py`). Both default to None: a fresh DB, or a stock outside the
    generator's top-N, renders an honest "noch nicht erzeugt" rather than blocking the
    card on a 5-second LLM call.
```

and add to the returned dict, after `"model_stop": None,`:

```python
        # Pre-generated, never computed here: see the docstring.
        "insight": insight,
        "chart": chart,
```

- [ ] **Step 4: Wire the endpoint**

In `src/equity_scout/api.py`, add the import next to the other `equity_scout` imports:

```python
from equity_scout.insights_storage import load_insights, load_price_series
```

Then in `/api/briefs`, change the default limit and join the caches. Replace `def briefs(limit: int = 5) -> JSONResponse:` with:

```python
    @app.get("/api/briefs")
    def briefs(limit: int = 12) -> JSONResponse:
```

and replace the `return JSONResponse({...})` at the end of that endpoint with:

```python
        # Two cheap keyed reads instead of a query per row: the caches are small
        # (one row per top-N ticker) and this endpoint is hit on every app open.
        insights = load_insights(db_path)
        series = load_price_series(db_path)

        return JSONResponse({
            "briefs": [
                build_brief(
                    e, f,
                    insight=insights.get(e["ticker"]),
                    chart=series.get(e["ticker"]),
                )
                for e, f in zip(top, fetched)
            ],
            "disclaimer": DISCLAIMER,
        })
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_briefs.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full Python gate**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .`
Expected: all green. Note: `tests/test_entry_model.py::test_calibrated_model_scores_through_the_calibrator` is a known pre-existing flake (documented 2026-08-04) — if only that one fails, re-run it in isolation to confirm, and leave it alone.

- [ ] **Step 7: Commit**

```bash
git add src/equity_scout/briefs.py src/equity_scout/api.py tests/test_briefs.py
git commit -m "feat(api): serve cached AI texts and the 1y series with each brief"
```

---

## Phase B — the stock tab (Tasks 6–8)

### Task 6: The 1-year sparkline

**Files:**
- Create: `frontend/src/sparkline.ts`
- Create: `frontend/src/sparkline.test.ts`
- Create: `frontend/src/components/MiniYearChart.tsx`
- Modify: `frontend/src/index.css`

Own SVG from our own data, not the existing TradingView widget (design constraint 7): it works with WSL off, it is dark, and it adds no external script to a private app.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/sparkline.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { sparklinePath, yearReturnPct } from "./sparkline";

describe("sparklinePath", () => {
  it("spans the full width and pins the extremes to the padded box", () => {
    const path = sparklinePath([10, 20], { width: 100, height: 40, pad: 2 });
    // First point at x=0, last at x=width; the low sits at the bottom, the high at the top.
    expect(path).toBe("M 0 38 L 100 2");
  });

  it("draws a flat series through the vertical middle instead of dividing by zero", () => {
    const path = sparklinePath([5, 5, 5], { width: 100, height: 40, pad: 2 });
    expect(path).toBe("M 0 20 L 50 20 L 100 20");
  });

  it("returns an empty path for fewer than two points", () => {
    expect(sparklinePath([], { width: 100, height: 40, pad: 2 })).toBe("");
    expect(sparklinePath([7], { width: 100, height: 40, pad: 2 })).toBe("");
  });
});

describe("yearReturnPct", () => {
  it("computes the return from the real endpoints", () => {
    expect(yearReturnPct([100, 150])).toBe(50);
  });

  it("is null without enough data or with a non-positive start", () => {
    expect(yearReturnPct([100])).toBeNull();
    expect(yearReturnPct([0, 50])).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './sparkline'`.

- [ ] **Step 3: Write the geometry module**

Create `frontend/src/sparkline.ts`:

```typescript
// Pure geometry for the 1-year price line on the phone card. Separate from the component
// so the maths is testable without a DOM, the same split ZoneBar/zone.ts already uses.

export interface Box {
  width: number;
  height: number;
  /** Vertical breathing room so the extreme points are not clipped by the stroke. */
  pad: number;
}

/** SVG path through the series, scaled to the box. "" for fewer than two points. */
export function sparklinePath(closes: number[], box: Box): string {
  if (closes.length < 2) return "";
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min;
  const usable = box.height - 2 * box.pad;
  return closes
    .map((close, i) => {
      const x = (i / (closes.length - 1)) * box.width;
      // A flat series has no span to scale against — centre it rather than divide by zero.
      const y = span === 0
        ? box.height / 2
        : box.pad + (1 - (close - min) / span) * usable;
      return `${i === 0 ? "M" : "L"} ${round(x)} ${round(y)}`;
    })
    .join(" ");
}

function round(value: number): number {
  // Two decimals keep the path string short without a visible kink at this size.
  return Math.round(value * 100) / 100;
}

/** Whole-percent return between the first and last close, or null when undefined.
 *  The backend guarantees these two are the real endpoints, not downsampled neighbours. */
export function yearReturnPct(closes: number[]): number | null {
  if (closes.length < 2 || closes[0] <= 0) return null;
  return Math.round((closes[closes.length - 1] / closes[0] - 1) * 100);
}
```

- [ ] **Step 4: Write the component**

Create `frontend/src/components/MiniYearChart.tsx`:

```tsx
import type { StockChart } from "../api";
import { sparklinePath, yearReturnPct } from "../sparkline";

// One year of closes as an inline SVG from OUR data (nightly scripts/run_insights.py) —
// not the TradingView widget StockChart.tsx embeds on desktop. Three reasons: the service
// worker can cache this so the card still draws with WSL off, it inherits the dark
// cockpit instead of forcing colorTheme "light", and a private cockpit should not load a
// third-party script on every card open.
const BOX = { width: 300, height: 64, pad: 3 } as const;

export function MiniYearChart({
  chart,
  currency,
}: {
  chart: StockChart | null;
  currency: string | null;
}) {
  if (!chart || chart.closes.length < 2) {
    return <p className="brief-muted">Kein Kursverlauf gespeichert.</p>;
  }
  const path = sparklinePath(chart.closes, BOX);
  const change = yearReturnPct(chart.closes);
  const up = (change ?? 0) >= 0;
  const label =
    change === null
      ? "1 Jahr — kein Vergleichswert"
      : `1 Jahr ${change > 0 ? "+" : change < 0 ? "−" : ""}${Math.abs(change)} %`;

  return (
    <figure className="yearchart">
      <svg
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        // Width comes from CSS; the box is a coordinate system, not a pixel size.
        preserveAspectRatio="none"
        className={up ? "yearchart-svg up" : "yearchart-svg down"}
        // aria-hidden because the caption below states the same fact as text. Without it a
        // screen reader inside the row's <button> would read the shape's label and the
        // caption twice (the mistake ZoneBar shipped with and fixed on 2026-08-04).
        aria-hidden="true"
      >
        <path d={path} fill="none" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className={up ? "brief-good" : "brief-warn"}>
        {label}
        <span className="brief-muted">
          {" "}
          · {chart.first_date} → {chart.last_date}
          {currency ? ` · ${currency}` : ""}
        </span>
      </figcaption>
    </figure>
  );
}
```

- [ ] **Step 5: Add the styles**

Append to `frontend/src/index.css`:

```css
/* ===== 1-year sparkline (2026-08-05) ===== */
.yearchart {
  margin: 0;
}
.yearchart-svg {
  width: 100%;
  height: 64px;
  display: block;
}
.yearchart-svg.up path {
  stroke: var(--good, #34d399);
}
.yearchart-svg.down path {
  stroke: var(--warn, #fbbf24);
}
.yearchart figcaption {
  font-size: 0.74rem;
  margin-top: 2px;
}
```

Before committing, confirm `--good` and `--warn` exist in `index.css`'s `:root` (`grep -n "\-\-good\|\-\-warn" frontend/src/index.css`). Fallbacks are supplied; if the project uses different names, use those instead of adding new variables.

- [ ] **Step 6: Run the frontend gate**

Run: `cd frontend && npm test && npm run typecheck && npm run build`
Expected: PASS / exit 0 / build ok.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/sparkline.ts frontend/src/sparkline.test.ts \
        frontend/src/components/MiniYearChart.tsx frontend/src/index.css
git commit -m "feat(frontend): inline 1-year sparkline from our own price cache"
```

---

### Task 7: Two sections and the potential headline number

**Files:**
- Create: `frontend/src/stocklist.ts`
- Create: `frontend/src/stocklist.test.ts`
- Modify: `frontend/src/api.ts:986-1016`
- Modify: `frontend/src/components/StockList.tsx`
- Modify: `frontend/src/index.css`

Design constraint 3: one list cannot serve both "our signal says buyable" and "highest potential" — measured, the top row of our ranking has **−7 %** potential. Two labelled sections, our own signal first.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/stocklist.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { StockBrief } from "./api";
import { splitSections } from "./stocklist";

function brief(over: Partial<StockBrief>): StockBrief {
  return {
    ticker: "AAA", name: "AAA Inc.", sector: null, industry: null, currency: "USD",
    price: 100, score: 40, score_band: "mittel", zone_low: 90, zone_high: 110,
    in_zone: false, zone_gap_pct: 0, zone_verdict: "", analyst_target: null,
    analyst_count: null, analyst_upside_pct: null, trailing_pe: null,
    model_target: null, model_stop: null, insight: null, chart: null,
    ...over,
  };
}

describe("splitSections", () => {
  it("puts in-zone stocks in the entry section, best score first", () => {
    const { inZone } = splitSections([
      brief({ ticker: "LOW", in_zone: true, score: 30 }),
      brief({ ticker: "HIGH", in_zone: true, score: 60 }),
      brief({ ticker: "OUT", in_zone: false, score: 90 }),
    ]);
    expect(inZone.map((b) => b.ticker)).toEqual(["HIGH", "LOW"]);
  });

  it("ranks the potential section by upside, highest first", () => {
    const { potential } = splitSections([
      brief({ ticker: "MID", analyst_upside_pct: 30 }),
      brief({ ticker: "TOP", analyst_upside_pct: 69 }),
      brief({ ticker: "LOWP", analyst_upside_pct: 9 }),
    ]);
    expect(potential.map((b) => b.ticker)).toEqual(["TOP", "MID", "LOWP"]);
  });

  it("never shows the same stock in both sections", () => {
    // MU is in the potential list; if it were also in-zone it must appear only once.
    const both = brief({ ticker: "MU", in_zone: true, analyst_upside_pct: 69 });
    const { inZone, potential } = splitSections([both]);
    expect(inZone.map((b) => b.ticker)).toEqual(["MU"]);
    expect(potential.map((b) => b.ticker)).toEqual([]);
  });

  it("excludes stocks without coverage from the potential section", () => {
    // A missing analyst target is not a potential of zero — it is unknown.
    const { potential } = splitSections([brief({ ticker: "AIRT", analyst_upside_pct: null })]);
    expect(potential).toEqual([]);
  });

  it("excludes negative upside from the potential section", () => {
    // "Potenzial −7 %" under a heading that promises potential is a contradiction; the
    // number still shows on the stock's own card, just not as a potential highlight.
    const { potential } = splitSections([brief({ ticker: "9064.T", analyst_upside_pct: -7 })]);
    expect(potential).toEqual([]);
  });

  it("caps the potential section at four rows", () => {
    const many = Array.from({ length: 9 }, (_, i) =>
      brief({ ticker: `T${i}`, analyst_upside_pct: 10 + i }),
    );
    expect(splitSections(many).potential).toHaveLength(4);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './stocklist'`.

- [ ] **Step 3: Write the module**

Create `frontend/src/stocklist.ts`:

```typescript
// How the phone's stock tab is divided. Measured on 2026-08-05, the funnel's own order
// (in-zone first, then score) puts a −7 % analyst upside in row one and +69 % in row
// three — so one list cannot answer both "what is buyable now" (our signal) and "what
// has potential" (third-party consensus). Two labelled sections keep both honest and
// keep the fremde Meinung from outranking our own.
import type { StockBrief } from "./api";

// Four rows is one thumb-scroll on a 390 px screen; more turns the highlight into a list.
const POTENTIAL_ROWS = 4;

export interface Sections {
  /** Our own signal: the price sits inside the support-derived entry zone. */
  inZone: StockBrief[];
  /** Highest analyst upside among the stocks NOT already shown above. */
  potential: StockBrief[];
}

export function splitSections(briefs: StockBrief[]): Sections {
  const inZone = briefs
    .filter((b) => b.in_zone)
    .sort((a, b) => b.score - a.score);

  const potential = briefs
    .filter((b) => !b.in_zone)
    // A null upside means no coverage, not zero potential; a negative one contradicts
    // the heading. Both stay visible on their own card, just not as a highlight.
    .filter((b) => b.analyst_upside_pct !== null && b.analyst_upside_pct > 0)
    .sort((a, b) => (b.analyst_upside_pct ?? 0) - (a.analyst_upside_pct ?? 0))
    .slice(0, POTENTIAL_ROWS);

  return { inZone, potential };
}
```

- [ ] **Step 4: Extend the API types**

In `frontend/src/api.ts`, add above `export interface StockBrief`:

```typescript
// Pre-generated by the nightly scripts/run_insights.py — never computed in the request
// (a warm local LLM call is ~5.6 s). null means "not generated yet", which the card says.
export interface StockInsight {
  generated_at: string;
  business: string | null;
  news_summary: string | null;
  headlines: string[];
  model: string | null;
}

export interface StockChart {
  as_of: string;
  first_date: string;
  last_date: string;
  /** Downsampled 1-year closes; first and last are the real endpoints. */
  closes: number[];
}
```

Add to `StockBrief`, after `model_stop: number | null;`:

```typescript
  insight: StockInsight | null;
  chart: StockChart | null;
```

And raise the default in `fetchBriefs` — the phone shows two sections now, so five rows is not enough to fill them:

```typescript
export async function fetchBriefs(limit = 12): Promise<BriefsResponse> {
```

- [ ] **Step 5: Rewrite `StockList.tsx` around the two sections**

Replace the whole body of `frontend/src/components/StockList.tsx` with:

```tsx
import { useEffect, useState } from "react";

import { fetchBriefs, type StockBrief } from "../api";
import { shortCompanyName } from "../company";
import { splitSections } from "../stocklist";
import { MiniYearChart } from "./MiniYearChart";
import { StockLogo } from "./StockLogo";
import { ZoneBar } from "./ZoneBar";

// Answers the questions Nico actually has on one daily look (2026-08-05: "auf den ersten
// Blick Potenzial plus dreißig Prozent"): which company is this, what is the potential,
// would this be a good price — then, one tap deeper, what would a good entry be, what do
// the numbers say, what happened over the year, and what is in the news.
//
// Deliberately NOT a "hot stocks" list: the ranking is value/quality from the funnel, and
// the potential is third-party analyst consensus — never our own forecast. The two
// sections keep those two things apart (see ../stocklist.ts).

function money(value: number, currency: string | null): string {
  // de-DE grouping so 1915.5 reads as 1.915,50 next to German labels. The currency code
  // stays as a code (JPY/USD) rather than a symbol: mixing $ and ¥ glyphs at this size is
  // harder to tell apart than three letters.
  const formatted = value.toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency ? `${formatted} ${currency}` : formatted;
}

function signedPct(value: number): string {
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)} %`;
}

/** The headline number. Big on purpose — it is the reason to look at all — but it is a
 *  third-party opinion, so the label under it says so instead of a legend elsewhere. */
function PotentialBlock({ brief }: { brief: StockBrief }) {
  if (brief.analyst_upside_pct === null || brief.analyst_target === null) {
    return (
      <span className="brief-potential brief-potential-none">
        <span className="brief-potential-num">—</span>
        <span className="brief-potential-label">keine Analystenschätzung</span>
      </span>
    );
  }
  const up = brief.analyst_upside_pct >= 0;
  return (
    <span className={up ? "brief-potential brief-good" : "brief-potential brief-warn"}>
      <span className="brief-potential-num num">
        {signedPct(brief.analyst_upside_pct)}
      </span>
      <span className="brief-potential-label">
        laut {brief.analyst_count ?? "?"} Analysten
      </span>
    </span>
  );
}

function ZoneLine({ brief }: { brief: StockBrief }) {
  // The verdict already reads as plain German from the backend ("im Einstiegsbereich",
  // "59 % über der Zone — zu teuer"); colour only reinforces it.
  const cls = brief.in_zone ? "brief-zone brief-good" : "brief-zone brief-warn";
  return (
    <span className={cls}>
      {brief.in_zone ? "✓" : "⚠"} {brief.zone_verdict}
    </span>
  );
}

function BriefRow({ brief }: { brief: StockBrief }) {
  const [open, setOpen] = useState(false);
  const business = [brief.sector, brief.industry].filter(Boolean).join(" · ");

  return (
    <li className="brief-row">
      <button className="brief-main" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <StockLogo ticker={brief.ticker} name={brief.name} />
        <span className="brief-body">
          <span className="brief-head">
            <span className="brief-name" title={brief.name}>
              {shortCompanyName(brief.name)}
            </span>
            <span className="brief-ticker">{brief.ticker}</span>
          </span>
          {business && <span className="brief-business">{business}</span>}
          <PotentialBlock brief={brief} />
          <span className="brief-price num">{money(brief.price, brief.currency)}</span>
          <ZoneBar brief={brief} />
          <ZoneLine brief={brief} />
        </span>
      </button>
      {open && (
        <div className="brief-detail-wrap">
          <MiniYearChart chart={brief.chart} currency={brief.currency} />
          <dl className="brief-detail">
            <dt>Guter Einstieg</dt>
            <dd className="num">
              {money(brief.zone_low, null)}–{money(brief.zone_high, brief.currency)}
            </dd>
            <dt>Analysten-Ziel</dt>
            <dd className="num">
              {brief.analyst_target === null
                ? "— keine Schätzung"
                : money(brief.analyst_target, brief.currency)}
            </dd>
            <dt>Einstiegs-Score</dt>
            <dd>
              {brief.score}/100 ({brief.score_band})
            </dd>
            <dt>KGV</dt>
            <dd className="num">
              {brief.trailing_pe === null ? "—" : brief.trailing_pe.toFixed(1)}
            </dd>
            <dt>Modell-Kursziel</dt>
            <dd>
              {brief.model_target === null
                ? "— kein trainiertes Modell"
                : money(brief.model_target, brief.currency)}
            </dd>
          </dl>
          <BriefInsight brief={brief} />
        </div>
      )}
    </li>
  );
}

/** The two AI texts. Labelled as machine-written, because they are — and dated, because
 *  a summary of last week's headlines read as today's news would be misleading. */
function BriefInsight({ brief }: { brief: StockBrief }) {
  const insight = brief.insight;
  if (!insight) {
    return (
      <p className="brief-muted brief-insight">
        Noch keine KI-Zusammenfassung erzeugt (läuft im 18:00-Lauf).
      </p>
    );
  }
  const when = new Date(insight.generated_at).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
  });
  return (
    <div className="brief-insight">
      {insight.business && <p className="brief-insight-business">{insight.business}</p>}
      {insight.news_summary ? (
        <p className="brief-insight-news">📰 {insight.news_summary}</p>
      ) : (
        <p className="brief-muted">Keine aktuellen Schlagzeilen gefunden.</p>
      )}
      {insight.headlines.length > 0 && (
        <ul className="brief-headlines">
          {insight.headlines.map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      )}
      <p className="brief-muted brief-insight-foot">
        KI-Zusammenfassung ({insight.model ?? "lokal"}) vom {when} — keine Empfehlung.
      </p>
    </div>
  );
}

export function StockList({ limit = 12, onOpen }: { limit?: number; onOpen?: () => void }) {
  const [briefs, setBriefs] = useState<StockBrief[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let ignore = false;
    fetchBriefs(limit)
      .then((r) => {
        if (!ignore) setBriefs(r.briefs);
      })
      .catch(() => {
        if (!ignore) setFailed(true);
      });
    return () => {
      ignore = true;
    };
  }, [limit]);

  if (failed) return <p className="brief-muted">Aktien-Daten nicht erreichbar.</p>;
  if (briefs === null) return <p className="brief-muted">lädt …</p>;
  if (briefs.length === 0) {
    return <p className="brief-muted">Noch keine Watchlist — der Screener lief noch nicht.</p>;
  }

  const { inZone, potential } = splitSections(briefs);

  return (
    <>
      <h3 className="brief-section-head">Jetzt im Einstiegsbereich</h3>
      {inZone.length > 0 ? (
        <ul className="brief-list">
          {inZone.map((brief) => (
            <BriefRow key={brief.ticker} brief={brief} />
          ))}
        </ul>
      ) : (
        <p className="brief-muted">
          Heute liegt kein Titel in seiner Einstiegszone — das ist ein Ergebnis, kein Fehler.
        </p>
      )}

      {potential.length > 0 && (
        <>
          <h3 className="brief-section-head">
            Höchstes Potenzial
            <span className="brief-muted"> · laut Analysten, nicht unser Modell</span>
          </h3>
          <ul className="brief-list">
            {potential.map((brief) => (
              <BriefRow key={brief.ticker} brief={brief} />
            ))}
          </ul>
        </>
      )}

      {onOpen && (
        <button className="stock-more" onClick={onOpen}>
          Alle im Radar →
        </button>
      )}
    </>
  );
}
```

- [ ] **Step 6: Add the styles**

Append to `frontend/src/index.css`:

```css
/* ===== Phone stock card: potential headline + sections (2026-08-05) ===== */
.brief-section-head {
  margin: var(--space-4) 0 var(--space-2);
  font-size: 0.92rem;
  font-weight: 600;
}
.brief-section-head .brief-muted {
  font-weight: 400;
  font-size: 0.78rem;
}
/* The potential is the reason to open the app at all — it gets the largest type on the
   row. The label directly under it carries the attribution, so the big number can never
   be read as our own forecast. */
.brief-potential {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.brief-potential-num {
  font-size: 1.5rem;
  font-weight: 650;
  line-height: 1.1;
}
.brief-potential-label {
  font-size: 0.72rem;
  color: var(--text-muted);
}
.brief-potential-none .brief-potential-num {
  color: var(--text-muted);
}
.brief-detail-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.brief-insight-business {
  margin: 0;
  font-size: 0.9rem;
}
.brief-insight-news {
  margin: 0;
  font-size: 0.9rem;
}
.brief-headlines {
  margin: 0;
  padding-left: 1.1em;
  font-size: 0.78rem;
  color: var(--text-muted);
}
.brief-insight-foot {
  margin: 0;
  font-size: 0.7rem;
}
```

- [ ] **Step 7: Run the frontend gate**

Run: `cd frontend && npm test && npm run typecheck && npm run build`
Expected: PASS / exit 0 / build ok. `MiniYearChart` comes from Task 6, so it must be done before this gate can pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/stocklist.ts frontend/src/stocklist.test.ts frontend/src/api.ts \
        frontend/src/components/StockList.tsx frontend/src/index.css
git commit -m "feat(frontend): lead the stock card with potential and split entry vs potential"
```

---

### Task 8: Verify the stock tab on a phone viewport

**Files:** none (verification only)

Screenshots, not assumptions — the 2026-08-04 round found four layout defects this way that no test caught.

- [ ] **Step 1: Build and serve**

```bash
cd frontend && npm run build && npm run preview
```

Print the URL. In DevTools set the viewport to **390 × 844**.

- [ ] **Step 2: Check the list**

Confirm, in this order:
1. "Jetzt im Einstiegsbereich" appears first with the in-zone stocks.
2. Each row shows logo, company name, then the potential as the largest number with "laut N Analysten" under it.
3. "Höchstes Potenzial" follows, with the "laut Analysten, nicht unser Modell" note in the heading.
4. **No horizontal scrolling anywhere** (the 2026-08-04 defect). Drag the page sideways to be sure.
5. A stock without coverage shows "—" and "keine Analystenschätzung", not "0 %".

- [ ] **Step 3: Check the detail**

Tap a row. Confirm: the sparkline draws with a 1-year label, the entry range and the numbers are readable, the AI business sentence and news summary appear with the "KI-Zusammenfassung … keine Empfehlung" footer, and the headline list is present.

If no AI text appears, check `.venv/bin/python -c "from equity_scout.insights_storage import load_insights; print(load_insights('equity_scout.db').keys())"` — an empty result means Task 4's runner has not run for those tickers.

- [ ] **Step 4: Check the desktop did not regress**

Widen past 720 px. The sidebar is back, the sections still read correctly, and the sparkline is not stretched into an empty rail (the ZoneBar's 2026-08-04 defect — if it is, add a `max-width` to `.yearchart` inside the desktop block).

---

## Phase C — the autotrader tab (Task 9)

### Task 9: `PhoneDepot` — holdings and trades on one screen

**Files:**
- Create: `frontend/src/components/PhoneDepot.tsx`
- Modify: `frontend/src/components/DepotsView.tsx`
- Modify: `frontend/src/index.css`

No backend work: `/api/autodepot` and `/api/shortterm` already carry everything. But the
two traders are shaped differently, and the payloads were read before writing this task:

- **The long-term auto-depot trades ETFs, not single stocks.** `account.weights` is an
  allocation over 11 ETFs (live 2026-08-05: `SPY .10, IEF .10, VEU .10, BIL .094, XLE .042,
  XLK .042, XLV .042, TLT .031, GLD .031, DBC .021`). "Current depot" therefore means
  allocation, and `AutodepotTrade` has **no** `side`/`qty`/`price` — it is
  `{created_at, ticker, delta_weight, notional, cost}` plus `fill`, `fill_price` and
  `decided_as_of` from the v13 next-open convention. Single stocks with logos exist only in
  the short-term lanes.
- **The trade list is full of micro-rebalances.** Live example: `GLD` with
  `delta_weight` 1.39e-05 = **1.40 $**. Unfiltered, the phone list is noise — the same
  problem the digest solved on 2026-08-04. Use `digest.MATERIAL_DELTA_WEIGHT` (0.01), and
  keep the small ones reachable behind a toggle: the binding rule from that session is that
  nothing may be dropped from Telegram that the dashboard does not show.
- **Field names differ between the two.** Lane trades use `executed_at`, depot trades use
  `created_at`. The response type is `ShortTermResponse` (capital T), and lanes are
  `ShortTermLane[]` with `open_positions: ShortTermPosition[]` (`ticker`, `qty`,
  `entry_price`, `opened_at`) and `recent_trades: ShortTermTrade[]` (`executed_at`,
  `ticker`, `side`, `qty`, `price`, `fees`, `reason`, `realized_pnl`).

- [ ] **Step 1: Add the two missing fields to the TS interface**

`/api/autodepot` returns `fill_convention` and per-trade fill data that `frontend/src/api.ts`
does not declare yet (`api.py:459-497`). In `frontend/src/api.ts`, extend `AutodepotTrade`:

```typescript
export interface AutodepotTrade {
  created_at: string;
  ticker: string;
  delta_weight: number;
  notional: number;
  cost: number;
  // v13 next-open fills: "open" when the trade filled at the following session's open,
  // "close_fallback" when no open existed. Absent on rows written before v13.
  fill?: string | null;
  fill_price?: number | null;
  decided_as_of?: string | null;
}
```

and add to `AutodepotResponse`, next to `trades`:

```typescript
  fill_convention?: string;
```

- [ ] **Step 2: Write the component**

Create `frontend/src/components/PhoneDepot.tsx`:

```tsx
import { useEffect, useState } from "react";

import {
  fetchAutodepot,
  fetchShortterm,
  type AutodepotResponse,
  type AutodepotTrade,
  type ShortTermLane,
  type ShortTermResponse,
} from "../api";
import { StockLogo } from "./StockLogo";

// The phone's answer to "what did my traders do?" (Nico 2026-08-05): what each trader
// holds right now and which trades got it there — long-term auto-depot and the short-term
// lanes on one screen. The desktop DepotsView keeps its seven tabs; six panels of
// paper-depot detail is a laptop layout, and hunting one number across tabs defeats a
// daily glance.
//
// The two traders are NOT symmetric and are not drawn as if they were: the auto-depot
// holds an ETF allocation and rebalances weights, the lanes hold single stocks with a
// quantity and an entry price. All of it is paper money.
//
// MUST stay equal to digest.MATERIAL_DELTA_WEIGHT (src/equity_scout/digest.py:34). A
// weight change below this is a rounding rebalance — live example GLD at 1.4e-05 = 1.40 $.
// The small ones stay reachable behind a toggle, because the digest's rule is that nothing
// leaves Telegram which the dashboard does not show.
const MATERIAL_DELTA_WEIGHT = 0.01;

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  const p = value * 100;
  return `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toFixed(digits)} %`;
}

function money(value: number): string {
  return value.toLocaleString("de-DE", { maximumFractionDigits: 0 });
}

/** DD.MM — on a phone row the day is what orients you, the year never changes mid-list. */
function dayOf(iso: string): string {
  const [, month, day] = iso.slice(0, 10).split("-");
  return month && day ? `${day}.${month}.` : "—";
}

export function PhoneDepot() {
  const [auto, setAuto] = useState<AutodepotResponse | null>(null);
  const [short, setShort] = useState<ShortTermResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let ignore = false;
    Promise.all([fetchAutodepot(), fetchShortterm()])
      .then(([a, s]) => {
        if (!ignore) {
          setAuto(a);
          setShort(s);
        }
      })
      .catch(() => {
        if (!ignore) setFailed(true);
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (failed) return <p className="brief-muted">Depot-Daten nicht erreichbar.</p>;
  if (!auto || !short) return <p className="brief-muted">lädt …</p>;

  const account = auto.available ? auto.account : undefined;
  const lanes = short.available ? short.lanes : [];

  return (
    <div className="phone-depot">
      <h3 className="brief-section-head">Langfrist · Auto-Depot</h3>
      {account ? (
        <>
          <div className="pd-kpis">
            <span>
              <b className="num">{money(account.equity)}</b>
              <small>Depotwert</small>
            </span>
            <span>
              <b className={account.total_return >= 0 ? "brief-good num" : "brief-warn num"}>
                {pct(account.total_return)}
              </b>
              <small>seit Start</small>
            </span>
            <span>
              <b className="num">{pct(account.benchmark_return)}</b>
              <small>{account.benchmark_ticker}</small>
            </span>
          </div>
          <p className="brief-muted pd-stamp">
            Stand {account.last_as_of ?? "—"}
            {auto.fill_convention ? ` · Fills ${auto.fill_convention}` : ""}
          </p>

          <h4 className="pd-sub">Aktuelle Aufteilung</h4>
          <Allocation weights={account.weights} equity={account.equity} />

          <h4 className="pd-sub">Letzte Umschichtungen</h4>
          <RebalanceList trades={auto.trades ?? []} />
        </>
      ) : (
        <p className="brief-muted">
          Noch kein Auto-Depot — der nächtliche Lauf hat es noch nicht angelegt.
        </p>
      )}

      <h3 className="brief-section-head">Kurzfrist · Arena-Lanes</h3>
      {lanes.length > 0 ? (
        lanes.map((lane) => <LaneCard key={lane.lane} lane={lane} />)
      ) : (
        <p className="brief-muted">Noch keine Lane-Bücher angelegt.</p>
      )}
    </div>
  );
}

/** The ETF allocation as a weight bar per holding — this IS the long-term "depot". */
function Allocation({
  weights,
  equity,
}: {
  weights: Record<string, number>;
  equity: number;
}) {
  const rows = Object.entries(weights)
    .filter(([, weight]) => Math.abs(weight) > 0)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (rows.length === 0) return <p className="brief-muted">Keine Allokation gebucht.</p>;
  const invested = rows.reduce((sum, [, weight]) => sum + weight, 0);
  const largest = Math.max(...rows.map(([, weight]) => Math.abs(weight)));

  return (
    <>
      <ul className="pd-alloc">
        {rows.map(([ticker, weight]) => (
          <li key={ticker}>
            <span className="pd-alloc-ticker">{ticker}</span>
            {/* Bars are scaled to the LARGEST holding, not to 100 %: at a 10 % maximum
                every bar would otherwise be a sliver and comparing them impossible. */}
            <span className="pd-alloc-bar" aria-hidden="true">
              <span style={{ width: `${(Math.abs(weight) / largest) * 100}%` }} />
            </span>
            <span className="num pd-alloc-num">{pct(weight)}</span>
            <span className="num brief-muted">{money(weight * equity)}</span>
          </li>
        ))}
      </ul>
      <p className="brief-muted pd-stamp">
        {pct(invested)} investiert · Rest Kasse
      </p>
    </>
  );
}

/** Depot rebalances: material ones named, rounding ones counted behind a toggle. */
function RebalanceList({ trades }: { trades: AutodepotTrade[] }) {
  const [showSmall, setShowSmall] = useState(false);
  if (trades.length === 0) return <p className="brief-muted">Noch keine Trades gebucht.</p>;

  const material = trades.filter((t) => Math.abs(t.delta_weight) >= MATERIAL_DELTA_WEIGHT);
  const small = trades.length - material.length;
  const shown = showSmall ? trades : material.slice(0, 8);

  return (
    <>
      {shown.length > 0 ? (
        <ul className="pd-trades">
          {shown.map((t, i) => (
            <li key={`${t.created_at}-${t.ticker}-${i}`}>
              <span className="pd-trade-day">{dayOf(t.created_at)}</span>
              <span className={t.delta_weight >= 0 ? "brief-good" : "brief-warn"}>
                {t.delta_weight >= 0 ? "auf" : "ab"}
              </span>
              <span className="pd-trade-ticker">{t.ticker}</span>
              <span className="num">
                {pct(t.delta_weight)} · {money(t.notional)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="brief-muted">
          Keine wesentliche Umschichtung — nur Rundungs-Rebalances.
        </p>
      )}
      {small > 0 && (
        <button className="pd-toggle" onClick={() => setShowSmall((s) => !s)}>
          {showSmall ? "kleine Rebalances ausblenden" : `+ ${small} kleine Rebalances zeigen`}
        </button>
      )}
    </>
  );
}

/** One short-term lane: return, the single stocks it holds, and its last trades. */
function LaneCard({ lane }: { lane: ShortTermLane }) {
  return (
    <div className="pd-lane">
      <div className="pd-lane-head">
        <b>{lane.lane}</b>
        <span className={lane.total_return >= 0 ? "brief-good num" : "brief-warn num"}>
          {pct(lane.total_return)}
        </span>
        <span className="brief-muted num">{money(lane.equity)}</span>
        {lane.promoted && <span className="pd-badge">handelt ein echtes Sleeve</span>}
      </div>
      {lane.open_positions.length > 0 ? (
        <ul className="pd-positions">
          {lane.open_positions.map((p) => (
            <li key={p.ticker}>
              <StockLogo ticker={p.ticker} name={p.ticker} />
              <span className="pd-trade-ticker">{p.ticker}</span>
              <span className="num">
                {p.qty} @ {p.entry_price.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="brief-muted">keine offene Position</p>
      )}
      {lane.recent_trades.length > 0 ? (
        <ul className="pd-trades">
          {lane.recent_trades.slice(0, 5).map((t, i) => (
            <li key={`${t.executed_at}-${t.ticker}-${i}`}>
              <span className="pd-trade-day">{dayOf(t.executed_at)}</span>
              <span className={t.side.toLowerCase().startsWith("b") ? "brief-good" : "brief-warn"}>
                {t.side}
              </span>
              <span className="pd-trade-ticker">{t.ticker}</span>
              <span className="num">
                {t.qty} @ {t.price.toFixed(2)}
              </span>
              {t.realized_pnl !== null && (
                <span className={t.realized_pnl >= 0 ? "brief-good num" : "brief-warn num"}>
                  {t.realized_pnl >= 0 ? "+" : "−"}
                  {Math.abs(t.realized_pnl).toFixed(0)}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="brief-muted">noch keine Trades</p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Render it on the phone only**

In `frontend/src/components/DepotsView.tsx`, add the import:

```tsx
import { PhoneDepot } from "./PhoneDepot";
```

and wrap the existing tab bar plus panels so the phone gets the compact view instead. Replace the `return (` block's contents from `<div className="tabbar wrap">` down to the last panel line with:

```tsx
      {/* Phone: one screen, the two questions. Desktop: the seven-tab detail below.
          CSS decides which one is visible, so both render — the payloads are the same
          two endpoints either way, so there is no double fetch cost worth a media query
          hook here. */}
      <div className="only-phone">
        <PhoneDepot />
      </div>

      <div className="only-desktop">
        <div className="tabbar wrap">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={tab === t.key ? "tab active" : "tab"}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
          {tab === "gesamt" && <TimeContextBadge kind="paper" />}
          {tab === "arena" && <TimeContextBadge kind="paper" />}
          {tab === "screener" && <TimeContextBadge kind="paper" />}
          {(tab === "forward" || tab === "bots" || tab === "autodepot" || tab === "shortterm") && (
            <TimeContextBadge kind="forward" />
          )}
        </div>

        {tab === "gesamt" && <OverviewPanel />}
        {tab === "arena" && <ArenaPanel embedded />}
        {tab === "screener" && <ScreenerDepot />}
        {tab === "forward" && <ForwardPanel include={(name) => !name.startsWith("ML ")} />}
        {tab === "bots" && (
          <ForwardPanel
            include={(name) => name.startsWith("ML ")}
            emptyHint="Die ML-Bots handeln erst, wenn ihre Modell-Familie einen promoteten Champion hat — kein nachgewiesener Edge, kein Trade. Das nächtliche Training (nightly_train.sh) registriert und promotet Kandidaten."
            botNote
          />
        )}
        {tab === "autodepot" && <AutoDepotPanel />}
        {tab === "shortterm" && <KurzfristArenaPanel />}
      </div>
```

- [ ] **Step 4: Add the styles**

Append to `frontend/src/index.css`:

```css
/* ===== Phone autotrader view (2026-08-05) ===== */
/* One breakpoint pair for "phone only" / "desktop only" content. 720 px is the same
   threshold the bottom nav uses — one number, not two that can drift apart. */
.only-phone {
  display: none;
}
@media (max-width: 720px) {
  .only-phone {
    display: block;
  }
  .only-desktop {
    display: none;
  }
}
.pd-kpis {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}
.pd-kpis span {
  display: flex;
  flex-direction: column;
}
.pd-kpis b {
  font-size: 1.1rem;
}
.pd-kpis small {
  font-size: 0.7rem;
  color: var(--text-muted);
}
.pd-stamp {
  font-size: 0.72rem;
  margin: var(--space-1) 0 0;
}
.pd-sub {
  margin: var(--space-3) 0 var(--space-1);
  font-size: 0.82rem;
}
.pd-lane {
  border-top: 1px solid var(--border-soft);
  padding-top: var(--space-2);
  margin-top: var(--space-2);
}
.pd-lane-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.pd-badge {
  font-size: 0.66rem;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  color: var(--text-muted);
}
.pd-alloc,
.pd-positions,
.pd-trades {
  list-style: none;
  margin: var(--space-1) 0 0;
  padding: 0;
  font-size: 0.8rem;
}
.pd-alloc li,
.pd-positions li,
.pd-trades li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px 0;
}
.pd-alloc-ticker {
  min-width: 3.4em;
  font-weight: 600;
}
/* The weight bar carries no meaning the numbers next to it do not also carry (it is
   aria-hidden), so it may be purely decorative — it exists to make "which holding is
   large" answerable without reading five percentages. */
.pd-alloc-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--border-soft);
  overflow: hidden;
}
.pd-alloc-bar span {
  display: block;
  height: 100%;
  background: var(--accent);
}
.pd-alloc-num {
  min-width: 3.6em;
  text-align: right;
}
.pd-toggle {
  margin-top: var(--space-1);
  padding: 0;
  border: 0;
  background: none;
  color: var(--accent);
  font-size: 0.76rem;
  /* 44 px tap target without a visible box: the row above it is already dense. */
  min-height: 44px;
}
.pd-trade-day {
  color: var(--text-muted);
  min-width: 3.2em;
}
.pd-trade-ticker {
  flex: 1;
  /* Long international tickers must wrap rather than push the price off-screen. */
  overflow-wrap: break-word;
}
```

- [ ] **Step 5: Run the frontend gate**

Run: `cd frontend && npm test && npm run typecheck && npm run build`
Expected: PASS / exit 0 / build ok.

- [ ] **Step 6: Verify on both viewports**

Run `npm run preview`, open the app with `?view=depots`.

At **390 × 844**, confirm in order:
1. Auto-depot KPIs (Depotwert / seit Start / benchmark), then "Aktuelle Aufteilung" with one bar per ETF — the largest bar is full width, and the percentages sum to the "investiert" line.
2. "Letzte Umschichtungen" shows only weight changes ≥ 1 %, with a "+ N kleine Rebalances zeigen" toggle below. Tap it: the micro rows (e.g. GLD at 0,0 % / 1 $) appear.
3. Each lane shows its return, its open positions with logo and `qty @ entry`, and its last trades with realised P&L.
4. **No horizontal scrolling** anywhere, and no tab bar.

Past **720 px**: the seven tabs are back and the compact view is gone.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/PhoneDepot.tsx frontend/src/components/DepotsView.tsx \
        frontend/src/index.css
git commit -m "feat(frontend): compact phone view for the autotrader depots and trades"
```

---

## Phase D — ship it (Task 10)

### Task 10: Full gate, live deploy, documentation

**Files:**
- Modify: `README.md`
- Create: `docs/sessions/2026-08-05_phone-cockpit-insights.md`
- Modify: `AUTOPILOT_LOG.md`
- Modify: `docs/superpowers/plans/2026-08-05-phone-cockpit-insights-and-autotrader.md` (this file — Outcome section)

- [ ] **Step 1: Run the full gate**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .
cd frontend && npm test && npm run typecheck && npm run build && cd ..
```

Expected: all green. Record the actual test counts — they go in the outcome doc. The known `test_entry_model` flake is the one permitted exception (confirm in isolation).

- [ ] **Step 2: Generate for real and deploy**

```bash
.venv/bin/python scripts/run_insights.py --limit 12
./scripts/install_dash_service.sh
```

The service restart is required: `/api/briefs` gained fields, and `StaticFiles` serves the new `dist/` per request but the Python process is long-lived.

Then verify the live payload carries the new fields:

```bash
curl -s -H "X-Dash-Token: $(grep -oP '(?<=^DASH_TOKEN=).*' .env)" \
  http://127.0.0.1:8420/api/briefs | .venv/bin/python -c "
import json, sys
data = json.load(sys.stdin)['briefs']
print(len(data), 'briefs')
for b in data[:3]:
    ins = b['insight'] or {}
    print(b['ticker'], '| upside', b['analyst_upside_pct'], '| chart',
          len((b['chart'] or {}).get('closes', [])), '| business:', (ins.get('business') or '—')[:60])
"
```

Expected: 12 briefs, 60 closes and a German business sentence on the top rows.

- [ ] **Step 3: Print the phone URL**

```bash
grep -oP '(?<=^DASH_URL=).*' .env
```

Print it for Nico together with the reminder that the token is already in his cookie from the 2026-08-04 walk-through.

- [ ] **Step 4: Update the README**

In `README.md`'s phone-cockpit section, document: the two stock sections and why they are split (our signal vs third-party consensus), that "Potenzial" is analyst consensus and never a model target, that the AI texts and the sparkline come from the nightly `run_insights` step (so a fresh DB shows honest "noch nicht erzeugt"), that Ollama runs as a user service (`scripts/install_ollama_service.sh`) and what happens without it, and that the phone depot view is a compact render of the same two endpoints the desktop tabs use.

- [ ] **Step 5: Write the session doc**

Create `docs/sessions/2026-08-05_phone-cockpit-insights.md` covering: Nico's target picture in his own words, the three decisions from the top of this plan, the measurements that shaped the design (LLM latency, analyst coverage 11/12, the ranking-vs-potential contradiction), what was built, what the phone verification showed, deviations from this plan, and what is still open.

- [ ] **Step 6: Append one line to `AUTOPILOT_LOG.md`**

Follow the file's existing one-line-per-round style, e.g.:

```
- 2026-08-05 phone cockpit: nightly insights step (Ollama user service, business+news texts, 1y series cached per ticker), /api/briefs serves both, stock tab split into Einstiegsbereich vs Potenzial with the analyst upside as the headline number + inline sparkline, compact PhoneDepot for the autotrader tab; N tests
```

- [ ] **Step 7: Fill in this plan's Outcome section and commit**

```bash
git add README.md docs/sessions/2026-08-05_phone-cockpit-insights.md AUTOPILOT_LOG.md \
        docs/superpowers/plans/2026-08-05-phone-cockpit-insights-and-autotrader.md
git commit -m "docs: record the phone cockpit insights and autotrader view"
```

---

## Deliberately not built

- **No news term in the funnel score.** Nico's decision 2. Making news move the ranking is a funnel change, and by this project's own rules that needs its own ledger and DSR hurdle before it may claim an edge. Today's honest statement is "here is what the news says", not "the news improved the pick".
- **No model price target.** `entry.compute_target_stop` needs a registered `entry_tb` champion; none exists. The card keeps saying "kein trainiertes Modell" rather than dressing the analyst number up as ours.
- **No live LLM call from the phone.** Measured 5.6 s warm, 27 s cold. A spinner that long on a card is worse than a text that is a day old and dated.
- **No LLM in the theme detection.** `evidence/news_themes.py` counts deterministically on purpose so a theme traces back to its headlines; this plan does not put a model in front of it.
- **No TradingView on the phone card.** External script, light theme, dead when WSL is off.
- **No new endpoint for the phone depot.** `/api/autodepot` and `/api/shortterm` already carry holdings and trades; a third endpoint would be a second place for the same numbers to drift.
- **No Web Push from the app.** Telegram stays the nudge (decision 3); Web Push would need a public endpoint and VAPID keys for a cockpit that is Tailscale-only.

---

## Outcome (2026-08-05)

**Alle 10 Tasks umgesetzt und live verifiziert.** Gate: **1314 Python-Tests grün**,
`ruff check .` clean, **46 vitest-Tests grün**, `tsc --noEmit` exit 0, Build ok,
`dist/sw.js` + Manifest ausgeliefert. Live über Tailscale: 401 ohne Token, 200 mit,
`/api/briefs` liefert 12 Briefs, **12 mit KI-Text und 12 mit 60-Punkt-Chart**.

Ein Nachlauf auf dem kombinierten Stand (eine parallele Session committete zwischen
23:16 und 23:33 auf denselben Branch, also nach meinem Gate um 23:29) ergab
**1318 passed, 1 failed**: der am 04.08. dokumentierte Flake
`test_entry_model::test_calibrated_model_scores_through_the_calibrator` (`11 + 88 = 99`
statt 100), isoliert 3× grün nachgeprüft. Betrifft ML-Training, nicht diese Arbeit.

Screenshots auf 390 × 844 (Chromium aus dem Playwright-Cache): beide Tabs ohne
horizontales Scrollen, Sortierung +69/+64/+38/+32, Detail mit Sparkline, Kennzahlen und
KI-Texten; Desktop bei 1440 px unverändert.

### Abweichungen

- **Kein `sys.path`-Anker in `run_insights.py`** (Task 4 verlangte ihn): geprüft, dass das
  Muster nur für `from scripts.<sibling> import …` nötig ist. `equity_scout` ist editable
  installiert, also wäre der Anker toter Code mit irreführendem Kommentar.
- **CSS-Tokens hießen anders**: real `--positive`, `--warning`, `--bg-surface` (der Plan
  nannte `--good`, `--warn`, `--surface`). Vor dem Schreiben geprüft, keine neuen Variablen
  angelegt.
- **Task 6 und 7 getauscht** (schon im Plan korrigiert): `StockList` importiert
  `MiniYearChart`, die Sparkline muss zuerst existieren.
- **`TodayViews` Überschrift „Aktuell vorne" entfernt** — mit den zwei neuen
  Sektions-Überschriften darunter war sie eine gestapelte Dopplung. Nicht im Plan.
- **Zwei Fixes, die der Plan nicht vorsah**, beide in der gebauten Fläche:
  - `clean_company_query` lieferte für „Yamato Holdings Co., Ltd." nur „Yamato", worauf die
    News-Zusammenfassung drei fremde TSE-Listings beschrieb; gleichzeitig kosteten die
    Nasdaq-Listing-Suffixe 4 von 12 Titeln ALLE Schlagzeilen. Nach dem Fix 12/12, Yamato
    trifft TSE:9064. Ein bestehender Test kodierte den Defekt und wurde umgeschrieben.
  - NaN als letzter Jahres-Close (9064.T, 9022.T) setzte `/api/briefs` komplett auf 500 —
    die Endpunkt-Zusicherung pinnte den NaN fest, `json.dumps` schrieb ihn als ungültiges
    Literal. Jetzt vor dem Sampling verworfen, `save_price_series` mit `allow_nan=False`.
  - Stückzahlen als 16-stellige Rohfloats brachen die Handy-Handelszeilen mitten im Token
    („sel l", „BT C"); jetzt vier signifikante Stellen plus Umbruch-Ausnahmen.
- **Modellwahl gemessen**: `llama3.1:8b` war 52,8 s statt 7,1 s und ignorierte den Prompt.
  `qwen2.5:7b` bleibt.

### Offen

Walk-Through am Handy durch Nico; die holprige Qualität des lokalen 7B-Deutsch (Optionen
brauchen seine Entscheidung, weil eine bezahlte API die private Kostengrenze berührt); kein
Modell-Kursziel ohne registrierten `entry_tb`-Champion.

Details: `docs/sessions/2026-08-05_phone-cockpit-insights-and-autotrader.md`.
