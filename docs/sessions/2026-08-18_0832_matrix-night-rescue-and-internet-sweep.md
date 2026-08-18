# Session 2026-08-18 08:32 — Matrix-Nachtrettung, externes Gutachten & Internet-Vollsweep

## Kontext & Ziel

Nico wollte (1) die Markt-Matrix-Vision („alle Parameter × alle Zeitscheiben, damit reich
werden") kritisch aus vielen Perspektiven durchlöchern lassen — Basis war
`Markt-Matrix-Vision-externe-Bewertung.md` aus Downloads —, (2) danach die Direktive verankern,
dass das Ziel GESETZT ist (volle Passion, „wie schaffen wir es" statt „ob"), inklusive tiefer
Code-Inspektion und externer Recherche, und (3) „das ganze Internet durchforsten" nach allem,
was an Strategien kursiert. Parallel lief die erste große Matrix-Nachtkette.

## Ergebnis

1. **Externes Gutachten geliefert** (Chat, Runde 1): alle 8 Gutachterfragen beantwortet;
   Kernpunkte: Kapital-Arithmetik (Alpha auf 5k macht nicht reich — Gehalt/Sparquote schon),
   Plateau-Regel schützt nicht gegen korrelierte Nachbarzellen, Hebel erst nach gesichertem
   Erwartungswert (Prompt widersprach dem eigenen Doc).
2. **Direktive verankert**: Memory `equity-scout-autotrader-ambition` — Ziel als erreichbar
   behandeln, Gates bleiben Werkzeug FÜR das Ziel, kein Generalzweifel mehr.
3. **NACHT-RETTUNG** (der eigentliche Kern der Session): Die Kette vom 17.08. war seit 23:12
   deadlocked (pgrep-Selbstmatch eines Alt-Waiters, der zudem `run_signal_matrix.py` OHNE Flags
   gestartet hätte → Hold-out-Öffnung), und die Bars waren RAW (10 Split-Sprünge −66…−95 %,
   Dividenden-Fake-Gaps). 13 Befunde, 11 in der Nacht gefixt — 5 Commits `54fc46a`, `7c6221a`,
   `a68f0f2`, `0c1f210`, `92a8260` (+ Registry `bd205cc`), Gate: volle Suite grün, ruff clean.
   Details: `docs/research/2026-08-18-external-review-and-upgrade-plan.md` §1.
   Rohdaten-Backup: `data/minutes-raw-2026-08-17/`.
4. **Nachtkette KOMPLETT durchgelaufen** (06:50, 0 FAILED): 62,98 Mio adjustierte Minutenbars
   (76 min Re-Download), 262.953 News-Artikel dedupliziert, Matrix-Zellen Tiefe 1 (70 Ticker,
   `data/matrix_cells.jsonl` 4,2 GB), Tiefe 2 (70, `_d2.jsonl` 30,7 GB), Tiefe 3 (12 Leader,
   `_d3.jsonl` 26,2 GB), News-Latenz-Messung gelaufen. **Hold-out UNGEÖFFNET** (beide Ketten
   bewusst `--phase cells`). Dünn-Ticker-Gate und Sentinel-Resume nachweislich aktiv (CPER 51,
   PPLT 125 Bars/Tag → nur Swing-Scheiben).
5. **Internet-Vollsweep** (5 parallele Recherche-Agents: Foren, Social/ICT, Quant-Blogs,
   Akademik, Code-Ökosystem) → **Strategie-Registry**
   `docs/research/2026-08-18-strategy-registry-internet-sweep.md`: ~60 Kandidaten dedupliziert,
   gemappt (neu/Variante/abgedeckt/widerlegt/Scam), Wellen-Plan 5a/5b/6, Scam-Filter,
   Dauerquellen. Stärkste Funde: Market Intraday Momentum (Gao/Han/Li/Zhou + Baltussen-46J),
   Same-Time-of-Day-Autokorrelation, konditionaler Overnight (TugOfWar), VWAP-Familie (fehlt
   komplett in der Matrix), IBS (3× unabhängig genannt), ICT-Falsifikationspaket.

## Entscheidungen

- **Report-Phase/Hold-out auf heute verschoben**, weil das gepoolte t Unabhängigkeit der 70
  Ticker unterstellt (bis ~6× zu groß) — das Hold-out wird nicht an aufgeblähte Statistik
  ausgegeben.
- **`adjustment="all"`** (Splits+Dividenden) statt raw — Total-Return-Pfad ist für Preis-P&L
  korrekt; Halbtage per Alpaca-Börsenkalender gekappt.
- **Stichprobenboden gesplittet**: 20/Ticker (Reporting) + 200/gepoolte Zelle (Evidenz, in
  `qualifying_cells`) — der alte 200er-Ticker-Boden hatte 1D/1W/1M strukturell stummgeschaltet.
- **Latenz-Anker auf Bar-Opens** umgestellt — der alte Close-Anker lag ~90 s NACH dem Wire,
  before(0) war konstruktiv 0.
- **F-Score fliegt aus dem alten Welle-5-Plan** (HXZ-Replikation: FAIL) — ersetzt durch Asset
  Growth + Net Issuance.

## Offene Fragen

- **News-Latenz-Urteil noch nicht angeschaut** (Doc wurde in Welle 1 geschrieben,
  `docs/research/2026-08-18-news-latency-decay.md`) — erste echte Antwort auf die Scraping-Frage.
- Composer-Symphonies + Bensdorp-Systeme: Recherche-Lücken (WebSearch-Kontingent war ab Strang 2
  erschöpft; Foren-Strang teils als [T]=Trainingswissen gekennzeichnet).
- Kongress-Befund (t=−51,6): Pseudo-Replikation vermutet — Reanalyse mit Titel+Monat-Clustering
  und Delisting-Check steht aus.

## To-dos

### Nico

1. **Push-Entscheidung**: `autopilot/work` ist ~27 Commits vor origin (inkl. der ganzen
   Nacht-Fixes) — sag Bescheid, ob ich pushen soll.
2. **Registry lesen** (`docs/research/2026-08-18-strategy-registry-internet-sweep.md`) und Go
   für Welle 5a geben (neue Matrix-Detektoren: Intraday-Momentum, VWAP, IBS, ICT-Paket …).
3. Altlasten aus früheren Sessions: Telegram-Bot-Token + DASH_TOKEN rotieren.

### Nächste Session (Agent)

1. **Pooling-Härtung** (VOR jeder Report-Öffnung): Kandidaten-Trades mit Zeitstempeln
   nachberechnen, Kalenderzeit-Block-Bootstrap, `arch`-MCS/SPA über Kandidaten; Details
   `docs/research/2026-08-18-external-review-and-upgrade-plan.md` §2.
2. Dann `--phase report` **EINMAL** je Checkpoint (Tiefe 1/2/3), mit Hold-out-Register
   (vorher anlegen: wer öffnet wann, welche Hypothesen).
3. Jeder Plateau-Kandidat zusätzlich: Entry@`open[i+1]`-Variante + Corwin-Schultz-Kosten
   pro Trade (beide Prüfungen sind Pflicht, sonst kein Kandidatenstatus).
4. News-Latenz-Doc lesen und Urteil einordnen (Drop-Zähler beachten: nur Intraday-News gemessen).
5. Danach Welle 5a aus der Registry vorregistrieren (nur nach Nicos Go).

## Einstieg für die nächste Session

Branch `autopilot/work` (~27 unpushed), alle Checkpoints liegen in `data/matrix_cells*.jsonl`
(61 GB, Hold-out unberührt). Zuerst `docs/research/2026-08-18-external-review-and-upgrade-plan.md`
§2 lesen (die zwei offenen Statistik-Löcher), dann Pooling-Härtung bauen (writing-plans lohnt —
das ist ein eigener kleiner Plan), erst danach die Report-Phase einmalig öffnen. Die
Strategie-Registry ist die Hypothesen-Warteschlange für alles Weitere.
