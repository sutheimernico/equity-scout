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
| **Volumen** | wie viele Menschen gehandelt haben | solide als Teilnahmemaß | ✅ | **gebaut** (v17) |
| **VIX-Terminstruktur** (VIX9D/VIX/VIX3M) | wie teuer Absicherung *jetzt* vs. *später* ist → Panik oder Ruhe | Backwardation als Stressmarker gut belegt | ✅ **verifiziert erreichbar** | **nächster Schritt** |
| **Marktbreite** (Advance/Decline, % über 200d) | tragen viele Titel die Bewegung oder wenige? | robust, klassisch | ✅ aus eigenen Panels | teilweise da (`pct_above_200d`) |
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

## Wochenplan

- [ ] **W1 VIX-Terminstruktur** — verifiziert erreichbar (^VIX9D/^VIX/^VIX3M über yfinance, alle
      drei liefern Daten). Kontango vs. Backwardation als Stressmarker, in die Ampel.
      Aktueller Live-Stand: 12,77 / 15,46 / 18,98 = sauberes Kontango, also Ruhe.
- [ ] **W2 Marktbreite ausbauen** — Advance/Decline-Linie und Neue-Hochs-minus-Tiefs aus dem
      vorhandenen Panel. Kostet keine neue Datenquelle.
- [ ] **W3 Sentiment-Gate im Depot** — einseitig nach Baker-Wurgler: drosselt bei
      Stimmungs-Überhitzung, dreht bei Pessimismus nicht auf. Mit markiertem Track-Bruch.
- [ ] **W4 Put/Call-Quelle finden** — der CBOE-CSV-Endpunkt gibt 403. Alternativen prüfen
      (andere CBOE-Pfade, Nasdaq-Datenportal, yfinance-Optionsketten als Eigenberechnung).
      Wenn keine freie Quelle trägt: ehrlich als „nicht verfügbar" dokumentieren statt
      ersetzen.
- [ ] **W5 Short Interest** — FINRA veröffentlicht zweimal monatlich; als Einzeltitel-Signal für
      die Watchlist, nicht fürs Entry-Modell.
- [ ] **W6 AAII-Sentiment** — wöchentlich. Erst klären, ob es einen stabilen freien Abruf gibt;
      ein wöchentlicher Wert ist für tägliche Entscheidungen ohnehin grob.

Reihenfolge nach verifizierter Erreichbarkeit und Wirkmechanismus, nicht nach Popularität.

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
