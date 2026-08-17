# Strategie-Registry: der Internet-Vollsweep (2026-08-18)

Auftrag (Nico): „das ganze Internet durchforsten — Foren, X, Reddit, Insta-Reels, Blogs, Videos,
alles — und aus allem das perfekte System bauen." Fünf parallele Recherche-Stränge haben die
Schichten des Netzes abgegrast: (1) Reddit/Foren, (2) Social-Media-Guru-Szene (ICT/SMC, VWAP,
0DTE, Finfluencer), (3) Quant-Blogosphäre (Quantocracy, Allocate Smartly, Concretum/Zarattini,
Alvarez), (4) Akademik (offene Faktor-Kataloge, Intraday-Literatur, Bücher, Podcasts),
(5) Code-Ökosystem (GitHub, QuantConnect, TradingView, Composer, Kaggle, MQL5).

**Wie daraus „das perfekte System" wird:** nicht durch Glauben, sondern durch die Pipeline, die
wir schon haben — jede Idee hier ist ein VORREGISTRIERTER KANDIDAT, der durch dieselben Gates
läuft (Kostenachse, Plateau, Hold-out-Register, Kandidaten-Nachmessung). Was überlebt, wird
Sleeve/Lane; was stirbt, wird dokumentierte Widerlegung. Diese Registry ist die Hypothesen-Warteschlange.

**Evidenz-Legende:** STARK = peer-reviewed/groß repliziert · MITTEL = ernsthafte unabhängige
Prüfung · ANEKD. = Behauptung ohne saubere Prüfung · WIDERLEGT = unabhängig negativ ·
[T] = aus Trainingswissen der Agents, in der Session nicht live per URL verifiziert (Reddit- und
Suchmaschinen-Sperren; betrifft v. a. den Foren-Strang — Kern-Regeln solcher Dauerbrenner sind
verlässlich, exakte Zahlen nicht).

---

## Cluster A — Minutenbar-Kandidaten für die Matrix (Welle 5a)

Neue Detektoren/Bedingungen für die BESTEHENDE Matrix-Maschinerie (Plateau + Hold-out-Register
greifen automatisch). Sortiert nach Priorität:

| # | Kandidat | Mechanik/Regel | Evidenz | Neuheit ggü. Matrix |
|---|---|---|---|---|
| A1 | **Market Intraday Momentum** (Gao/Han/Li/Zhou 2018 JFE; Baltussen et al. 2021 JFE) | Rendite der ersten 30 min (ab Vortagesschluss) sagt die letzten 30 min desselben Tages vorher; stärker bei hoher Vol/Volumen/Makro-News. Mechanismus: Gamma-/Leveraged-ETF-Rebalancing nahe Close | **STARK** — Top-Journal + 46-Jahre-Replikation über 60+ Märkte | NEU — kein Analog |
| A2 | **Same-Time-of-Day-Autokorrelation** (Heston/Korajczyk/Sadka 2010 JF) | Rendite im 30-min-Fenster X sagt Rendite im SELBEN Fenster der Folgetage voraus, hält bis ~40 Handelstage | **STARK** (209 Zitationen) | NEU |
| A3 | **Konditionaler Overnight (TugOfWar)** (Lou/Polk/Skouras 2019 JFE) | Momentum-Prämien existieren NUR overnight; EWMA-Overnight/Intraday-Spread als Signal, konditioniert auf Crowding/institutionelles Active-Weight (Proxy aus unseren 13F-Daten) | **STARK** | VARIANTE — die konditionale Fassung unseres unkonditional widerlegten Overnight-Drifts |
| A4 | **VWAP-Familie**: Session-VWAP Bounce/Reclaim, Concretum-VWAP-Trend (long-leg), Anchored VWAP (earnings-verankert via Benzinga/EDGAR) | VWAP-Berechnung Standard; Concretum: SSRN 4631351 (QQQ 2018–23 Sharpe 2,1 — mit Short-Bein!) | MITTEL–STARK, Anchored: ANEKD. (keine unabhängigen Tests — Lücke, die wir füllen) | NEU — **VWAP fehlt komplett in der Matrix**; von 3 Strängen unabhängig genannt |
| A5 | **IBS (Internal Bar Strength)** = (Close−Low)/(High−Low); <0,2 → Long, Exit IBS>0,8 / Close>Vortages-High | Von DREI Strängen unabhängig genannt (Alvarez-Filter, QC-Lean-Alpha, Foren-Dauerbrenner) | MITTEL | NEU — als Detektor UND als Bedingung einbaubar |
| A6 | **ICT-Falsifikationspaket**: Fair Value Gap (Low[t]>High[t−2]), Order Block (letzte Gegenkerze vor Displacement>X·ATR), Liquidity Sweep (N-Bar-Extremum um <X überschritten + Reversal in M Bars), Silver Bullet (10–11 Uhr NY + FVG + Sweep) | Der größte Social-Media-Kult; existierende Reddit-Multi-Asset-Tests: Order Blocks fast überall negativ, Silver Bullet trotz hoher Winrate Nettoverlust [teils T] | ANEKD.–WIDERLEGT — **Wert liegt in der sauberen Widerlegung auf 70 Mio Bars** (und falls etwas überlebt, umso besser) | NEU (FVG/OB/Sweep), Silver Bullet = neues fixes Zeitfenster-Setup |
| A7 | **Beat the Market** (Concretum, SSRN 4824172): dynamische Noise-Area (±14-Tage-Ø-Move ab Open), Entry bei Bandbruch nur zu HH:00/HH:30, Exit Trailing max(Band, VWAP), Vol-Targeting | STARK (live bis 2025 getrackt); Caveat: Teil der Güte kommt aus dem Short-Bein — bei uns nur Long-Leg testbar | NEU — mechanisch klar anders als widerlegtes ORB |
| A8 | **Turtle Soup / Failed-Breakout-Fade** (Raschke): neues 20-Bar-Tief, Close zurück über altes Tief → Long [T] | ANEKD. | VARIANTE — Kombination aus vorhandenem new_low_20 + Reversal; als expliziter Kombi-Test |
| A9 | **Overnight-Gap-Fade (Extremfall)**: Gap > X SD OHNE News-Katalysator → Fade [T] | ANEKD. | VARIANTE — Gap-Detektor + News-Fenster vorhanden, neu ist nur SD-Schwelle + Negativ-Bedingung („keine News") |

## Cluster B — Tagesbars/EDGAR: Faktor- und Depot-Kandidaten (Welle 5b)

**Vorfilter für alles hier: die HXZ-Replikationsstudie** (452 Anomalien: 65 % scheitern; Trading
Frictions 96 % Fail = Microcap-Artefakte; nur Investment- (74 %) und Momentum-Kategorien (63 %)
sind für unser liquides Universum belastbar). Caveat überall: unsere Cross-Section sind 30
Mega-Caps — Dezil-Sorts werden Terzil-Sorts, Aussagen entsprechend schwächer.

| # | Kandidat | Regel | Evidenz | Status bei uns |
|---|---|---|---|---|
| B1 | **Investment/Asset Growth** | Long niedrigstes Terzil Asset-Growth (10-K, jährl. Juni) | STARK (beste HXZ-Kategorie 73,7 %) | NEU, EDGAR vorhanden |
| B2 | **Net Stock Issuance** | Long Rückkäufer (Δ Shares Outstanding negativ) | STARK | NEU, bewusst getrennt vom widerlegten Insider-Following |
| B3 | **12-1-Momentum** (Jegadeesh/Titman) | Return(t−12, t−1), letzter Monat EXKLUDIERT | STARK historisch, Momentum-Crash-Risiko real | VARIANTE — der Kontrasttest zu unserem toten Short-Term-Reversal: die Lücke liegt genau im Exclusion-Fenster |
| B4 | **Gross Profitability / QMJ** | (Umsatz−COGS)/Assets bzw. Quality-Komposit | MITTEL | NEU, dünne Cross-Section |
| B5 | **Residual Momentum** (Blitz/Huij/Martens) | FF3-Residual-Momentum 12-1 | STARK (Kategorie) | NEU — nicht identisch mit XS-Momentum-Sleeve |
| B6 | **Return Seasonality own-month** (Heston/Sadka) | Ø-Rendite im selben Kalendermonat der Vorjahre | MITTEL (bei uns nur 10 Jahre Historie) | NEU — NICHT Turn-of-Month |
| B7 | **13F-Cloning** | Neue/aufgestockte Top-Positionen konzentrierter Value-Manager, 45-Tage-Verzug einpreisen [T] | MITTEL (Effekt real, durch Verzug reduziert) | NEU — EDGAR-13F vorhanden, Meldeverzug-Handling können wir (Congress-Erfahrung) |
| B8 | **TAA-Paket**: VAA (binärer Cash-Switch), HAA (TIPS-Canary), GPM (Korrelations-Malus zi=ri×(1−ci)), ADM (Ø 1/3/6M) | Regeln komplett publiziert (Allocate Smartly); ADM-Redux dokumentiert eigene Ernüchterung (SWR 9,0→6,6 %) | STARK–MITTEL | Alles echte VARIANTEN: Repo-Check ergab DAA = Keller-Original (Equal-Weight), GEM = Antonacci 12M — keiner der 4 Mechanismen vorhanden; GPM-Korrelations-Malus hat kein Sleeve |
| B9 | **Clenow „Stocks on the Move"** | Momentum = Slope(exp. Regression 90d)×252×R², ATR-Sizing, SPX>200-SMA-Filter, Gap-Ausschluss | MITTEL (mehrfach repliziert, live im Einsatz) | NEU — aber 30-Titel-Universum macht das Ranking dünn |
| B10 | **Low-Vol/BAB long-only-Tilt** | Rang nach 12M-Vol/Beta | STARK | ABGLEICHEN — Low-Vol-Sleeve existiert; BAB-Konstruktion (Beta statt Vol) ggf. Variante |
| B11 | **CEF-Discount-Reversion** + **Options-O/S-Ratio** (Johnson & So, OCC-Daten frei) | aus dem Review-Fahrplan vom Vormittag | MITTEL–STARK | NEU, je eigene Datenpipeline nötig (klein) |

## Cluster C — Leveraged-ETF- & Struktur-Cluster (Welle 6, braucht Instrument-Erweiterung)

| # | Kandidat | Kern | Evidenz |
|---|---|---|---|
| C1 | **Leveraged-ETF-Close-Pressure** (Shum et al., Review of Finance): EoD-Vol ↔ LETF-Rebalancing-Volumen; + QC-Decay-Arbitrage-Alphas | Mikrostruktur-Effekt nahe Close, koppelt an A1 | STARK |
| C2 | **HFEA/9-Sig** (UPRO/TMF 55/45 quartalsweise; 9 %-Signal-Rebalancing auf TQQQ) | Rebalancing-Bonus auf Vol-Monstern; 2022-Regimebruch (Aktien+Bonds gleichzeitig ↓) ist das ehrliche Post-Mortem und der Stress-Test | MITTEL; [T] teils |
| C3 | **BTC-Intraday-Seasonality 22:00 UTC** (Quantpedia/SSRN 4081000, Sharpe 1,58 bis 2021, seither ungetestet) | braucht Crypto-Minutenbars (Kraken-API kann das) | MITTEL |

Voraussetzung C1/C2: TQQQ/UPRO/TMF/SVXY in den Minuten-/Tages-Store aufnehmen (Alpaca liefert sie).

## Cluster D — Meta-Lehren, die JEDE Strategie verbessern (in die Pipeline einbauen)

1. **Limit- statt Market-Orders** (Anand et al. RoF 2026: 8–21 bp; Fill-Rate 60–65 %, Non-Fills mit ~16 bp Opportunitätskosten modellieren) — bereits Welle 4 im Fahrplan.
2. **Validierungs-Design aus Kaggle**: time_id-/kalendergruppierte Splits statt Row-Level; Multi-Task über mehrere Horizonte als Rauschreduktion; G-Research-Live-Phase bestätigt extern unser Champion-Artefakt-Muster (Public-Sieger kollabieren live).
3. **„Vol statt Richtung" als Zielgröße** (Optiver-Lehre) — deckt sich mit unserem einzigen positiven Prognose-Befund (VIX→Vola).
4. **Falck/Rej/Thesmar-Diagnose**: In-Sample-Ergebnisse, die auf wenigen Ausreißern ruhen, zerfallen schneller — als Standard-Check in die Kandidaten-Nachmessung.
5. **Carver/Kaufman-Overlays**: Vol-Floor (Langfrist-Minimum statt aktueller Vol), konditionales Deleveraging (nur bei Vol-Anstieg UND Verlust), Skew-Cap (max ~30 % Portfolio in negativ-schiefen Strategien).
6. **Finfluencer-Anti-Signal** (SFI-Studie 23-30): 56 % anti-skilled (−2,3 %/Mon), Reichweite korreliert NEGATIV mit Skill; Contrarian dagegen +1,2 %/Mon OOS. Für uns mangels X-Datenzugang nicht handelbar — aber als Prior: virale Strategien sind eher Anti-Signal.

## Cluster E — Geprüft und bewusst RAUS (mit Grund)

| Kandidat | Grund |
|---|---|
| 0DTE-Verkauf, GEX-Levels, Options-Flow-Following, Earnings-IV-Crush, Wheel-Backtest | Optionshistorie erst ab Feb 2024 — kein Crash-Zyklus abgedeckt; 0DTE-Retail-Bilanz mehrfach negativ belegt |
| Martingale/Grid-Bots | Ruin per Konstruktion — kein Backtest nötig |
| MOC-Imbalance | Alpaca lehnt CLS nach 15:50 ab + Imbalance-Feed $1.000/Mon — strukturell unmöglich |
| Futures-Saisonalität, Turtle auf Futures | keine Futures bei Alpaca; Saisonalität lt. 26-Rohstoff-Studie „largely disappeared" |
| Golden/Death Cross, 9-20-EMA-Cross, Supertrend | Kreuzungsprinzip = widerlegtes MACD; Supertrend-BTC-Test: −92,9 % vs. +940 % B&H |
| Wikipedia-Pageviews/Google Trends | Prädiktivität nach 2012 wegrepliziert (Zhong & Raghib 2019) |
| VPIN | Andersen/Bondarenko: keine inkrementelle Prognosekraft über simples Vol-Perzentil |
| naives SVXY/XIV-Short-Vol | Volmageddon-Post-Mortem; alle Pre-2018-Zahlen durch Hebel-Redesign entwertet |
| Distress-Anomalien, F-Score, Trading-Frictions-/Intangibles-Kataloge | HXZ-Replikation: Fail bzw. Microcap-Artefakte (F-Score-Fail relevant für unseren Welle-5-Plan von gestern!) |
| WSB-YOLO, Signalgruppen (IM Academy: FTC, $1,2 Mrd.), EA-Marktplätze | Scam-Anatomie dokumentiert; keine reproduzierbaren Regeln |
| „13-Sharpe"-arXiv-Preprints | Paper-Mill-Muster — Serien-Extrem-Alpha desselben Autors |

## Scam-Filter (destilliert aus allen 5 Strängen — Standardprüfung für jede künftige Internet-Idee)

1. Reichweite/Likes/Stars messen Marketing, nicht Edge (Finfluencer-Studie, TradingView, MQL5).
2. Winrate ohne Verteilungsform ist ein Alarmsignal (85 % Winrate + Sharpe 0,3 = ICT-Muster; „90 % Win" = Martingale-Tail).
3. Wer die Strategie verkauft (Kurs/Discord/Bot), verdient am Verkauf — Warrior Trading (FTC $3 Mio), IM Academy (FTC $1,2 Mrd).
4. Backtest ohne Kostenachse, ohne OOS-Trennung, ohne tote Varianten = Schaufenster (MQL5/Composer/Guru-Screenshots).
5. Jede Zahl vor einem Produkt-Redesign oder Regimebruch prüfen (Volmageddon 2018, HFEA 2022, PDT-Abschaffung 06/2026).

## Dauerquellen-Abo (laufende Hypothesen-Zufuhr)

**Kataloge:** Open Source Asset Pricing (209+ Prädiktoren, Code+Daten frei, GPL) · JKP Global
Factor Data (406 Charakteristika frei, CC BY-NC) · HXZ „Replicating Anomalies" als Vorfilter-Linse.
**Blogs/Tracker:** Quantocracy (täglich, RSS) · Allocate Smartly (~1–2 TAA/Monat) · Quantpedia
frei · Concretum/Zarattini (2–4 Papers/Jahr, transparent) · Alvarez (exakte MR-Regeln).
**Foren:** r/algotrading (echte Backtest-Threads) · r/thetagang (Options-Mechanik) · r/HFEA
(einzige ehrliche LETF-Live-Community) · Bogleheads-Quant-Ecke.
**Code:** QuantConnect/Lean-Alphas · je-suis-tm + stefan-jansen Repos · Kaggle-Wettbewerbe mit
Live-Phase. **Social:** Corey Hoffstein · Cem Karsan · r/algotrading. **Nicht lohnend:**
TradingView-Likes, OpenBB, MQL5 (nur als Warnkatalog), Composer (seit SoFi-Übernahme schwer zugänglich).

## Vorgeschlagene Reihenfolge (nach Pooling-Härtung + Report-Öffnung der laufenden Nacht)

1. **Welle 5a — Matrix-Erweiterung Minutenbars** (Cluster A): A1–A7 als neue Detektoren/
   Bedingungen, vorregistriert, ein gemeinsames Hold-out-Öffnen. ICT-Paket als Falsifikationsserie
   mitfahren (kostet fast nichts extra, hoher Erkenntnis-/Portfolio-Wert).
2. **Welle 5b — Faktor-/Depot-Kandidaten Tagesbars** (Cluster B): B1–B3 + B8 zuerst (beste
   Evidenz), als Shadow-Sleeves mit denselben Promotions-Hürden wie alles im Depot.
3. **Welle 6 — Instrument-/Datenerweiterung** (Cluster C): LETF-Minuten laden, Crypto-Minuten
   für BTC-Seasonality, OCC-O/S-Pipeline.
4. **Durchgehend** (Cluster D): Limit-Order-Arm (Welle 4), Validierungs-/Overlay-Lehren in die
   Kandidaten-Nachmessung.

**Ehrlicher Rahmen:** Die Studie mit der stärksten Evidenz im ganzen Sweep (Baltussen 46 Jahre)
zahlt ~ein paar bp pro Tag vor Kosten — auch die besten Internet-Funde sind Bausteine, keine
Gelddruckmaschinen. Der Weg zum „perfekten System" ist genau der, den die Pipeline erzwingt:
viele Kandidaten rein, wenige Überlebende raus, evidenzgewichtet kombiniert, Ausführung optimiert.
