# Rebalance-Timing-Glück auf unseren Sleeves (2026-08-17)

Aus dem externen Review vom 2026-08-16: Hoffstein/Faber/Braun (JII 2020) zeigen, dass allein die
WAHL des Rebalance-Tags in genau dieser Strategieklasse große Langfrist-Streuung erzeugt. Alle
Depot-Sleeves rebalancieren am Monatsende. Vor dem Bau von Tranching (das neue Sleeve-Identitäten
mit frischen Forward-Tracks erzeugen würde) misst diese Studie, ob der Effekt auf UNSEREM Panel
und UNSEREN Strategien überhaupt material ist. Reproduzierbar über
`scripts/run_timing_luck_study.py` (Engine-Override `run_backtest(..., rebalance_dates=...)`).

## Ergebnis in drei Sätzen

1. **Der Effekt ist material — aber nur für die signalgetriebenen Sleeves.** Dieselbe Regel,
   dieselben Kosten, nur ein anderer Rebalance-Tag: Mean-Reversion streut **5,85 pp CAGR**, DAA
   **4,15 pp**, GEM **3,63 pp**, Cross-Sectional Momentum **3,12 pp**. Die reinen
   Allokations-Sleeves ohne Signal-Stichtag sind praktisch immun (60/40 0,23 pp, DCA 0,25 pp,
   Permanent 0,27 pp, Risk Parity 0,48 pp).
2. **Es ist Glück, kein Kalendereffekt.** Kein Offset gewinnt systematisch: über alle Strategien
   gemittelt liegen die vier Varianten bei **+8,77 % / +8,32 % / +9,19 % / +8,27 %** (Spread der
   Mittel 0,93 pp), und der jeweilige Sieger wechselt pro Strategie (Sektor-Rotation +0d, GEM
   +10d, DAA +15d, Mean-Reversion +10d, Momentum 12-1 +0d). Es gibt also keinen besseren Tag zu
   wählen — nur eine Streuung zu mitteln. Der Turn-of-Month-Effekt war hier am 2026-08-16
   unabhängig widerlegt, was dazu passt.
3. **Konsequenz: der Live-Track jedes Signal-Sleeves trägt eine Unsicherheit in Größenordnung
   mehrerer Prozentpunkte CAGR, die nichts mit der Regel zu tun hat.** Das ist derselbe
   Fehlertyp wie das Champion-Artefakt: eine Zahl, die stabiler aussieht, als der Prozess ist.

## Messaufbau

- Panel: der gecachte ETF-Panel (`data/prices/etf_panel.csv`), **2018-06-19 bis 2026-08-14** —
  8,2 Jahre, ~98 Monatsenden. Der Startzeitpunkt ist nicht wählbar: das gemeinsame Panel beginnt
  dort, wo der jüngste ETF handelbar wird.
- 11 Regel-Strategien (`default_strategies()` ohne den Ensemble-Blend, weil er selbst eine
  Blendung derselben Sleeves ist).
- Offsets 0 / 5 / 10 / 15 Handelstage nach dem Monatsende-Panel-Datum, Kosten 10 bps,
  identische Entscheidungslogik.

| Strategie | +0d | +5d | +10d | +15d | Spread pp | Sharpe min..max |
|---|---|---|---|---|---|---|
| DCA (12-month entry) | +9,52 % | +9,57 % | +9,60 % | +9,76 % | 0,25 | 0,87 .. 0,89 |
| 60/40 | +9,88 % | +9,71 % | +9,65 % | +9,83 % | 0,23 | 0,87 .. 0,88 |
| Permanent Portfolio | +8,34 % | +8,22 % | +8,21 % | +8,48 % | 0,27 | 1,03 .. 1,06 |
| Volatility Targeting | +7,62 % | +7,63 % | +7,44 % | +5,32 % | 2,31 | 0,45 .. 0,69 |
| Dual Momentum (GEM) | +10,54 % | +9,04 % | +12,57 % | +8,94 % | 3,63 | 0,60 .. 0,83 |
| Defensive Asset Allocation | +8,79 % | +6,85 % | +7,97 % | +11,01 % | 4,15 | 0,64 .. 1,01 |
| Sektor-Rotation (Top 3) | +13,36 % | +10,90 % | +12,18 % | +11,91 % | 2,46 | 0,66 .. 0,79 |
| Low-Vol-Anomalie | +3,70 % | +4,49 % | +3,97 % | +2,89 % | 1,60 | 0,46 .. 0,73 |
| Cross-Sectional Momentum (12-1) | +15,55 % | +13,61 % | +14,21 % | +12,42 % | 3,12 | 0,77 .. 1,02 |
| Mean-Reversion (10 Tage) | +2,80 % | +4,83 % | +8,65 % | +4,15 % | 5,85 | 0,32 .. 0,88 |
| Risk Parity (naiv) | +6,38 % | +6,63 % | +6,67 % | +6,19 % | 0,48 | 0,75 .. 0,82 |
| **Mittel über alle Strategien** | **+8,77 %** | **+8,32 %** | **+9,19 %** | **+8,27 %** | **0,93** | |

Die Per-Offset-Spalten und die Mittelzeile sind eine Abweichung vom Plan (er sah nur min..max
vor). Ohne sie ist Glück nicht von Struktur zu trennen: ein systematisch gewinnender Offset wäre
ein ausbeutbarer Kalendereffekt, keine Pfadabhängigkeit — und die Antwort ändert die Empfehlung.

## Was das NICHT sagt

- **Der Spread ist kein Alpha-Maß.** Über 98 Monatsenden hat die Streuung selbst
  Schätzunsicherheit; die Aussage ist „die Größenordnung ist Prozentpunkte, nicht Basispunkte",
  nicht „Mean-Reversion streut genau 5,85 pp".
- **Es sagt nichts darüber, ob eine Strategie funktioniert.** Low-Vol liefert 2,9–4,5 % CAGR und
  Mean-Reversion 2,8–8,7 % — beide bleiben unabhängig vom Rebalance-Tag hinter dem Markt.
- **Es ist keine Live-Änderung.** Kein Sleeve, kein Cron, kein Gewicht wurde angefasst.

## Empfehlung

**Tranching bauen — aber nur für die signalgetriebenen Sleeves und nur nach Nicos Go.** Konkret:
jeden betroffenen Sleeve in vier Tranchen zu 25 % laufen lassen (Offsets 0/5/10/15), das Ergebnis
mitteln. Kosten: die Umschlagshäufigkeit bleibt in der Summe gleich (jede Tranche handelt ein
Viertel), die Buchführung wird komplexer, und — das ist der Preis, der die Entscheidung Nico
gehört — **jeder getrancht laufende Sleeve ist eine neue Strategie-Identität mit frischem
Forward-Track**. Der bisherige Track wird dadurch nicht falsch, aber er endet.

Die vier immunen Allokations-Sleeves (60/40, DCA, Permanent, Risk Parity) bleiben unverändert am
Monatsende: bei 0,2–0,5 pp Streuung wäre Tranching Aufwand ohne Gegenwert.
