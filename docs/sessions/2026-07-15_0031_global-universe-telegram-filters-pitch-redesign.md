# Session 2026-07-14 → 2026-07-15 00:31 — Weltuniversum, Telegram-Umbau, Filter, Pitch-Redesign

## Kontext & Ziel

Startete als Pitch-Frage („was kann das Screening?"), wuchs per Nico-Blanket-Go („arbeite
bis zur Vision") zu fünf Arbeitspaketen in einer Nacht-Session auf `autopilot/work`
(f485371..aa6aec1, ~25 Commits, NICHT gepusht). Gate durchgehend grün, zuletzt 633 Tests
+ ruff + FE-Build.

## Ergebnis

1. **Weltuniversum 6.318 → 7.499** — generische `WikipediaIndexSource` (8 Configs:
   Hang Seng, CSI 300, KOSPI 200, NIFTY 50+Next 50, TSX, ASX 200, B3; Taiwan honest-skipped).
   Spec/Plan: `docs/superpowers/{specs,plans}/2026-07-14-global-universe-*`.
2. **instrument_meta + Prefetch** — Cache-Hit-Sektorverlust gefixt (Overlay + Harvest,
   Regressionstest), nächtliche Prefetch-Rotation (00:45, 6 Segmente), Montags-Scout
   `--cache-max-age 7`. Dazu Live-Fund: **Cache-Vergiftung** durch leere Rate-Limit-Quotes
   → Fix 247c219 (leere Quotes nie speichern/servieren).
3. **Erster Welt-Scan**: 6.117/7.499 geranked (vorher 1.043), Fehlerquote 0,7 %.
   Zweistufig: `run_prefetch --segments 1` (5.120 Fetches, 4.424 Sektoren persistiert)
   → Scout aus warmem Cache.
4. **Telegram final** (2× von Nico revidiert): EIN Chat via neuem Bot
   **@daily_equityscout_bot** (Token in `.env`; alter „Equity Scout Copilot"-Chat stillgelegt).
   **Eine Lieferung täglich 18:00** (daily_copilot), 15-min-Kette ist `--inbox-only`.
   `scripts/setup_telegram.sh` für geführtes Re-Setup. Crontab verifiziert aktuell
   (inkl. */15 intraday, 00:45 prefetch); Installer ist jetzt LINE-MANAGING.
5. **Empfehlungs-Filter** — `run_scores` (volles Ranking je Lauf, 6.117 Zeilen live),
   `country_of` + REGION_GROUPS, `/api/latest?region=&country=&sector=` + `/api/filters`,
   deutsche Filterleiste in FunnelView. Plan-Outcome:
   `docs/superpowers/plans/2026-07-15-recommendation-filters.md`.
6. **Pitch-Redesign v1+v2** — Chart-Foto (1J, matplotlib) + kompakte Caption ≤980
   (Score/KGV/Kurs **inkl. €-Umrechnung** (fx.py)/Zone/Analysten-Ziel/👥 Evidenz/🗞️ bis 2
   **Pressestimmen** (press.py, Google-News RSS)/⚠️ Risiko — **ohne** Anlagerat-/15-min-Footer).
   `send_photo` stdlib-multipart, Decision-Edit-Fallback editMessageText→Caption.
   Daily pitcht **≥5 Namen** (`--min-pitches 5`, Top-up nach Composite).
   Retro-Spec: `docs/superpowers/specs/2026-07-15-pitch-photo-redesign.md`.
   **Live**: 8er-Auswertung als Chart-Pitches gesendet (message_ids 8–15).
7. **Broker-Recherche** (Subagent): Trade Republic = 1 Depot, keine Trennung möglich;
   Trading 212 = Pie als Empfehlungs-Bucket (Empfehlung: Pie + optional Portfolio
   Performance fürs exakte Tracking). Nur im Chat übergeben, nicht im Repo.

## Entscheidungen

- 15-min-Takt statt Nicos „10 min oder so": yfinance-Kurse sind ~15 min verzögert —
  schneller pollen = nur Rate-Limit-Last.
- Disclaimer/Delay-Footer nur aus den privaten Telegram-Captions entfernt; Honesty-Framing
  bleibt in Inbox/Dashboard/README (öffentliches Repo).
- Filter re-scoren nicht: sie selektieren aus dem globalen Ranking (dokumentiert in der Spec).
- ADRs bleiben Region „US" (Listing-Land) — bewusst out of scope, im UI als Hinweis.

## Offene Fragen

- Token-Rotation @daily_equityscout_bot: Token stand im Chat-Verlauf; Rotation empfohlen,
  Nicos Call (BotFather `/revoke` + `./scripts/setup_telegram.sh`).

## To-dos

### Nico

1. Heute 18:00: erstes reguläres Daily im neuen Format prüfen (≥5 Chart-Pitches + Digest).
2. Optional: Bot-Token rotieren (BotFather `/revoke`, dann `./scripts/setup_telegram.sh`).
3. Optional: Trading-212-Pie „Equity Scout Picks" anlegen, wenn du echt tracken willst.
4. `EDGAR_USER_AGENT` in `.env` setzen (ohne: 13F/Form-4-Insider-Quellen bleiben aus).
5. Entscheiden: `autopilot/work` → `main` mergen/pushen (25 Commits warten).
6. Laptop nachts anlassen wo möglich — Prefetch braucht ~6 Nächte für den vollwarmen Cache.

### Nächste Session (Agent)

- **STOXX-Symbol-Fix** (nächstes Paket, im Plan-Outcome dokumentiert): Wikipedia führt
  Reuters-RICs für ~50–100 Titel (BNPP.PA→BNP.PA, DANO.PA→BN.PA, ERICB.ST→ERIC-B.ST …)
  + Leerzeichen-Klassen („AMBU B.CO"→AMBU-B.CO) in `stoxx_yahoo_ticker` — Roche/BNP/Danone
  ranken bisher nur via ADR; 131 EU-Namen gegated.
- Voices-Ticker-Auflösung härten („Micron"→MSN statt MU, `evidence/voices.py`).
- Backlog aus v6: v5-P4 Strategy-Param-Search, DSR-Hurdle, signed resolution bearish calls.

## Einstieg für die nächste Session

Branch `autopilot/work` in `~/private/equity-scout`, Working Tree clean, Gate grün
(`uv run pytest -p no:warnings && uv run ruff check .`). Erster Kandidat: STOXX-Symbol-Fix
(siehe oben; Einstieg `src/equity_scout/data/constituents.py::stoxx_yahoo_ticker`, danach
`scripts/refresh_universe.py` + Commit der neuen CSV). Für neue Feature-Wünsche:
brainstorming → writing-plans wie gehabt; Projektstand komplett im Memory
(`equity-scout-project.md`) und in den Spec-/Plan-Outcomes unter `docs/superpowers/`.
