# Externes Review der Markt-Matrix + Upgrade-Fahrplan (2026-08-18, nachts)

Auftrag (Nico, 2026-08-17): die Matrix-Vision aus möglichst vielen Perspektiven durchlöchern,
den aktuellen Code wirklich lesen, extern recherchieren, was wir besser machen können — mit der
verankerten Grundhaltung, dass das Ziel (profitabler Autotrader) gesetzt ist und die Frage
„WIE schaffen wir es" lautet. Dieses Dokument ist das Ergebnis: Befunde, was davon noch in der
Nacht gefixt wurde, und der priorisierte Fahrplan.

**Kurzfassung:** Die Nachtkette war tot (Deadlock) und hätte auf vergifteten Daten gerechnet
(unadjustierte Splits). Beides ist behoben, die Kette läuft neu — bewusst **cells-only**: das
Hold-out bleibt zu, bis die Pooling-Statistik gehärtet ist. Die externe Recherche liefert einen
klaren nächsten Hebel, der zu unserem Setup passt (Limit- statt Market-Orders, 8–21 bp belegt)
und ein ehrliches Ranking der Nischen, in denen Solo-Trader nachweislich Geld verdienen.

---

## 1. Was in dieser Nacht kaputt war und gefixt wurde

Vollständiges Review der Datenschicht (empirisch, gegen die Dateien auf Platte) plus der
Statistik-Module. Status je Befund:

| # | Befund | Schwere | Status |
|---|---|---|---|
| 1 | **Nachtkette deadlocked**: der manuell gestartete Waiter matchte per `pgrep -f` seine eigene cmdline; chain1/chain2 hingen seit 23:12 dahinter; der Waiter hätte zudem `run_signal_matrix.py` OHNE Flags gestartet (falsche Phase, Hold-out-Öffnung) | P0 | **GEFIXT** — Prozesse gestoppt, Warteschleife matcht jetzt nur den Python-Prozess (`fetch_minute_history\.py`) |
| 2 | **Bars unadjustiert** (`adjustment` fehlte → Alpaca-Default raw): 10 Split-Sprünge von −66 % bis −95 % auf Platte (GOOGL −95,1 %, AMZN −94,9 %, NFLX, NVDA, TSLA, AAPL, AVGO, WMT); 6 im Suchfenster, 4 im Hold-out; jede Zelle der Klasse `stock` wäre davon dominiert worden | P0 | **GEFIXT** — `adjustment="all"` (Splits+Dividenden = Total-Return-Pfad), Parameter per Test gepinnt, alle 700 Ticker-Jahre werden neu geladen (Backup der Rohdaten: `data/minutes-raw-2026-08-17/`) |
| 3 | **Latenz-Messung blind by construction**: Preisanker war der CLOSE des ersten Bars NACH dem Wire (~90 s zu spät) → `before(0) ≡ 0`, das Urteil wäre ein sicheres falsches Negativ gewesen | P0 | **GEFIXT** — Open-basierte Anker (pre = Bar, der den Stamp enthält; Entry/Exit = Open des ersten Bars ab Zielzeit), Drops werden pro Grund gezählt, Regressionstest mit synthetischem Intra-Bar-Sprung |
| 4 | **Dividenden als Fake-Gaps**: TLT −27,23 bp mittleres Overnight-Gap am Monatsersten (n=120), 68/120 unter der kleinsten gap_down-Schwelle; bond/reit systematisch negativ verzerrt | P1 | **GEFIXT** (durch `adjustment="all"` in #2) |
| 5 | **Halbtage**: Wall-Clock-Filter 09:30–16:00 ließ After-Hours-Prints an ~2 Tagen/Jahr als reguläre Bars durch (SPY 2020-11-27: Bars bis 15:58 bei 13:00-Schluss) | P1 | **GEFIXT** — Session-Ende pro Tag aus dem Alpaca-Börsenkalender (ein Call pro Jahr, gecacht; verifiziert: 2020 → 2 Halbtage erkannt) |
| 6 | **Dünne Instrumente**: CPER-Median 34 „Minuten"-Bars/Tag, FXB 29 — ein „1min"-Bar spannt real 10–30 Minuten; Intraday-Zellen messen Sampling-Frequenz statt Verhalten | P1 | **GEFIXT** — Ticker mit Median < 200 Bars/Tag laufen nur auf Swing-Scheiben (1D+) |
| 7 | **News-Fetch scheiterte leise** (Fehler → continue → exit 0 → Kette loggt OK) und hatte kein Rate-Limit-Handling | P1 | **GEFIXT** — Fehler zählen → non-zero exit; 429/5xx-Backoff mit Retry-After; measure verweigert bei fehlenden Jahren (`--force` überstimmt) |
| 8 | **News nicht dedupliziert** (Alpaca-`id` wurde verworfen; ein Item mit N Symbolen = N „unabhängige" Events) | P1 | **TEILGEFIXT** — `id` im Schema, Dedup nach id/(created_at, headline); die Cluster-Statistik (ein Wire-Item = ein Event) ist als Grenze im Doc ausgewiesen, geclusterte t-Werte sind Teil der Pooling-Härtung (§2) |
| 9 | **Checkpoint-Resume nach Kill unvollständig**: Ticker mit halben Zeilen galt als fertig; verschiedene Zellen eines „Plateaus" ruhten auf verschiedenen Ticker-Mengen | P1 | **GEFIXT** — Complete-Sentinel pro Ticker; ohne Sentinel wird neu gemessen |
| 10 | **Stichprobenboden erstickte lange Zeitscheiben**: 200 Trades PRO TICKER vor dem Pooling → 1D/1W/1M waren strukturell stumm (7 Jahre ≈ 1.760 Tagesbars, 5 % Feuerrate = 88 Trades < 200), obwohl der Pool über 70 Ticker > 6.000 Trades hätte | P1 | **GEFIXT** — Ticker-Boden 20 (Reporting), Evidenz-Boden 200 auf der GEPOOLTEN Zelle (in `qualifying_cells`) |
| 11 | Nicht-atomares Schreiben + 0-Byte-Dateien galten als fertig | P2 | **GEFIXT** — tmp+`os.replace`, 0-Byte = fehlend |
| 12 | **Survivorship der 30 Einzelaktien** (2026er Mega-Caps rückwärts angewandt): absolute bp der Klasse `stock` nach oben verzerrt, Dip-Buying-Signale besonders | strukturell | **DOKUMENTIERT** (Docstring + Limits); Leseregel: stock-Klasse nur relativ zum eigenen unkonditionalen Mittel |
| 13 | Zeitzonen/DST, Paging, Jahresgrenzen, Resampling | — | **GEPRÜFT, SAUBER** (AAPL 2016–2025: 977.993 Zeilen, 0 Duplikate, monoton, alle 253 Handelstage 2020) |

Gate nach den Fixes: volle Suite grün (exit 0), ruff clean. Commits `54fc46a`, `7c6221a`,
`a68f0f2`, `0c1f210` auf `autopilot/work`.

## 2. Die zwei Statistik-Befunde, die noch offen sind (bewusst: vor dem Report, nicht vor den Zellen)

**(a) Das gepoolte t unterstellt Unabhängigkeit der 70 Ticker.** `grid.pool_cells` und
`pooled_cells` rechnen `sum(t_i·√n_i)/√(Σn_i)` — das ist gewichtetes Stouffer unter
Unabhängigkeit (bei k gleichlaufenden Tickern: t·√k). Der Docstring behauptet das Gegenteil.
Aktien teilen Marktbewegungen, und Bedingungen wie VIX-Band/News clustern Trades zeitlich →
gepoolte t-Werte sind um Faktor ~2–6 aufgebläht. **Konsequenz gezogen:** beide Wellen laufen
heute Nacht `--phase cells`; die Report-Phase (und damit die Hold-out-Öffnung) läuft erst nach
der Härtung. Fix-Richtung: Kalenderzeit-Block-Bootstrap über die Trades der Plateau-Kandidaten
(Trade-Zeitstempel müssen dafür für Kandidaten nachberechnet werden — billig, der Checkpoint
speichert nur Aggregate), plus `arch.bootstrap.SPA`/`MCS` über die Kandidatenmenge (§4).

**(b) Entry am Signal-Bar-Close schenkt Mean-Reversion-Signalen den Bid-Ask-Bounce.** Eine
Abwärts-Minute endet typisch am Bid; real bekommt ein ~5 s späterer Einsteiger eher das nächste
Bar-Open (~½ Spread höher). Bei `reversal_down`/`spike_fade`/`consecutive_down` ist dieser
Bounce mit dem Signal KORRELIERT — die konstante Kostenachse fängt das nicht. Fix-Richtung:
Robustheitsvariante Entry@`open[i+1]` als Pflicht-Nachmessung für jeden Plateau-Kandidaten;
ein Kandidat muss beide Varianten überleben. Gleiches Muster für zustandsabhängige Kosten:
die Bedingungen selektieren Weite-Spread-Momente (News, Vola, Volumen), das Kostenraster ist
konstant — Corwin-Schultz-Spread-Proxy pro Kandidaten-Trade als zweite Pflicht-Nachmessung.

Dazu drei kleinere offene Härtungen: Plateau-Nachbarzellen teilen ~80 % ihrer Trades (4er-Regel
ist schwächer als sie aussieht → Kandidaten-Bootstrap behandelt das mit); Hold-out-Register
(wer öffnet 2023–2025 wann, mit welchen Hypothesen — Pflicht vor Welle 4/5); Kongress-Befund
reanalysieren (t = −51,6 riecht nach Pseudo-Replikation: nach Titel UND Monat clustern,
Delisting-Handling prüfen — die Größe liegt weit außerhalb der Literatur).

## 3. Externe Recherche: was nachweislich profitable Solo-Trader anders machen

Vollreport der Recherche (mit Quellen und Evidenz-Grading) beim Review-Agent; hier die für uns
tragfähigen Kernergebnisse:

**Das Muster ist nie „schneller/cleverer", sondern „strukturelle Prämie + enges Universum".**
Latenz ist nur in 3 von 9 geprüften Nischen der Engpass. Für unser Setup (Alpaca, ~5 s, frei):

| Nische | Für uns | Warum |
|---|---|---|
| **Limit- statt Market-Orders** | **JA — größter sofortiger Hebel** | Anand et al., Review of Finance 2026 (27 Mio. FINRA-Retail-Orders): 8 bp (Large-Cap) bis 21 bp (Small-Cap) Kostenvorteil ggü. Market-Orders, Fill-Raten 60–65 %. Mechanismus explizit: Geduld schlägt Geschwindigkeit — Retail-Limit-Orders, die >10 min stehen, verdienen die Spread-Prämie. Passt exakt zu unserer 5-s-Architektur. Caveat: ~35–40 % Non-Fills mit ~16 bp Opportunitätskosten ehrlich modellieren. Zweiter Fund: Alpacas PFOF zahlt 10–25× mehr für Market-Flow — der Broker-Default ist strukturell gegen uns. |
| Closed-End-Fund-Discounts | JA, messbar | Retail-taugliche Cousine der ETF-Arbitrage: kein AP-Status nötig, Discounts persistieren und reversieren über Tage–Monate. Freie Daten (CEF-NAVs). Kandidat für Welle 5. |
| Crypto-Weekend/Overnight | JA, sofort testbar | Evidenz dünn/alt (nur BTC, pre-2018) — aber an unseren eigenen Minutenbars kostenlos falsifizierbar. |
| Optionsprämien (VRP) | SPÄTER | Stärkste Evidenz aller Nischen (PUT-Index: 32 Jahre publizierter Track), aber: Alpaca-Options-Historie beginnt Feb 2024 → kein Backtest über 2018/2020/2022 ohne bezahlten Vendor. Und es ist Tail-Selling — Sizing entscheidet, nicht Signal. |
| Merger-Arb <$1 Mrd. | SPÄTER | Echte Kapazitätslücke, aber Single-Deal-Tail (−20/−40 % über Nacht) auf kleinem Konto nicht diversifizierbar. |
| Microcaps | NEIN (vorerst) | Anomalien konzentrieren sich dort (NBER w23394), aber Spreads 5–50 % Round-Trip fressen sie — unsere eigene Kostenschwellen-Erkenntnis, nur schlimmer. |
| Market-Making illiquide | NEIN | Kein dokumentierter Fall von profitablem LANGSAMEM MM; Hummingbot-Daten zeigen Median ≈ Taschengeld ohne Netto-P&L-Ausweis. Mit 5 s wird man systematisch abgegriffen. |
| Index-Rekonstitution | NEIN | Additionseffekt <1 % im letzten Jahrzehnt — wegarbitriert. |
| MOC-Imbalance | NEIN (hart) | Alpaca lehnt CLS-Orders nach 15:50 ab; NYSE-Imbalance-Feed startet 15:50 → strukturell unmöglich + Feed $1.000/Monat. (Betrifft die laufende gapfade-Lane NICHT — sie nutzt MOO/MOC ohne Imbalance-Reaktion.) |
| Saisonale Futures | NEIN | Alpaca hat keine Futures; Saisonalität laut 26-Rohstoff-Studie 1970–2023 „largely disappeared". |

**Sofort nutzbare Methodik-Pakete** (alle aktiv gepflegt, pip): `arch` (White's Reality Check,
Hansen SPA, Model Confidence Set — MCS ist für unsere Zellensuche das richtigste Werkzeug: es
liefert die MENGE statistisch ununterscheidbarer Sieger), `skfolio` (CombinatorialPurgedCV),
`purgedcv` (Deflated/Probabilistic Sharpe, MinTRL). **`mlfinlab` meiden** (tot/kommerziell).

**Sonstige Funde mit Konsequenz für uns:** Options-O/S-Ratio (Johnson & So 2012, JFE:
~19 % p.a. Dezil-Spread, Rohdaten frei via OCC) als bester freier neuer Prädiktor-Kandidat;
SEC-EDGAR-Submissions-API mit <1 s Latenz (dünne Konkurrenz: ein frischer 10-K wird im Schnitt
nur ~28× sofort abgerufen); FINRA-Reg-SHO-Daily-Files decken NUR OTC-Volumen ab (naive
Short-Ratio-Backtests darauf sind fehlspezifiziert); Wikipedia/Google-Trends: Prädiktivität
nach 2012 wegrepliziert; **PDT-Regel zum 04.06.2026 abgeschafft** (kein $25k-Minimum mehr —
ältere Design-Constraints dazu sind obsolet); dokumentierter Alpaca-Websocket-Ausfall
(lautloser Freeze ~4 min bei Markteröffnung) → Staleness-Detektor („kein Tick seit N s") gehört
in jede Live-Lane, unabhängig von der Reconnect-Logik.

## 4. Priorisierter Fahrplan

1. **Heute Nacht (läuft):** adjustierter Re-Download → News (dedupliziert, mit Backoff) →
   Matrix-Zellen Tiefe 1 (70 Ticker) → Tiefe 2 (70) → Tiefe 3 (12 Leader) → Latenz-Zerfall.
   Hold-out bleibt ZU. Wächter armiert (halbstündlich).
2. **Morgen — Pooling-Härtung, dann EINE Report-Öffnung:** Kandidaten-Nachmessung mit
   Trade-Zeitstempeln; Kalenderzeit-Block-Bootstrap; `arch`-MCS über die Kandidaten; DANN
   `--phase report` einmalig, mit Hold-out-Register. Jeder überlebende Kandidat durchläuft
   zusätzlich: Entry@`open[i+1]`-Variante + Corwin-Schultz-Kosten pro Trade.
3. **Welle 4 — Ausführungsprämie statt Signalsuche:** Limit-Order-Arm in der Live-Messung
   (Session-/Swing-Lane): passive Fills vs. Market-Fills auf identischen Signalen, eigene
   Fill-Raten- und Opportunitätskosten-Messung. Das ist der einzige Hebel mit PEER-REVIEWED
   8–21 bp Erwartungswert, der exakt zu unserem Setup passt — und er verbessert JEDE Lane.
4. **Welle 5 — neue freie Prädiktoren, vorregistriert:** Options-O/S (OCC), AAII, Short
   Interest (mit der Reg-SHO-Falle im Blick), Crypto-Weekend-Test auf eigenen Bars,
   CEF-Discounts. Jeweils mit Zellbudget und gegen das Register.
5. **Dauerhaft:** Falck/Rej/Thesmar-Diagnose in die Kandidaten-Pipeline (Ausreißer-Sensitivität
   sagt Decay voraus); Staleness-Detektor in die Live-Lanes.

## 5. Ehrliche Einordnung gegenüber der Vision

Die Vision („alle Parameter, alle Zeitscheiben, viele Universen, long+short, Hebel nach
Risikoabschätzung") bleibt der Nordstern; dieses Review hat ihre Maschine in vier Punkten
härter gemacht (Daten, Resume, Böden, Latenzmessung) und zwei Selbsttäuschungs-Kanäle
geschlossen, BEVOR sie Funde produzieren konnten. Drei Leitplanken aus der Evidenz:

- **Die Reihenfolge ist Erwartungswert → dann Hebel.** Gemessen: bei −4 bp/Trade macht Hebel 10
  daraus −41 bp. Hebel multipliziert, was da ist — heute wäre das Rauschen und Kosten.
- **Der belegte Weg zu positiven bp führt aktuell über die AUSFÜHRUNG** (Limit-Orders,
  Spread-Prämie), nicht über ein weiteres Preis-Signal. Deshalb Welle 4 vor Welle 5.
- **Short bleibt draußen, bis Leihkosten messbar sind** — die 162-Anomalien-Studie (Muravyev
  et al. 2025, JoF) zeigt: nach echten Borrow-Kosten bleibt von Short-Alpha fast nichts.

Basisraten-Fußnote (Recherche): Für diskretionäre Day-Trader sind <1 % nachhaltig profitabel
(Taiwan-Vollzensus); für SYSTEMATISCHE Solo-Trader existiert keine belastbare Studie — in beide
Richtungen. Genau diese Lücke ist unser Spielfeld: sauber messen, was andere behaupten.
