# Session 2026-08-12 00:29 — Head-Modus-Nacht: Champion-Artefakt, festes Universum, Datenqualität

## Kontext & Ziel

Nico stieg mit „was ist beim Autotrader sache? Mach da mal weiter?" ein, gab dann auf die
Richtungsfrage „Deine Empfehlung, mach einfach" und schließlich „arbeite in einer loop immer
weiter und weiter und weiter. Du bist Head". Ab da lief die Session im Head-Modus mit
Cron-Wächter (alle 23 min, session-only, 7-Tage-Expiry).

Ausgangslage war der offene Punkt der Vorsession: der Mi-12.08.-Faktencheck auf die ersten
`entry_predictions`-Auflösungen und Nicos unbeantwortete Richtungsentscheidung zwischen vier
Optionen.

## Ergebnis

**25 Commits auf `autopilot/work`, NICHT gepusht. Gate zuletzt: 2050 Tests grün, ruff clean.**

Der rote Faden: die Suche nach einem besseren Modell fand einen kaputten Schiedsrichter.

### 1. Der Faktencheck (`a74f6fc`)
Ein Tag vorgezogen, weil die erste Kohorte um 18:52 UTC fällig wurde: **30 von 30 aufgelöst**.
Der Verdacht „Resolve-Loop kaputt", der den ganzen v15-Wave-1-Plan ausgelöst hatte, ist erledigt.
Erste Out-of-Sample-Zahlen aber unerfreulich: 67 % Treffer gegen 77 % Basisrate. Kein Urteil —
alle 30 Zeilen aus EINEM Tag mit korrelierten Titeln.
Doku: `docs/research/2026-08-11-first-resolved-entry-predictions.md`

### 2. Der Champion war ein Messartefakt (`6fdd346`, `06c74ad`)
Der live scorende `entry`-Champion v1 behauptete **AUC 0,6195 aus 220 OOS-Zeilen**; auf dem
heutigen Sample mit 3281 Zeilen liefert er **0,5152**. Er blockierte fünf Wochen lang messbar
bessere Herausforderer, weil die Promotionsregel seine GESPEICHERTE Zahl gegen frische Zahlen aus
einem anderen Sample verglich. Ursache: das Trainingsuniversum war die aktuelle Watchlist, also
wechselte die Stichprobe fast jede Nacht (`n_train` schwankte 80…4806).
Fix: `evaluate_fitted_model` + `promote_if_better(..., incumbent_metric=)`.
Doku: `docs/research/2026-08-11-champion-was-a-measurement-artifact.md`

### 3. Festes ex-ante-Universum → Achse 2 endgültig negativ (`14a76e8`, `547502d`)
`ml/entry_universe.py`: 503 US-Titel aus dem datierten Index-Snapshot `2026-07-02` statt der
Watchlist. **Stichprobe 3.931 → 68.085 Trainingszeilen, 2.431 → 54.735 OOS-Zeilen.**
**Der Vorteil verschwindet mit der Stichprobe: 0 von 12 Presets über der Schwelle**, Spanne
0,4715–0,5069, acht von zwölf mit negativem Rank-IC. Schärfster Beleg: catboost war auf der
Watchlist der beste Herausforderer (0,5433) und liegt hier unter dem Münzwurf.
Laufzeit gemessen und in `nightly_train.sh` dokumentiert: ~15 min gegen 25-min-Cap.
Doku: `docs/research/2026-08-11-fixed-universe-and-the-final-null-result.md`

### 4. Automatische Entthronung (`c771867`) — im Head-Modus entschieden
`demote_if_no_edge`: ein Champion, der als Herausforderer heute abgelehnt würde, verliert den
Titel. Das Prinzip stand wörtlich im Modul-Docstring, galt aber nur beim Eintritt.
**Live-Folge ab dem nächsten Nightly: der ML-Long-Bot handelt nicht mehr.**
Nachverifiziert (`6c54297`): Autotrader-Trockenlauf gegen die entthronte DB-Kopie läuft sauber mit
7 statt 8 Sleeves, Gewichte auf 14,3 % normalisiert. Im selben Lauf **Depot-Brutto 84 %**
bestätigt — der offene v16-Welle-2-Beobachtungspunkt ist damit geschlossen.

### 5. Datenqualität: 79 % der Investoren-Erwähnungen waren falsch (`e3b6c5e`, `4f8b400`, `1ae0599`, `cfc4757`)
Audit aller 296 gespeicherten voice-Events: 79 % trugen einen Ticker, den die Schlagzeile nie
nennt („Aussies **Take** Over" → TTWO, „Who Foots the **Bill**" → BILL, „– Yahoo **Finance**
Singapore" → FOA). Die tragfähige Unterscheidung ist **Wortschatz, nicht Großschreibung**.
Fehlzuordnungen bei den ledger-relevanten Calls **22 → 13**, jeder echte Treffer erhalten.
Dazu: eine Schlagzeile ergibt nur noch EIN Event pro Ticker (Pseudo-Replikation), und
Füllwort-Themen (`buy` war mit 43 Treffern das zweithäufigste „Thema") fallen weg.
Reparaturskript für die Altlast gebaut und am Sessionende auf Nicos Go **ausgeführt** — eigener
Abschnitt weiter unten.

### 6. Bearische Calls zählen jetzt (`8743de4`)
`Call.direction` + Vorzeichenumkehr in `score_persons`. Die Voice-Stichprobe wächst von 15 auf 35
Calls (+133 %), alle Meldungs-Quellen bleiben bit-identisch. Das Ledger bleibt bewusst long-only.

### 7. Ketten-Timeouts (`a2d1196`)
Über 226 protokollierte Läufe gemessen: radar normal 7 s, **einmal 995 s** — das überlief die
15-Minuten-Kadenz. Wichtigerer Fund, der nicht im Backlog stand: **die minütliche Session-Lane
konnte still offline gehen**, weil `flock -n` bei einem Hänger jede Folgeminute überspringt.
Jetzt 55 s gekappt. `run_full_refresh.sh` bewusst ungekappt, per Test gepinnt.

### 8. Erster positiver Befund: VolTarget nutzt den schwächeren Schätzer (`dbd3392`)
`VolTarget` drosselt auf der TRAILING 20-Tage-Vola. Der VIX sagt dieselben 20 Tage besser voraus:
**rho 0,642 gegen 0,539**, inkrementell 0,390 gegen 0,099. Out-of-Sample bestätigt (Divisor auf
2007–2016 gefittet, auf 2017–2026 geprüft: rho 0,678 gegen 0,565, Kalibrierung 1,07).
**Noch nicht eingebaut** — Begründung unten.
Doku: `docs/research/2026-08-12-voltarget-uses-the-weaker-estimator.md`,
Werkzeug: `scripts/run_vol_forecast_study.py`

### 9. Point-in-Time-Fundamentaldaten (`f0f2b13`)
Machbarkeit an einem Ticker geprüft: EDGAR liefert `filed`, 3,8 MB pro Ticker. Zwei stille Fallen
an echten AAPL-Daten gefunden — `fy` ist das Fiskaljahr des FILINGS (ein 10-K trägt drei Perioden
unter derselben `fy`), und Restatements teilen ein Periodenende.
`pit_fundamentals.visible_annual_series` gebaut, gegen echte EDGAR-Daten verifiziert.

## Entscheidungen

- **Entthronung selbst entschieden** (nicht an Nico zurückgegeben), weil das Head-Mandat vorlag,
  es Paper-Geld ist und das Prinzip wörtlich im Code steht.
- **Löschung der 121 Altlast-Zeilen zunächst NICHT selbst ausgeführt** — anders als die
  Entthronung ist sie nicht per Konfiguration umkehrbar, hat keine Frist, und sie entfernt auch
  echte, aber mehrdeutige Erwähnungen. **Nico hat am Sessionende zugestimmt („Löschen
  wahrscheinlich smart"), danach ausgeführt** (eigener Abschnitt unten).
- **Lehren in `LOOP.md` statt nur im Log**, weil LOOP.md jede Autopilot-Iteration liest — ein
  Eintrag im Log wirkt auf nichts.
- **VolTarget-Einbau auf nach der Nightly verschoben**, weil in derselben Nacht die Entthronung
  erstmals wirkt (Sleeve fällt weg, ~32 % Umschichtung). Zwei Eingriffe in einer Nacht hätten die
  Ursachenzuordnung zerstört.
- **Fundamentaldaten parallel begonnen**, weil sie Trainingsdaten betreffen und damit keinen
  Attributionskonflikt erzeugen.
- **Kosten-Netting über Lanes verworfen statt gebaut**: über die Sleeves nettet es längst, über die
  Lanes wäre es falsch (würde jede Lane besser darstellen als sie einzeln ist).

### Eigene Fehler, unterwegs korrigiert
1. **Erster voices-Fix war zu aggressiv** (Title-Case-Erkennung) — er zerstörte echte Signale
   („Michael Burry Adds to DraftKings Stake" → nichts). Vor dem Commit verworfen und durch die
   Wortschatz-Lösung ersetzt; ein Test pinnt beide Seiten.
2. **Dedupe-Wirkung dreifach überzeichnet** (32 % statt der ehrlichen 10 %) — 54 der 80
   Wiederholungen sind die gewollte Wochenrotation.
3. **`#`-Kommentare in einen per `split()` zerlegten Stoppwort-Block** geschrieben — „2026-08-11"
   wäre still zum Stoppwort geworden. Test schließt es aus.
4. **`filing_lag_days` meldete 396 Tage Median** — von Vergleichszahlen dominiert, aussagekräftig
   ist das Minimum (30–34 Tage).
5. **Eine Commit-Message wurde von der Shell verstümmelt** (Backticks in `-m "..."` werden
   ausgeführt). Per `--amend -F datei` repariert. **Regel: Messages mit Backticks immer über `-F`.**

## Offene Fragen

- **Die Nightly um 03:08 ist noch nicht gelaufen.** Sie führt festes Universum und Entthronung
  erstmals live aus. Erwartet: `Trainingsuniversum: 503 Titel`, `ENTTHRONT: v1`, train_entry ~15 min,
  danach ein Depot mit 7 Sleeves und einer einmaligen Umschichtung von ~32 %.
- Bringen Fundamentaldaten etwas, wo vier andere Dimensionen nichts brachten? Offen.
- Wenn nein: ist der Autotrader ein Risiko-System statt eines Alpha-Systems? Das wäre eine
  Projektentscheidung, keine technische.

## Altlast-Bereinigung — AUSGEFÜHRT (Nicos Go am Sessionende)

Nico: „Löschen wahrscheinlich smart". Danach auf der **Produktions-DB** ausgeführt:

```
uv run python scripts/fix_voice_misattributions_2026_08_11.py --apply --backup pre_fix_voices_2026-08-12.db
```

- **Gelöscht: 121 voice-Events + 7 offene Vorhersagen.** `evidence_events` gesamt 1557 → 1436,
  voice-Events 296 → 175, voice-Vorhersagen 15 → 8.
- **Aufgelöste Vorhersagen unangetastet** (es gab keine; der append-only-Vertrag hätte sie
  ohnehin geschützt).
- **Backup: `pre_fix_voices_2026-08-12.db` im Repo-Root, 81 MB, vollständig.** Durch `*.db` in
  `.gitignore` nicht versionierbar. Zurückrollen = Datei über `equity_scout.db` kopieren, aber
  **Achtung: sie ist ein Stand von 00:35 und würde alles Spätere verwerfen** (u. a. die Nightly).
  Nach ein paar ruhigen Tagen löschen.

## To-dos

### Nico

1. **Morgen früh einmal ins Log schauen**, ob die Nacht durchgelaufen ist (`train.log`). Wenn das
   Depot plötzlich stark umgeschichtet hat: das ist erwartet, kein Fehler.
3. **Unverändert offen:** DASH_TOKEN erneuern, Namensliste der beobachteten Investoren bestätigen,
   Cockpit einmal am Handy durchklicken, Server-Frage (~5 €/Monat) ja/nein.
4. **Session-Lane-Kapital:** sie nutzt 10 % ihres Broker-Kapitals. Hochsetzen ändert die
   Positionsgrößen — deine Risikoentscheidung.
5. **Pushen?** 23 Commits liegen auf `autopilot/work` und warten auf dein Wort.

### Nächste Session (Agent)

- **Zuerst die Nightly verifizieren** (`train.log`): `Trainingsuniversum: 503 Titel`, `ENTTHRONT`,
  kein `TIMEOUT train_entry`, Depot mit 7 Sleeves. Erst danach weiterbauen.
- **Dann VolTarget einbauen.** Zwei Pflichten stehen in PLAN.md: dimensionsloser Multiplikator
  (`VIX-Prognose / SPY-trailing`) auf die EIGENE trailing Depot-Vola — nie das SPY-Niveau, das
  Depot ist Multi-Asset — und Rückfall auf die trailing Vola bei VIX-Ausfall.
- **Danach Fundamentaldaten-Backfill** über die 445 Titel (~8 min bei EDGAR-Etikette), dann die
  F-Score-Kriterien additiv ins Entry-Modell, mit demselben Nachweis wie bei Evidenz/Volumen.
- Probeläufe **immer gegen DB-Kopien** im Scratchpad, nie gegen die Produktions-DB.
- **Vor dem Weiterbauen: die Gegenprüfung abwarten** (eigener Abschnitt unten). Ihr Ergebnis kann
  die Entthronung oder den Nullbefund kippen — dann wäre jede darauf aufbauende Arbeit verschwendet.
- Die Messregeln dieser Nacht stehen jetzt in `LOOP.md` („Measurement rules") und gelten für jede
  Iteration.

## Gegenprüfung durch einen unabhängigen Chat (Nicos ausdrücklicher Auftrag)

**Diese Session prüft sich nicht selbst.** Alles Obige stammt aus einer einzigen langen
Head-Modus-Nacht, in der derselbe Agent Befund, Fix und Verifikation geliefert hat — inklusive
mehrerer Selbstkorrekturen, die genau zeigen, wie leicht hier ein Fehlschluss durchrutscht. Nico
will deshalb morgen eine **unabhängige Zweitmeinung aus einem frischen Chat**, der diese Arbeit
NICHT gebaut hat.

Konkret zu challengen, in dieser Reihenfolge:

1. **Die Entthronung** (`c771867`) — sie hat eine Live-Folge (ML-Long-Bot handelt nicht mehr,
   Depot mit 7 statt 8 Sleeves). War die Begründung tragfähig, oder wurde ein funktionierendes
   Sleeve auf Basis einer zu strengen Schwelle abgeschaltet? Gegenfrage an den Prüfer: ist
   `NO_EDGE_BAND = 0,05` (AUC ≥ 0,55) die richtige Latte, oder ist SIE das eigentliche Problem?
2. **Das feste Universum** (`14a76e8`) — 503 US-Titel aus einem Snapshot von 2026-07-02, trainiert
   ab 2007. Der Survivorship-Bias ist im Doku-Abschnitt „Ehrliche Grenzen" benannt, aber nicht
   quantifiziert. Wie groß ist er wirklich, und kippt er den Nullbefund?
3. **Der Nullbefund selbst** (0 von 12 Presets) — ist er ein Befund über die DATEN oder über
   dieses SETUP? Insbesondere: 20-Handelstage-Relativrendite als Ziel, monatliches Rebalance,
   445 US-Large-Caps. Was davon ist Annahme, was ist Notwendigkeit?
4. **Die VolTarget-Studie** (`dbd3392`) — der Divisor 1,341 ist out-of-sample geprüft, aber auf
   EINEM Split (2017). Hält er auf anderen Splits? Und ist SPY ein zulässiger Proxy für die
   Depot-Vola, oder verschiebt das die ganze Empfehlung?
5. **Die gelöschten 121 Zeilen** — war „weniger Evidenz statt falscher" die richtige Abwägung,
   oder wurden mit den Falschtreffern zu viele echte, nur mehrdeutige Erwähnungen entfernt?

Material für den Prüfer: die vier Research-Dokumente unter `docs/research/2026-08-11-*` und
`2026-08-12-*`, dieses Handoff, `AUTOPILOT_LOG.md` (letzte ~10 Einträge), und der Diff der
24 Commits. Der Backup-Stand vor der Löschung liegt in `pre_fix_voices_2026-08-12.db`.

**Nicht gesucht ist Zustimmung.** Am wertvollsten sind Stellen, an denen die Beweisführung dünner
ist als der Ton, in dem sie geschrieben wurde.

## Einstieg für die nächste Session

Branch `autopilot/work`, Tree sauber, **25 Commits vor `origin/main`, nicht gepusht**.
Erster Blick: `tail -50 train.log` — lief die Nightly um 03:08 durch, und steht dort
`ENTTHRONT: v1`? Danach `PLAN.md` ab „Phase: Risiko-Schiene" (die zwei Einbau-Pflichten für
VolTarget stehen dort als offene Punkte).
Der Cron-Wächter dieser Session ist mit ihr gestorben — bei einer neuen Autopilot-Session neu
armen (~23 min, krumme Minute).
Keine Secrets in dieser Doku; EDGAR- und Alpaca-Zugänge liegen in `.env`.
