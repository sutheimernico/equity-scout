# Wie Menschen ticken: Landkarte der Verhaltensindikatoren (2026-08-11)

Nicos Auftrag: „Volumen war nur ein Beispiel … es gibt ja sicherlich ganz, ganz viele andere
Indizes neben Volumen, die Du bei Tradingview einsehen kannst. Und daraus muss man halt ein
bisschen verstehen, wie die Menschen halt ticken." Wochenziel.

## Die Unterscheidung, die alles entscheidet

**Ein Indikator trägt entweder neue Information — oder er malt den Preis nur anders an.**

Das ist keine Geschmacksfrage, sondern Arithmetik. RSI, MACD, Stochastik, Bollinger-Bänder,
Momentum-Oszillatoren: **alle sind Funktionen derselben Kursreihe.** Wer den Kurs hat, hat sie
schon; sie fügen keine Beobachtung hinzu, sondern transformieren eine vorhandene. Deshalb kann
ein Modell, das den Kurs kennt, aus ihnen strukturell nichts Neues lernen.

Das erklärt auch Nicos eigene Beobachtung („viele Menschen, die Tradingangebote machen, die
funktionieren meistens nicht"): Diese Angebote verkaufen fast ausschließlich Kategorie A.

## Kategorie A — Preistransformationen: gut belegt, dass sie nicht tragen

Die Literatur ist hier ungewöhnlich einig, und zwar negativ:

- Studien zu RSI und MACD auf dem NASDAQ 1972–2015: Vorhersagekraft war früher vorhanden, hat
  sich **von 2005 bis 2015 abgebaut und erzeugte nach Transaktionskosten negative Renditen**.
- Eine breite Auswertung über Märkte hinweg: „All technical indicators perform poorly in terms
  of profitability and predictive power."
- Positive Befunde finden sich fast nur in Emerging Markets und in einzelnen Zeitfenstern — also
  genau das Muster, das man bei Data-Mining erwartet.

**Konsequenz: Wir bauen aus Kategorie A nichts.** Das ist kein Pessimismus, sondern gesparte
Wochen. Und es deckt sich mit dem, was dieses Projekt heute selbst gemessen hat: zwei Runden
zusätzlicher Features am Entry-Modell (Insider-Evidenz +0,003 AUC, Volumen −0,001) bewegten
nichts, weil das Modell den Kurs schon kannte.

## Kategorie B — echte Verhaltensdaten: unabhängige Beobachtungen

Hier steckt der Wert, weil diese Daten **etwas messen, was im Kurs nicht steht**: was Menschen
sagen, wie sie positioniert sind, was sie versichern.

| Quelle | Was sie über Verhalten sagt | Evidenzlage | Frei? | Status |
|---|---|---|---|---|
| **Volumen** | wie viele Menschen gehandelt haben | solide als Teilnahmemaß | ✅ | **gebaut** (v17); W0: kein eigener Beitrag zur Vorhersage |
| **VIX-Terminstruktur** (VIX9D/VIX/VIX3M) | wie teuer Absicherung *jetzt* vs. *später* ist → Panik oder Ruhe | Backwardation als Stressmarker gut belegt | ✅ **verifiziert erreichbar** | **W0 gemessen: gestrichen** — sagt nichts, was der VIX-Level nicht schon sagt |
| **Marktbreite** (Advance/Decline, % über 200d) | tragen viele Titel die Bewegung oder wenige? | robust, klassisch | ✅ aus eigenen Panels | **W0 gemessen: bester Nicht-Vola-Prädiktor**, schon verbaut (`pct_above_200d`) |
| **AAII-Sentiment-Umfrage** | was Privatanleger *erwarten* | **extreme Bearishness → überdurchschnittliche 12-Monats-Renditen** | ✅ wöchentlich (Do) | Abruf offen |
| **Put/Call-Ratio (CBOE)** | Absicherungs- vs. Spekulationsdruck | kontrazyklisch, gut untersucht | ⚠️ **CSV-Endpunkt gibt 403** | Quelle nötig |
| **Short Interest** (FINRA/CBOE) | wie viele gegen einen Titel wetten | **extrem hohes SI → überdurchschnittliche Folgerenditen** (Squeeze) | ✅ 2×/Monat | Abruf offen |
| **Insider / Kongress / 13F** | was Informierte tun | im Projekt gemessen: Kongress-Lane tot, Insider dünn | ✅ | **gebaut**, Befund ernüchternd |

### Der stärkste theoretische Anker: Baker-Wurgler

Baker & Wurgler (2006) bauen einen Sentiment-Index aus fünf Größen (Dividendenprämie,
IPO-Ersttagsrenditen, IPO-Volumen, Closed-End-Fund-Discount, Aktienanteil an Neuemissionen) und
finden **verlässliche kontrazyklische Vorhersagekraft** für Marktrenditen.

Der entscheidende Teil ist die **Asymmetrie**: Es funktioniert **nur in Hoch-Sentiment-Phasen**
(−0,9 % Folgemonat, −0,8 % über sechs Monate, −0,5 % über ein Jahr, jeweils signifikant auf
1 %-Niveau). Die Begründung ist ökonomisch und nicht statistisch: Überbewertung ist häufiger als
Unterbewertung, weil Short-Restriktionen rationale Investoren daran hindern, Überbewertung
abzubauen — bei Unterbewertung gibt es diese Bremse nicht.

**Was das für uns heißt:** Ein Sentiment-Signal sollte **nur in eine Richtung** wirken — es darf
Exposure drosseln, wenn die Stimmung überhitzt, aber nicht symmetrisch aufdrehen, wenn sie
schlecht ist. Genau die Sorte einseitiges Gate, die dieses Projekt beim `_no_edge`-Band der
ML-Champions schon einmal aus demselben Grund gebaut hat.

> **Nachtrag W0 (2026-08-11) — diese Ableitung hat die Messung nicht bestätigt.** An unseren
> Daten wirkt die **Panik**-Seite, nicht die Euphorie-Seite: schwache Marktbreite geht mit
> +13,19 Prozentpunkten Folgevolatilität einher (p < 0,0001), starke Breite mit nichts
> (p = 0,37). Einordnung: Baker-Wurgler sprechen über *Renditen*, gemessen ist hier *Risiko* —
> und in der Renditedimension war der Effekt zu klein, um überhaupt auflösbar zu sein
> (erkennbar erst ab 3,47 % im Monat, Baker-Wurgler berichten 0,9 %). Die Asymmetrie-Annahme ist
> damit weder bestätigt noch widerlegt, sondern **an unseren Daten nicht prüfbar** — und ein Gate
> darauf zu bauen hieße, eine ungeprüfte Fremdannahme in die Exposure-Steuerung zu schreiben.

## Kategorie C — nicht frei

SentimenTrader (20.000+ Indikatoren mit API), Optionsflow in der Tiefe, Level-2-Orderbuchdaten.
Alles kostenpflichtig, alles außerhalb der Projektgrenze. **Nicht verfolgt.**

## Der wichtigste Struktur-Hinweis für die Umsetzung

Die Kategorie-B-Signale sind **Markt-Ebene, nicht Titel-Ebene.** Sie beantworten „wie ist die
Stimmung insgesamt", nicht „welche Aktie steigt". Deshalb gehören sie **nicht** ins
Entry-Modell — dort wurde heute zweimal bewiesen, dass zusätzliche Spalten nichts bewegen —
sondern an zwei andere Stellen:

1. **In die Marktlage-Ampel** (`regime.py`): als zusätzliche Signale, die den Zustand
   beschreiben. Da sitzt schon VIX-Level, Breite, Zinskurve.
2. **In die Exposure-Steuerung des Depots** (`autotrader_protections`): als einseitiges Gate
   nach dem Baker-Wurgler-Muster — drosseln bei Überhitzung, nicht aufdrehen bei Pessimismus.

Das ist ein anderer Wirkmechanismus als „ein Feature mehr im Klassifikator", und es ist der
Grund, warum diese Runde nicht im selben Nullbefund enden muss wie die letzten zwei.

## Wochenplan — nach W0 revidiert (2026-08-11)

> **W0 ist gelaufen und hat den Plan umgeworfen.** Vollständige Auswertung:
> [`2026-08-11-w0-historical-check-behavioural-indicators.md`](2026-08-11-w0-historical-check-behavioural-indicators.md).
> Die drei Sätze, die zählen:
>
> 1. **Kein Kandidat sagt die Marktrendite voraus** — 7 Signale × 3 Horizonte über bis zu 19
>    Jahre, kein Treffer.
> 2. Was trägt, sagt **Risiko** voraus — und stammt ausnahmslos aus Signalen, die die Ampel
>    schon führt (VIX-Level, Marktbreite).
> 3. **Nach Abzug dieser Bestandssignale bleibt bei keinem Kandidaten etwas übrig** (0 von 35
>    inkrementellen Tests). Die VIX-Terminstruktur fällt von Rank-IC 0,51 auf 0,08.
>
> Genau der Fall, für den Nico das Gate angeordnet hat: W1 sah in Literatur und
> Erreichbarkeitstest gut aus und wäre eine neue Datenquelle plus laufende Wartung für null
> Informationsgewinn gewesen.

- [x] **W0 Historischer Abgleich (Gate für alle folgenden Tasks)** — **erledigt 2026-08-11.**
      `scripts/run_behaviour_study.py`, Werkzeug `behaviour_study.py` (26 Tests), Rohzahlen in
      `data/behaviour_study.json`. Nebenbefunde: der OBV-Treffer entpuppte sich im
      Startpunkt-Test als Artefakt (hielt bei 9 % der 22 gleichwertigen Stichproben-Startpunkte),
      und das Volumen-Panel war ohne Not elf Jahre zu kurz — jetzt ab 2007 statt 2018.
- [x] **W1 VIX-Terminstruktur — GESTRICHEN.** Gemessen: trägt roh (Vola 21T Spread +11,02 %,
      p < 0,0001), aber **nichts über den VIX-Level hinaus**, der bereits in der Ampel steht
      (Rest-p = 0,027 gegen α = 0,0006). Eine zweite Datenquelle für dieselbe Aussage.
- [ ] **W2 Marktbreite ausbauen — herabgestuft.** Die Breite ist der beste
      Nicht-Volatilitäts-Prädiktor im Test (Rank-IC −0,48 auf Folgevola) und **schon verbaut**.
      A/D-Linie und Neue-Hochs-minus-Tiefs sind Varianten derselben Beobachtung; sie müssten
      erst inkrementell gegen die vorhandene Breite antreten.
- [ ] **W3 Sentiment-Gate im Depot — Grundlage entfallen.** Es sollte einseitig nach
      Baker-Wurgler wirken („drosseln bei Überhitzung"). Gemessen wirkt die **Panik**-Seite
      (schwache Breite → +13,19 Pp Folgevola, p < 0,0001), die Euphorie-Seite nicht (p = 0,37).
      Falls ein Gate kommt: auf der gemessenen Seite und mit Risiko-, nicht mit Renditebegründung.
- [ ] **W4 Put/Call**, **W5 Short Interest**, **W6 AAII** — **jetzt die einzigen sinnvollen
      Kandidaten.** Sie bringen als Einzige eine wirklich unabhängige Beobachtung mit
      (Optionsmarkt, Leerverkaufspositionen, Umfrage) statt einer weiteren Transformation von
      Kurs und Volatilität — und haben damit als Einzige eine Chance, Runde 2 zu bestehen.
      Gate gilt unverändert. Bei W6 (wöchentlich) vor dem Abruf klären, ob n überhaupt reicht.

**Die harte Grenze, die W0 aufgedeckt hat:** Auflösbar sind hier erst Rendite-Unterschiede ab
**3,47 %** pro Monat (80 % Testmacht, korrigiertes Niveau). Der Baker-Wurgler-Effekt beträgt
−0,9 % — er wäre in unseren Daten **grundsätzlich unsichtbar**, dafür bräuchte es ~275 Jahre
Historie. Die Rendite-Frage ist an unseren Daten also nicht entscheidbar; die Risiko-Frage ist es.
Jedes künftige Verhaltenssignal muss sich über die Risiko-Schiene rechtfertigen.

## Quellen

- [Testing the Profitability of Technical Trading Rules across Markets](https://mgmt.cmb.ac.lk/cbj/wp-content/uploads/2020/06/2.-Technical-trading-rules.pdf)
- [An Empirical Analysis of the Profitability of Technical Analysis](https://lup.lub.lu.se/luur/download?func=downloadFile&recordOId=8905915&fileOId=8905916)
- [Assessing the Long-Term Performance of MACD Strategy](https://ieomsociety.org/proceedings/2023lisbon/327.pdf)
- [How does investor sentiment affect stock and fund returns? (Baker-Wurgler-Auswertung)](https://www.evidenceinvestor.com/post/how-does-investor-sentiment-affect-stock-and-fund-returns)
- [Odds that Investor Sentiment Spuriously Predicts Anomaly Returns (NBER)](https://www.nber.org/system/files/working_papers/w18231/w18231.pdf)
- [Technical analysis as a sentiment barometer and the cross-section of stock returns](https://www.tandfonline.com/doi/abs/10.1080/14697688.2023.2244991)
- [AAII Investor Sentiment Survey](https://www.aaii.com/sentimentsurvey)
- [The Put-Call Ratio: Viewing Market Sentiment Through Options Activity](https://insights.aaii.com/p/the-put-call-ratio-viewing-market)
- [Cboe Short Interest Report](https://www.cboe.com/markets/us/equities/market-statistics/short-interest)
- Eigene Erreichbarkeitstests 2026-08-11: CBOE-Put/Call-CSV → HTTP 403; ^VIX/^VIX3M/^VIX9D über
  yfinance → alle drei liefern Kurse.
