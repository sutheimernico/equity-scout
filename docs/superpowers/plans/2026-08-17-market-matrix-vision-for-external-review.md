# Markt-Matrix: Vision, Methodik und Ausbauplan — zur externen Bewertung

**Stand:** 2026-08-17, nachts · **Zweck:** Dieses Dokument ist für einen externen Gutachter
geschrieben, der das Projekt nicht kennt. Es enthält die Vision, die vollständige Messhistorie,
die Methodik, den Bauzustand und die offenen Fragen. Am Ende stehen **acht gezielte Fragen**, bei
denen eine unabhängige Einschätzung den größten Wert hätte.

---

## 1. Was das Projekt ist

`equity-scout` ist ein privates, lokal laufendes Research- und Papierhandelssystem eines einzelnen
Entwicklers (kein Fonds, kein Team, kein Fremdkapital). Es läuft seit Juni 2026, hat ~2.200
automatisierte Tests und arbeitet ausschließlich mit **kostenlosen Datenquellen**. Echtgeld ist
per Projektverfassung ausgeschlossen; gehandelt wird auf einem Alpaca-**Papier**-Konto.

Gebaut ist heute:

- **Ein Auto-Depot** mit 11 regelbasierten Strategie-Sleeves (DCA, 60/40, Permanent Portfolio,
  Vol-Targeting, Dual-Momentum/GEM, Defensive Asset Allocation, Sektor-Rotation, Low-Vol,
  Cross-Sectional-Momentum, Mean-Reversion, Risk Parity), meta-allokiert und mit einer
  Risikoschicht (Einzeltitel-Cap 10 %, Regime-Gate, 12 % Vol-Ziel, gestufter Drawdown-Breaker).
- **Vier Kurzfrist-Lanes** auf Papier (Swing, Session – pausiert, Crypto, Gap-Fade).
- **Ein ML-Lernkreis**: Vorhersagen werden geloggt, nach Ablauf des Horizonts zwangsweise
  aufgelöst, Champions per Deflated-Sharpe-Hürde promoviert oder entthront.
- **Eine Evidenz-Schiene**: 50.955 historische Ereignisse (Kongress-Käufe, Insider-Käufe) mit
  aufgelösten Renditen über 1 Woche bis 12 Monate.

**Der ehrliche Stand nach 8 Wochen Messung:** Die Maschine funktioniert, die Ökonomie nicht. Das
Auto-Depot liegt nach 29 Tagen Track 2,09 Prozentpunkte hinter seiner Benchmark (+1,61 % vs.
+3,70 %), bei geringerem Rückgang (1,06 % vs. 1,49 % MaxDD). Kein ML-Modell hat je seine eigene
Promotions-Schwelle erreicht. Rund 17 geprüfte Handelsregeln sind widerlegt.

## 2. Die Vision (Auftrag des Eigentümers)

Wörtlich, aus der Konversation vom 2026-08-17:

> „Einen Autotrader, der nicht an einem Parameter oder einer Zeitscheibe tradet, sondern allen —
> und das jeweils basierend auf gelerntem Wissen, was nachweislich erfolgreich war, und dann mit
> Risikoabschätzung entsprechende Hebel verwenden zum Einkaufen."

> „Alle Parameter gegen alle Parameter und gleichzeitig noch gegen alle Zeitscheiben und dann dort
> ein Muster suchen. Es geht nicht darum, die Gewinnerzelle zu finden, sondern eine Auswahl an
> Gewinnerzellen."

> „Vielleicht ist es ja wirklich eine Parameterkombination von drei, vier Parametern … hohe
> Volatilität und ein hoher Greed-Index, Kongressmitglied hat gekauft und dann kommen noch News
> dazu. Daraus ergibt sich die Risikoeinschätzung, gekauft, jetzt gehebelt."

Zusätzlich gefordert: Zeitscheiben von Minuten bis Monaten, alle Anlageklassen (nicht nur Aktien:
Indizes, Rohstoffe, Anleihen, Währungen), historische News mit minimaler Latenz, Betrieb rund um
die Uhr, und ausdrücklich **auch alles wieder aufnehmen, was bisher widerlegt wurde**.

## 3. Was bereits gemessen wurde — die Messhistorie

Ein Gutachter sollte das kennen, bevor er die Vision bewertet: das ist kein unbeschriebenes Blatt,
sondern ein Projekt mit einer langen Liste negativer Befunde.

### 3.1 Geprüfte Handelsregeln (alle dokumentiert in `docs/research/`)

| Regel | Befund |
|---|---|
| Opening-Range-Breakout intraday | widerlegt: 1.684 Ausbrüche; mit Overnight-Halten 2.550 Signale in 3 Armen, alle gegen den bedingungslosen Benchmark verloren |
| Ausbruch, Einstieg in Minute 1 | Impuls +4,63 bp, hält genau 1 Minute, dann monoton negativ — aber t = 0,94 auf nur 91 Ereignissen (7 Tage Daten) |
| 5-Minuten-Reversal | Effekt **hochsignifikant**: Autokorrelation −0,0644, t = −32,1 auf 248.461 Fenstern. Nach Kosten: genau EINE positive Zelle (+1,86 bp bei 4 bp Kosten, stärkstes Vola-Fünftel) |
| Gap-Fade | brutto stabil (+228,68 bp bei den größten Lücken), **aber der Effekt ist 15 Min nach Eröffnung weg**, und der vorbörsliche Kurs sagt die Lücke nicht vorher |
| Turn-of-Month | widerlegt (+4,66 % vs. +11,28 % Benchmark) |
| 52-Wochen-Hoch | widerlegt (+0,54 %, Trefferquote 52,6 %) |
| Volumen-Kapitulation | widerlegt (+0,22 pp gegen Basis) |
| Overnight-Drift | widerlegt (4,01 bp) |
| Short-Term-Reversal (Tagesskala) | brutto t = 2,68, nach Kosten weg |
| Earnings-Premium | widerlegt (+0,08 pp) |
| PEAD / Post-Earnings-Drift | 1.729 Meldungen, keine Gruppe signifikant; nach schlechten Nachrichten fallen Titel **nicht** (+0,82 %) |
| Donchian 20/10 auf 15-Min-Bars (Crypto) | ~460 von 451 USD Verlust waren Gebühren — brutto ±0 |
| **Kongress-Käufe folgen** | **nachweislich negativ**: −17,55 pp gegen SPY über 12 Monate, t = −51,6, n = 16.358; nur 27,5 % schlagen den Index. Placebo (dieselben Titel, Zufallszeitpunkte): **+4,01 pp** |
| Insider-Käufe folgen | Mittelwert +7,91 % / 12 Monate, **Median −5,48 %**, gegen SPY −5,76 pp |
| Rebalance-Tag (Timing-Glück) | signalgetriebene Strategien streuen **1,6–5,9 pp CAGR** allein durch die Wahl des Kalendertags; kein Offset gewinnt systematisch |

### 3.2 Geprüfte Vorhersage-Signale

| Kandidat | Befund |
|---|---|
| 11 Verhaltensindikatoren × 3 Renditehorizonte, bis 19 Jahre | **kein einziger sagt Rendite voraus**; was trägt, sagt Risiko voraus, davon **0 von 63 inkrementell** |
| VIX-Terminstruktur | roh Rank-IC 0,51 → **inkrementell 0,08** |
| Fear-&-Greed-Komposit | **schwächer als seine beste Einzelzutat** |
| Marktbreite (% über 200d) | bester Nicht-Vola-Prädiktor, aber für **Risiko**, nicht Rendite |
| Insider-Evidenz als ML-Feature | +0,003 AUC (Nullbefund) |
| Volumen als ML-Feature | −0,001 AUC (Nullbefund) |
| Zielgröße/Horizont/Universum (systematische Suche) | kein Modell erreichte je die eigene Schwelle AUC 0,55 |
| Der live scorende Champion | **Messartefakt**: behauptete AUC 0,6195 aus 220 Zeilen, lieferte 0,5152 auf 3.281 — blockierte 5 Wochen bessere Herausforderer |
| VIX als Vola-Prognose | **einziger positiver Befund**: rho 0,642 vs. 0,539 trailing, out-of-sample bestätigt → produktiv eingebaut |
| RSI, MACD, Stochastik, Bollinger | Literatur einig negativ nach Kosten; als reine Preistransformationen fügen sie der Kursreihe keine Information hinzu |

### 3.3 Die zwei harten Grenzen, die aus diesen Messungen folgen

1. **Auflösungsgrenze.** Mit der vorhandenen Datenmenge und Track-Länge ist ein Renditeeffekt erst
   ab **~3,47 % pro Monat** von Null zu unterscheiden. Bekannte, gut erforschte Effekte liegen bei
   0,1–0,5 %/Monat. Auf Tages-/Monatsskala ist die Renditefrage an diesen Daten daher nicht
   entscheidbar; die Risikofrage schon.
2. **Kostenschwelle.** Auf Minutenskala ist die statistische Auflösung ausgezeichnet (t = −32 für
   den 5-Minuten-Reversal), aber der vorhersagbare Anteil beträgt 1,7–5,9 bp, während ein
   Roundtrip 4–10 bp kostet. Der Effekt existiert und ist nicht handelbar — er ist die Entlohnung
   für Liquiditätsbereitstellung, die man verdient, indem man mit Limit-Orders im Buch **steht**,
   nicht indem man mit Market-Orders zugreift.

## 4. Der neue Ansatz: die Markt-Matrix

### 4.1 Der Datenfund, der ihn erst möglich macht

Alle bisherigen Minutenstudien waren **datenlimitiert, nicht effektlimitiert**: yfinance liefert
7 Tage Minutenbars, weshalb der Ausbruchstest 91 Ereignisse und t = 0,94 hatte. Am 2026-08-17
verifiziert:

- **Alpaca SIP-Feed liefert Minutenbars ab 2016-01-01** — ~1 Million Bars pro Instrument,
  10.000 pro API-Call mit Paging, gemessen ~19.000 Bars/s.
- **Alpaca/Benzinga-News ab 2016 mit sekundengenauem Zeitstempel** (`2016-01-04T11:15:03Z`).

Beides im vorhandenen kostenlosen Papier-Zugang. Geladen sind 70 Instrumente × 10 Jahre
(2016–2025) ≈ **70 Millionen Minutenbars**.

### 4.2 Der Messraum

| Achse | Werte |
|---|---|
| **Signal** | 13 Detektoren: `momentum_up`, `reversal_down`, `volume_spike`, `breakout_high`, `hammer`, `bullish_engulfing`, `gap_up`, `gap_down`, `spike_pullback`, `spike_fade`, `consecutive_down`, `range_contraction`, `new_low_20` |
| **Schwelle** | 4 Werte pro Signal (pro Signal eigene Achse, da Einheiten differieren) |
| **Zeitscheibe** | 8: 1min, 5min, 15min, 30min, 60min, 1D, 1W, 1M |
| **Haltedauer** | 5: 1, 2, 3, 6, 12 Bars der jeweiligen Scheibe |
| **Kosten** | 4: 2, 4, 10, 20 bp Roundtrip |
| **Anlageklasse** | 8: Aktien, Index-ETFs, Sektoren, Rohstoffe, Anleihen, Währungen, Volatilität, REITs |
| **Bedingung** | 23 einzeln; als Kombinationen 251 (Tiefe 2), 1.733 (Tiefe 3), 8.516 (Tiefe 4) |

Bedingungen sind: Tageszeit (3), relatives Volumen, Trend (2), News-Fenster 30 Min, VIX-Bänder
(2) — plus **jedes Signal als Zustand** („hat in den letzten 10 Bars gefeuert").

### 4.3 Die methodische Kernentscheidung: Plateau statt Siegerzelle

Der Raum hat Millionen Zellen. Bei α = 0,05 produziert reiner Zufall Tausende „signifikante"
Sieger — genau der Fehler, der dieses Projekt fünf Wochen gekostet hat (der Champion mit AUC
0,6195 auf 220 Zeilen). Die Antwort:

**Eine Zelle gilt nur als Fund, wenn sie Teil einer zusammenhängenden Region von mindestens vier
Zellen ist, in der JEDE Zelle einzeln nach Kosten positiv ist und t ≥ 2 erreicht.** Nachbarschaft
ist definiert als ein Schritt in genau einer von drei Achsen (Schwelle, Zeitscheibe, Haltedauer).
Begründung: Rauschen kommt nicht in zusammenhängenden Blöcken; ein Mechanismus, der bei 0,5 %
Schwelle und 3 Bars Halten funktioniert, hört bei 1 % und 2 Bars nicht abrupt auf.

**Nicht** Nachbarschaftsachsen sind Kosten, Anlageklasse und Bedingung — jeder ihrer Werte
bekommt eigene Regionen, weil „wirkt nur bei 2 bp" / „nur bei Rohstoffen" / „nur nach einer
Meldung" andere Behauptungen sind als „wirkt generell".

### 4.4 Weitere Schutzmechanismen

- **Hold-out:** gesucht wird nur auf 2016–2022; 2023–2025 wird **einmal** geöffnet und nur für die
  bereits gefundenen Plateaus, ohne Nachjustierung. Ein Plateau „hält" nur, wenn die **Mehrheit**
  seiner eigenen Zellen out-of-sample positiv bleibt.
- **Stichprobenboden:** unter 200 Trades berichtet eine Zelle ihre Anzahl und sonst nichts.
- **Kein Pyramiding:** während eine Position offen ist, werden weitere Signale ignoriert —
  überlappende Einstiege würden eine Marktbewegung mehrfach als „unabhängige" Beobachtung zählen.
- **Look-ahead-Test:** jeder Detektor muss beweisen, dass ein abgeschnittener Datenrahmen
  identische frühere Signale liefert.
- **Gepoolte t-Werte Stouffer-artig**, ohne Unabhängigkeit der Instrumente zu unterstellen.

### 4.5 Warum Bedingungen Zustände sind, keine Koinzidenzen

Zwei Ereignisse, die je 1 % der Bars treffen, fallen auf 0,01 % zusammen — ~100 Fälle in einer
Million Bars, unter dem Stichprobenboden. Deshalb wird das zweite Signal zum **Zustand**: „B hat
in den letzten 10 Bars gefeuert, dann feuerte A". Dieselbe Aussage, aber messbar. Das Fenster ist
um eine Bar verschoben, damit die Bedingung immer vor dem Signal steht.

## 5. Bauzustand und Laufplan

**Fertig, getestet, committet** (Gate: ~2.200 Tests grün, ruff clean):
`data/minute_bars.py`, `data/news_history.py`, `matrix/timeframes.py`, `matrix/signals.py`,
`matrix/contexts.py`, `matrix/grid.py`, `matrix/plateau.py`, `matrix/latency.py`, plus
`scripts/fetch_minute_history.py`, `scripts/run_signal_matrix.py`, `scripts/run_news_latency.py`.

**Gemessene Laufzeiten:** 109.749 Zellen pro Instrument in 41 s (Tiefe 1); Tiefe 2 ≈ 2 min pro
Instrument. Ein Instrument nach dem anderen im Speicher, JSONL-Checkpoint pro Instrument,
Wiederaufnahme überspringt Fertiges. Pooling inkrementell pro Anlageklasse (der Checkpoint
erreicht ~7,7 Mio Zeilen / 2,2 GB).

**Nacht 17./18.08.:** Bars → News → Tiefe 1 (70 Instrumente) → Tiefe 2 (70) → Tiefe 3 (12
Leitinstrumente) → News-Latenz-Zerfallskurve. Tiefe 4 (8.516 Bedingungen) braucht ~75 h auf dem
ganzen Universum und ist bewusst nicht Teil dieser Nacht.

**Vorbefunde aus Testläufen (SPY allein):**
- Tiefe 0 (ohne Bedingungen): 1.984 messbare Zellen, 206 nach Kosten positiv, **2 mit t ≥ 2, beide
  isoliert → kein Plateau**. Bei 20 bp Kosten überlebt nichts.
- Tiefe 1 (23 Bedingungen): 32.236 messbare Zellen, **47 qualifizieren (0,1 %)** — die
  Zufallserwartung läge bei ~741. **Kein Plateau.** Alle fünf Spitzenzellen bei 2 bp.

### Geplante Wellen

| Welle | Inhalt |
|---|---|
| 3 | Kombinationstiefe 2–4; Tages-Regime-Bedingungen (Marktbreite, Zinskurve, SPY-vs-200d, Drawdown); Kongress/Insider als Bedingung mit dem gemessenen **negativen** Vorzeichen |
| 4 | Die drei bekannten, freien und nie gebauten Verhaltensquellen: **AAII-Sentiment** (wöchentlich), **Short Interest** (FINRA, 2×/Monat), **Put/Call-Ratio** (CBOE, Endpunkt gab 403) |
| 5 | Fundamentaldaten (F-Score-Kriterien) auf 126-Tage-Horizont, vorregistriert |

## 6. Bewusste Nicht-Ziele und ihre Begründung

- **Kein Hebel, bis ein Erwartungswert gesichert ist.** Gemessen: bei −4 bp je Trade macht Hebel
  10 daraus −41 bp. Hebel ist die richtige Antwort auf einen gesicherten positiven Erwartungswert,
  und der einzige Schritt, der aus einem kleinen Irrtum eine Kontolöschung macht.
- **Kein Latenzwettlauf, kein Social-Media-Scraping.** Der Weg von Signal zu Fill ist gemessen
  ~5 Sekunden; die Konkurrenz bei News-Reaktion liegt im Mikrosekundenbereich mit Kolokation.
  Historische Tweets sind zudem nicht frei beziehbar, die Hypothese wäre nicht testbar. Statt
  Spekulation wird die **Zerfallskurve** gemessen: was ein um d Minuten verspäteter Einsteiger
  verpasst und was er noch verdient. Hält der Effekt 5 Minuten, ist Latenz kein Engpass; existiert
  er nur in Minute 0–1, ist das Rennen ohnehin verloren.
- **Kein Echtgeld** (Projektverfassung).
- **Keine Preistransformations-Indikatoren als „neue Information".** RSI/MACD & Co. sind Funktionen
  derselben Kursreihe. Sie laufen als Handelsregeln mit, gelten aber nicht als zusätzliche Evidenz.

## 7. Bekannte Schwächen dieses Ansatzes — offen benannt

1. **Feed-Bruch.** Historie ist SIP (konsolidierte Tape, alle Börsen), live lesen die Lanes IEX
   (~2–3 % des Volumens). Ein bestätigtes Plateau ist damit ein Kandidat, kein Live-Edge; der
   erste Schritt eines Umsetzungsplans wäre eine Signal-vs-Fill-Messung, nicht eine Order.
2. **Liquiditäts-Bias.** Das Universum sind die liquidesten Instrumente ihrer Klasse — der
   billigste Fall für Handelskosten. Was hier scheitert, scheitert überall teurer; die Umkehrung
   gilt nicht.
3. **ETFs statt Futures.** „Öl" heißt USO (mit Rollkosten und Tracking-Fehler), nicht der
   WTI-Kontrakt.
4. **Long-only.** Leihkosten sind in diesem Projekt nicht messbar, nur schätzbar.
5. **Kein formaler Multiple-Testing-Korrektor** über die Matrix. Der Schutz ist strukturell
   (Plateau + Hold-out), nicht statistisch (kein FDR, kein Bonferroni über Millionen Zellen).
6. **Das laufende Jahr fehlt** (`HTTP 403 subscription does not permit querying recent SIP data`),
   nutzbar sind 2016–2025.
7. **Keine Richtungsklassifikation der News.** `after_news` misst „eine Meldung kam", nicht „eine
   gute Meldung kam".

---

## 8. Acht Fragen an den externen Gutachter

1. **Reicht die Plateau-Regel als Schutz gegen Multiple Testing**, oder braucht es zusätzlich ein
   formales Verfahren (FDR/Benjamini-Hochberg, Deflated Sharpe über die Zellzahl, White's Reality
   Check / Hansen SPA)? Falls ja: welches passt zu ~4 Millionen abhängigen Tests, deren
   Abhängigkeitsstruktur (geteilte Trades über Kostenstufen und Nachbarzellen) bekannt ist?
2. **Ist ein einmaliger Zeit-Split (2016–2022 / 2023–2025) ausreichend**, oder wäre Combinatorially
   Purged Cross-Validation bzw. Walk-Forward mit Embargo hier klar überlegen — und rechtfertigt der
   Mehraufwand den Gewinn bei diesem Datenumfang?
3. **Ist die Gate-Konstruktion sauber** — ein Signal als Zustand („hat in den letzten 10 Bars
   gefeuert") statt als Koinzidenz? Entsteht dadurch eine versteckte Verzerrung, die wir nicht
   sehen (z. B. Autokorrelation, die t-Werte aufbläht)?
4. **Ab welcher Kombinationstiefe ist die Suche ökonomisch sinnlos?** Wir messen den
   Stichprobenboden pro Zelle, aber gibt es ein besseres Kriterium als „mindestens 200 Trades",
   etwa eine Mindest-Ereignisrate oder ein Bayes-Faktor?
5. **Wie groß ist der SIP-vs-IEX-Fehler realistisch** bei Minutenbars auf liquiden US-Titeln, und
   ist ein daraus gebauter Backtest überhaupt aussagekräftig für eine IEX-Live-Ausführung?
6. **Fehlt eine freie Datenquelle oder eine Methode**, die wir nicht kennen und die bei diesem
   Zuschnitt (Einzelperson, kostenlose Daten, ~5 s Latenz, Papierhandel) messbar etwas beitragen
   würde? Bekannte Lücken sind AAII, Short Interest, Put/Call.
7. **Ist der gemessene Kongress-Befund plausibel** (−17,55 pp gegen SPY über 12 Monate, t = −51,6,
   Placebo +4,01 pp) oder deutet die Größe auf einen methodischen Fehler? Wir vermuten
   Meldeverzug plus „kaufen, was schon gelaufen ist"; ein Survivorship- oder
   Delisting-Bias in der Kursquelle wäre die Alternative, die wir nicht ausgeschlossen haben.
8. **Die unbequemste Frage:** Ist dieses Vorhaben — mit kostenlosen Daten, ~5 s Latenz und ohne
   Fremdkapital — grundsätzlich in der Lage, einen nach Kosten positiven Erwartungswert zu finden?
   Oder ist die richtige Empfehlung, das System als Risiko- und Disziplinwerkzeug zu behalten und
   die Renditeerwartung aufzugeben? Eine begründete negative Antwort ist ausdrücklich willkommen —
   sie wäre die nützlichste.

### Anhang: wo was liegt

- Vollständiges Inventar aller Messungen: `docs/research/2026-08-17-inventory-everything-measured.md`
- Kongress/Insider-Langhorizont: `docs/research/2026-08-17-congress-and-insider-long-horizon.md`
- Matrix-Bauplan mit Task-Historie: `docs/superpowers/plans/2026-08-17-signal-matrix-plateaus.md`
- 28 Einzelstudien: `docs/research/`
- Projektverfassung (harte Grenzen): `LOOP.md`
