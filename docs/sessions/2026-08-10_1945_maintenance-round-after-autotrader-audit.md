# Session 2026-08-10 ~18:50 → 19:45 — Bestandsaufnahme Autotrader + Wartungsrunde

## Kontext & Ziel

Nico: „Was macht der Autotrader? Funktioniert das alles? Funktioniert das alles gut? Wurden die
letzten offenen To Dos alle ausgeführt?" — danach „dann arbeite alle to dos ab". Also erst ein
Prüfauftrag über den Live-Zustand, dann Abarbeitung.

## Teil 1 — Die Bestandsaufnahme

**Was der Autotrader ist:** zwei Ebenen. Das **Auto-Depot** (100.000 USD Papierkapital, acht
Strategie-Sleeves per Look-Through zu einem Meta-Buch aggregiert, Schutzkette aus
Einzeltitel-Cap/Regime-Gate/Vol-Target/Drawdown-Breaker, Fills am nächsten Open) und die
**Kurzfrist-Arena** mit drei Lanes à 10.000 USD (session = ORB live auf Alpaca Paper mit
Minutentakt, swing = nightly, crypto = simuliert).

**Funktioniert es mechanisch? Ja.** Alle Ketten aktiv, Slippage real gemessen (1–2 bps),
Buch-vs-Broker-Abweichungen werden erkannt und aufgelöst, Dash live, Gate grün.

**Funktioniert es gut? Nein — und die Ursachen sind verschieden:**

| Lane | Stand | Diagnose |
|---|---|---|
| Auto-Depot | +0,9 % vs SPY +3,3 % | strukturell: 60 % Brutto-Exposure kann steigenden Markt nicht schlagen |
| Session | −233 USD gesamt | 76 % davon (−176,70) ist einmaliges Zwangsflatten von Altbeständen; reine ORB-Strategie −56 USD auf 36 Trades, 6 Ziele (+12,61 Ø) gegen 16 Stops (−9,43 Ø) = 27 % Trefferquote, nötig wären >43 % |
| Crypto | −451,60 USD | **kein Alpha-Problem, ein Kostenproblem**: ~460 USD davon sind Gebühren, vor Kosten ±0 |
| ML-Loop | kein Champion | AUC 0,47–0,50, also am Zufall; 419 Vorhersagen, 0 aufgelöst (planmäßig) |

**Zwei Befunde, die vorher niemand gesehen hatte:**
1. Der Watchdog schlug **sonntags und montags systematisch Fehlalarm** — flache 26-h-SLA gegen
   eine Di–Sa-Kadenz. Der Alarm „nightly überfällig seit 64 h" war heute falsch.
2. Die Session-Lane meldete **−2,41 % für ein Konto, das −0,10 % verlor**: Buch rechnet auf
   10.000, das Alpaca-Konto hält 100.000.

**ToDo-Stand der Vorsession:** Nur Nico-ToDo 1 war erledigt (Training-Konto PA3AKCY23RCD ist
glattgestellt, AAPL @305,88 heute 13:31 UTC gefüllt, 0 Positionen). Alles andere offen.

## Teil 2 — Abgearbeitet

Vier Richtungsentscheidungen vorab bei Nico abgefragt (Crypto-Lane, Kapitalbasis, Evidence-v2,
Merge/Push), dann durchgearbeitet. Sechs Commits, alle mit Test, Gate nach jedem Schritt.

| Commit | Was |
|---|---|
| `164ebc9` | Watchdog prüft Kadenz-Ketten gegen den letzten FÄLLIGEN Slot statt gegen ein pauschales Alter — in der Zeitzone des Crontabs, mit dem frühesten Trigger als Slot, und der Alarm nennt den verpassten Slot |
| `4fe435b` | Session-Lane schreibt die Broker-Equity mit (`fetch_account`), additiv neben dem Strategie-Ledger; Cockpit zeigt beide plus Kapitalauslastung |
| `c446017` | Crypto-Lane auf Tagesbars, Stop 2 % → 15 %, Track-Bruch als `strategy_regime` markiert |
| `6d42963` | v15 M2: Evidence-Challenger auf der Lernkurve als Ringe unterscheidbar, mit Abdeckung 2,5 % als Vorbehalt |
| `ea224f1` | Windows-Tasks daily/nightly können die Maschine wecken (`WakeToRun` war false) |
| `97ce6f2` | Tests für die Broker-Equity-Verdrahtung, ihren Ausfallpfad und den simulierten Pfad |

`main` per Fast-Forward auf `8197f4e` gezogen und **nach GitHub gepusht** (41 Commits; Secret-Scan
über den Diff sauber, `.env` ungetrackt). Dash-Service neu gestartet, neue Felder live verifiziert.

## Teil 3 — Chat-Latenz (Nachtrag, nach „hab nur den laptop" → „fix das alles erstmal lokal")

Plan + alle Messungen: `docs/superpowers/plans/2026-08-10-chat-latency-prompt-cache.md`.

**Hardware-Antwort zuerst:** Intel Iris Xe, integriert, kein dediziertes VRAM. Für Ollama
praktisch nutzlos — nicht offiziell unterstützt, und eine iGPU teilt den Speicherbus mit der
CPU, also genau die bei LLM-Inferenz limitierende Ressource. Also am Prompt gearbeitet.

**Eigene Vorannahme widerlegt:** Ich hatte aus „60–106 s bis zum ersten Token" auf 6.000–11.000
Prompt-Token zurückgerechnet. Gemessen sind es 1.652 (Aktienfrage), 332 (Depot), 463 (Lexikon).
Die alten Zahlen kamen aus Last oder Kaltstart.

**Der eigentliche Befund (Faktor ~50, last-unabhängig): Ollama cached das Prompt-Präfix
zwischen Anfragen.** Gleiches Präfix → 1,8 s Prefill, anderes → 108,6 s. Damit kippt die
Optimierungsrichtung: **stabiles Präfix schlägt kurzen Prompt** — und das bis dahin für richtig
gehaltene Topic-Trimming des Glossars war kontraproduktiv, weil es pro Themenkombination ein
anderes Präfix baute.

Umgesetzt (`b1c772b`): Glossar konstant und fest vorn · `ADVICE_BRIEF` dahinter · Routing am
Wortanfang verankert (`hält` in „hältst", `offen` in „offensichtlich", `ml` in „Sammlung"
feuerten als Substrings) · Überblick-Fallback unterdrückt, sobald die Frage einen Anker hat.

**Der Live-Check fand einen echten Antwort-Defekt:** Hausbegriff-Fragen trafen kein Keyword,
bekamen über den Fallback das ganze Dashboard und wurden mit „wird nicht im Datenkontext
erwähnt" beantwortet — während die Definition im Glossar direkt darüber stand. Neues Topic
`begriffe` ohne eigenen Datenblock. **„Was ist die Einstiegszone?": 121 s und falsch → 7 s und
korrekt** (über den echten Dash-Service verifiziert, nicht nur im TestClient).

Prefill nach dem ersten Aufruf: Lexikon 6,5→0 s · Depot 8,0→1,5 s · Aktienfrage 14,5→8,0 s ·
Empfehlung 22,2→15,7 s.

**Grenzen, ausdrücklich:** Alle Sekundenwerte entstanden unter Fremdlast (parallele Session mit
5× `scan.py`, Load 7–16). Der **qwen2.5:1.5b-Vergleich war dadurch ungültig** — 1.5b generierte
„langsamer" als 7b, was physikalisch nicht sein kann — und bleibt ungeprüft; **kein
Modellwechsel**. Zwei Modellschwächen unabhängig davon: das Modell nannte ein Perzentil
„F-Score 59/100" trotz Glossar-Definition „Piotroski 0–9", erfand „Hoheitswertverhältnis" fürs
Kurs-Buchwert-Verhältnis, und fasste eine Depot-Frage teilweise falsch zusammen („einziger
negativer Beitrag" — die Session-Lane verlor auch). Ansatzpunkt wäre das Dossier-Wording
(Kennzahlen mit ihrer Skala beschriften), nicht der Prompt-Aufbau.

## Entscheidungen

- **Nicos Maker-Wahl begründet abgewichen.** Er wählte „Maker + längere Haltedauer" für die
  Crypto-Lane. Die Haltedauer-Achse ist umgesetzt, die Maker-Achse nicht: Kraken Tier 1 ist
  Maker 0,40 % / Taker 0,80 % (geprüft an der Quelle, nicht aus dem Gedächtnis), und die Lane
  **routet nichts** — ein Limit-Order auf dem Ausbruchsniveau ist genau die Order, die beim
  echten Ausbruch nicht füllt. Die Fee zu halbieren und dieselben Fills anzunehmen hätte 32
  Trades billiger gebucht, die es so nie gegeben hätte. Breakout-Retest wäre eine andere
  Strategie und bekommt einen eigenen Plan, wenn Nico ihn will.
- **Kapitalbasis additiv statt umgeschrieben.** „Buch auf 100k heben" wäre wörtlich genommen
  Option 2 gewesen: Positionsgrößen sind `fraction × Buchwert`, ein 10× größeres Buch handelt
  10× größer. Nicos Ziel (Cockpit zeigt die Alpaca-Zahl, Positionen unverändert) ist stattdessen
  über eine zusätzliche Spalte erreicht, die trägt, was die Börse selbst meldet. Kein Backfill
  der Altzeilen — der hätte genau die Zahl erfunden, die die Spalte verhindern soll.
- **Watchdog-Hürde erhöht, nie gesenkt:** derselbe Fix deckt den daily-Fehlalarm am Wochenende
  mit ab; ein echter verpasster Slot alarmiert weiterhin.

## Befunde ohne Codeänderung

- **Die Resolve-Fälligkeiten sind zwei verschiedene Termine**, was in der Vorsession vermischt
  war: `entry_predictions.resolve_after` min = **11.08. 18:52 UTC** (Horizont 20 Tage) → die
  erste Auflösung schreibt der Daily-Chain **Mi 12.08.**; `evidence_predictions` haben Horizont
  60 Tage und werden erst ab **08.09.** fällig. Der Mittwochs-Check gilt also NUR für
  `entry_predictions` — bei den Evidenz-Vorhersagen ist `resolved = 0` bis September korrekt.
- **P2-Schattenlane:** erster Werktagslauf des Form-4-Kollektors lief heute 18:00, die Lane um
  18:45 → genau 1 Insider-Ereignis im 30-Tage-Fenster, 0 Cluster. Der Verdacht der Vorsession
  bestätigt sich: das Sichtfeld ist das Thema, nicht die Lane (`evidence_predictions` hat
  source='insider' genau 1×, gegen congress 893).
- **Evidence-Refresh-Gate** verhält sich korrekt: Dry-Run meldet 0 neue Auflösungen gegen ein
  Minimum von 30, bewertet nichts neu, Champion unverändert.
- **Doppelter Daily-Trigger** (Windows-Task + systemd) wird vom Lock sauber abgefangen — das
  ist Absicht, kein Defekt.
- Die Alpaca-Paper-Kontonummern stehen bereits seit Juli auf dem öffentlichen `main`. Ohne
  API-Key nicht verwertbar; wenn Nico sie trotzdem raus will, wäre das ein History-Rewrite und
  damit eine eigene, bestätigungspflichtige Aktion.

## Offene Fragen

- Trägt die Crypto-Lane auf Tagesbars? **n = 0** auf der neuen Zeitskala. Bei 20/10 Tagen über
  4 Paare sind grob 1–3 Trades pro Monat und Paar zu erwarten — belastbar erst in Monaten.
- Trägt der Insider-Edge? Hängt daran, ob überhaupt Filings ankommen (siehe P2-Befund).
- ORB-Trefferquote: 27 % gegen nötige >43 % bei n=22. Zu klein für Signifikanz, aber falls es
  bleibt, ist die Strategie und nicht die Ausführung das Problem.

## To-dos

### Nico (nur er kann das)
1. ~~**GPU-oder-API-Entscheidung für den Assistenten**~~ — durch Nicos Randbedingung („hab nur
   den laptop") beantwortet und lokal gelöst, siehe Teil 3. Die Iris Xe bringt für Ollama
   nichts; die Latenz kam vom Prompt-Präfix, nicht von der Hardware. **Falls es später doch
   nicht reicht:** eine API wäre der einzige echte Sprung und kostet Geld — bleibt seine
   Entscheidung. Offen und billig nachzuholen: der 1.5b-Vergleich bei ruhiger Maschine.
2. **`DASH_TOKEN` rotieren** (steht seit dem Cockpit-Deploy an).
3. **Voices-Personenliste** bestätigen/erweitern (`evidence/voices.py::PERSONS`) — Veto-Option.
4. **Visueller Abnahme-Pass** des Cockpits im Browser (kein Screenshot-Tooling hier).
5. Optional: Mi 12.08. prüfen (oder prüfen lassen), ob die ersten `entry_predictions`
   aufgelöst sind — der Wave-1-Selbstcheck sagt: wenn dann noch 0, Plan wieder öffnen.
6. Erledigt und nur zur Kenntnis: Windows-Energie war zur Hälfte ein echter Defekt
   (`WakeToRun`), ist gefixt. Grenze bleibt: im **Akkubetrieb** erlaubt Windows keine
   Wake-Timer, da fällt der Nachtlauf weiter aus.

### Nächste Session (Agent)
- Mi 12.08.: `uv run python scripts/run_evidence_refresh.py` (Dry-Run); ab ≥30 neuen
  Auflösungen mit `--apply`. Ergebnis ehrlich berichten, auch einen Nullbefund.
- Crypto-Lane beobachten: kommt auf Tagesbars überhaupt ein Ausbruch zustande, und trägt der
  erste Trade seine ~180 bps?
- PLAN-Backlog, bewusst nicht in dieser Runde angefasst: vorzeichenrichtige Ledger-Auflösung
  für bearish Voice-Calls (Zeile 201 — vor der ersten Auflösung im September zu erledigen,
  sonst werden 13 voice-Vorhersagen falsch gebucht), B5 voices-Ticker-Resolution + news_themes
  Titel-Dedupe, Kelly-Sizing ab ~50 Depot-Trades, Shorts mit Borrow-Realismus.

## Einstieg für die nächste Session

Branch `autopilot/work` = `main` = `origin/main` = `97ce6f2` (autopilot/work zwei Commits vor
main nach dem Test-Commit — vor dem nächsten Push nachziehen). Tree sauber, Gate 1875 Tests +
ruff + tsc. Keine Secrets in dieser Doku; Alpaca-Keys in `.env`.
