# Session 2026-08-11 00:02 — W0 historischer Abgleich + Fear & Greed

## Kontext & Ziel

Nico: „mach mit dem Autotrader weiter da gabs handoff, prüf erstmal die erkenntnisse bzgl wonach
menschen kaufen gegen die Historie ob das zutrifft" — also **W0**, der Gate-Schritt, den die
Vorsession als wichtigste Lücke hinterlassen hatte. Mitten in der Session nachgeschoben:
„Werden die Punkte mehr die menschen zu verstehen …? Bspw auch mit sowas wie fear and greed index".

## Ergebnis

**Die Erkenntnisse der Indikator-Landkarte halten der eigenen Historie nicht stand.**

140 Tests (77 roh + 63 inkrementell), 11 Signale × 7 Ziele, bis zu 19 Jahre, Bonferroni-korrigiert
auf α = 0,00036:

- **Kein einziger Kandidat sagt die Marktrendite voraus.** Kein Treffer, in keiner Variante.
- Was trägt, sagt **Risiko** voraus (Folgevola, Drawdown) — 6 Treffer.
- **0 von 63 inkrementellen Tests.** Nach Abzug dessen, was VIX-Level und Marktbreite schon
  sagen, bleibt bei keinem Kandidaten etwas übrig.
- **W1 (VIX-Terminstruktur) ist damit gestrichen** — roh stark (Vola-Spread +11,02 %,
  p < 0,0001), inkrementell nichts (Rank-IC 0,51 → 0,08). Sie wäre eine zweite Datenquelle für
  eine Aussage gewesen, die die Ampel schon trifft.
- **Fear & Greed ist erledigt.** 5 seiner 7 Zutaten standen schon im Test; die 3 neuen
  (Momentum, Safe-Haven, Junk-Bond) bringen nichts, und **der Komposit ist schwächer als seine
  beste Einzelzutat** (Momentum allein p < 0,0001 / IC 0,38 → gemittelt p = 0,0036 / IC 0,18).
  Das Mitteln verwässert das starke Signal mit schwachen.

**Die härteste Zahl ist kein Treffer, sondern eine Grenze:** Auflösbar sind hier erst monatliche
Rendite-Unterschiede **ab 3,47 %** (80 % Testmacht, korrigiertes Niveau, günstigster Fall).
Baker-Wurgler berichten 0,9 % — das wäre in unseren Daten **strukturell unsichtbar**, dafür
bräuchte es ~275 Jahre Historie. **Die Rendite-Frage ist an unseren Daten nicht entscheidbar, die
Risiko-Frage ist es.** Jedes künftige Verhaltenssignal muss sich über die Risiko-Schiene
rechtfertigen.

Commits auf `autopilot/work` (4, nicht gepusht), Gate grün: **1983 pytest + ruff sauber**.

- `febf750` feat(study): das Messwerkzeug `behaviour_study.py` + 26 Tests + `run_behaviour_study.py`
- `ccddd02` docs(research): W0-Auswertung + Landkarte revidiert + `data/behaviour_study.json`
- `3c52a2e` docs(study): Auflösungsgrenze als bester Fall gekennzeichnet
- `7532009` feat(study): Fear & Greed gemessen

Doku: `docs/research/2026-08-11-w0-historical-check-behavioural-indicators.md` (volle Auswertung),
`docs/research/2026-08-11-behavioural-indicator-landscape.md` (W0 abgehakt, W1 gestrichen,
W2/W3 herabgestuft, Baker-Wurgler-Ableitung mit Nachtrag korrigiert).

## Entscheidungen

- **Risiko als eigenständige Zielgröße** neben der Rendite: Einbauort wäre die
  Exposure-Drosselung, dort zahlt sich Risikovorhersage auch ohne Renditevorhersage aus. Hätte
  man nur Renditen getestet, wäre der einzige messbare Effekt gar nicht aufgetaucht.
- **Signifikanz nur auf nicht überlappenden Fenstern.** Tägliche Beobachtungen eines 21-Tage-
  Forwards teilen 20 von 21 Tagen; als unabhängig behandelt bläht das jede t-Statistik um ~√h auf.
  Der überlappende Rank-IC steht daneben, ausdrücklich als deskriptiv markiert.
- **Startpunkt-Sweep ins Verdict aufgenommen** (`MIN_OFFSET_SHARE = 0,5`), nachdem er einen
  eigenen Treffer zerlegt hat — siehe unten.
- **Residualisierung als Bau-Kriterium.** Ein Kandidat verdient seinen Platz nur über den Teil,
  den die Bestandssignale nicht schon enthalten. Die rohe Korrelation beantwortet eine Frage, die
  niemand hat: dass zwei Angstmesser übereinstimmen, ist keine Nachricht.
- **F&G nachgebaut statt abgerufen:** CNNs Endpunkt liefert wenige Jahre, der Nachbau 19 — und
  keine Abhängigkeit von einer Quelle, die verschwinden kann.
- **Junk-Bond als HYG-gegen-LQD-Proxy**, weil FREDs freier CSV-Endpunkt für `BAMLH0A0HYM2` nur
  ~3 Jahre liefert (n = 12 bei 63 Tagen = nicht beurteilbar). Als Proxy verrauschter, so notiert.
- **Produktions-Preispanel NICHT angefasst.** `etf_panel.csv` startet 2018-06 wegen XLC; die
  Studie hält sich stattdessen einen eigenen spaltenweisen Snapshot der Sleeve. Ein Eingriff dort
  hätte alle Backtests berührt.

## Zwei Funde, die die Methodik erzwungen hat

1. **Ein eigener Treffer war ein Artefakt.** Der OBV-Trend trug zunächst deutlich (Vola 21T
   p = 0,0003). Die Stichprobe kann an 22 gleichwertigen Stellen beginnen — der Befund hielt bei
   **9 %** davon. VIX und Marktbreite halten bei 86–100 %. Ohne den Sweep wäre OBV als Treffer
   berichtet worden.
2. **Das Volumen-Panel war elf Jahre zu kurz** (Start 2018 statt 2007, ohne Grund). Das drittelte
   die Aussagekraft jedes Volumentests. Neu gezogen ab 2007-01: alte Zeilen bit-identisch zurück
   (0 Abweichung über 45.381 Zellen), 2770 Zeilen dazu. Backup lag im Scratchpad, Datei ist
   gitignored. Erst dadurch war der OBV-Befund sichtbar — und erst dadurch widerlegbar.

## Offene Fragen

- **Mi 12.08.: erste `entry_predictions`-Auflösungen prüfen** (`run_evidence_refresh.py`). Der
  Wave-1-Plan hat den Selbst-Check hinterlegt: wenn dann immer noch `resolved = 0`, ist der
  Resolve-Loop kaputt und das hat Vorrang. **Gilt nur für `entry_predictions`** —
  `evidence_predictions` lösen erst ab 08.09. auf.
- Trägt Cross-Sectional Momentum (v16, Backtest-Sharpe 1,00) forward? n ist weiter 0.
- Der `insights`-Schritt der Tageskette passt nicht in sein 12-Minuten-Budget (per Timeout
  abgeschnitten). Erst einen Einzelaufruf messen, dann `--limit` senken oder eigener Cron-Slot.
- Rest v16-Welle 2: Kosten-Netting über die Handelsspuren; die Session-Lane nutzt nur 10 % ihres
  Broker-Kapitals.

## To-dos

### Nico

Nico hat die Richtungsentscheidung offen gelassen („mach handoff und erstmal pause"). Zur Wahl
standen — **das ist der erste Punkt der nächsten Session**:

1. **Kosten & Kapitalnutzung** (meine Empfehlung): Kosten-Netting über die Handelsspuren,
   Crypto-Lane auf den Prüfstand (80 bps Taker × 2 Seiten = >1,6 % Bewegung nur für Break-even),
   Session-Lane-Kapital von 10 % hoch. Am gemessenen Hauptverlustgrund, kein Erkenntnisrisiko.
2. **Ziel/Horizont/Universum des Entry-Modells**: der ungetestete Hebel. AUC 0,496 mit 11 wie mit
   14 Spalten heißt, das Problem sitzt in der Zielvariable, nicht in den Features.
3. **Short Interest testen**: einziger Landkarten-Kandidat mit anderem Wirkort (Einzeltitel statt
   Markt, Squeeze-Mechanik). Werkzeug steht, Test wäre schnell — Erwartung: weiterer Nullbefund.
4. **Faktencheck 12.08. vorziehen** (siehe Offene Fragen).

Weiter offen aus der Vorsession, unverändert:

5. `DASH_TOKEN` erneuern (alter liegt in einem Chat-Protokoll).
6. Namensliste der beobachteten Investoren bestätigen (`evidence/voices.py`, 8 Fondsmanager).
7. Cockpit einmal am Handy durchklicken: `http://100.99.224.50:8420` über Tailscale.
8. Server für ~5 €/Monat ja/nein — Begründung ist Verfügbarkeit, nicht Geschwindigkeit. Nichts
   gebucht.
9. `docs/sessions/` ist in diesem Repo **nicht** gitignored, liegt also auf dem öffentlichen
   GitHub. Keine Secrets darin (geprüft), aber Projektinterna und Zitate. `.gitignore` bleibt
   ungefragt unangetastet.

### Nächste Session (Agent)

- **Erst Nicos Richtungsentscheidung abwarten** (Liste oben). Ohne sie nicht ins Blaue bauen.
- **Das W0-Gate gilt unverändert weiter** für jeden neuen Kandidaten: `study_signal` mit
  Runde 1 + Runde 2 (Residualisierung), und ein Nullbefund wird genauso berichtet wie ein Treffer.
  Die Latte liegt jetzt bei „inkrementell auf Risiko" — alles andere ist an unseren Daten nicht
  entscheidbar.
- Kein Cron-Wächter aktiv (CronList leer, session-only Jobs der Vorsession sind ausgelaufen).
  Bei einer Autopilot-Session neu armen.

## Einstieg für die nächste Session

Branch `autopilot/work`, Tree sauber, 4 Commits vor `origin/main`, **nicht gepusht** (Nico hat
nicht darum gebeten). Gate: `uv run pytest -q` (1983) + `uv run ruff check .` — beides grün,
Frontend nicht angefasst.

Erster Blick: `docs/research/2026-08-11-w0-historical-check-behavioural-indicators.md`, dort der
Abschnitt „Grenzen — was dieser Test NICHT zeigt". Die Studie neu rechnen:
`uv run python scripts/run_behaviour_study.py` (~2 min aus den Snapshots, `--refresh` zieht
VIX/Sleeve/Credit neu). Rohzahlen liegen in `data/behaviour_study.json`.

Keine Secrets in dieser Doku; Alpaca-Keys und `DASH_TOKEN` liegen in `.env`.
