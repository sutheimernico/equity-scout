# Overnight-Drift: geprüft, keine eigene Lane — aber ein Befund über die Session-Lane (2026-08-16)

Vierter Kandidat aus `plans/2026-08-16-short-term-lane-expansion.md`, im Plan bewusst nur als
Backtest angesetzt: kaufen zum Schluss, verkaufen zur Eröffnung.

**Ergebnis: keine eigene Lane** — sie schlägt simples Halten nicht und kippt im Bereich
realistischer Ausführungskosten. **Aber der Befund selbst ist der stärkste dieser Serie und
betrifft die bestehende Intraday-Lane direkt.**

## Der Effekt ist real und groß

SPY, 1995–2026, 7.956 Nächte, ohne Kosten:

| | Ø je Tag | annualisiert | t |
|---|---|---|---|
| über Nacht halten | 4,01 bp | **+10,62 %** | **5,23** |
| tagsüber halten | 0,95 bp | +2,43 % | 0,87 |
| beides (Buy & Hold) | 4,96 bp | +13,31 % | 3,71 |

91 Einzeltitel, 2012–2026, 325.000 Beobachtungen:

| | Ø je Tag | annualisiert | t |
|---|---|---|---|
| über Nacht | 7,42 bp | +20,55 % | **18,08** |
| tagsüber | 0,53 bp | +1,34 % | 1,01 |

**93 % der Gesamtrendite entsteht über Nacht.** Die Handelszeit trägt statistisch nichts bei
(t = 1,01 bzw. 0,87 — beide unter jeder Schwelle).

## Warum trotzdem keine Lane

**1. Sie schlägt Halten nicht.** 10,62 % gegen 13,31 % bei SPY. Wer nur nachts investiert ist,
nimmt weniger Risiko und bekommt weniger Rendite — eine Risikoaussage, keine Überlegenheit.

**2. Sie kippt bei ~2 bp je Seite.** Ein Roundtrip pro Nacht ist teuer:

| Kosten je Seite | annualisiert | t |
|---|---|---|
| 1,0 bp | +5,18 % | 2,62 |
| 2,5 bp | −2,48 % | −1,30 |
| 5,0 bp | −14,02 % | −7,83 |
| 10,0 bp (unser Kostenboden) | −33,19 % | −20,88 |

Unsere **gemessene** Slippage aus 67 echten Alpaca-Fills: Median +0,40 bp, Mittel −0,98 bp,
Interquartilsbereich −3,74 bis +3,15 bp. Das liegt auf der Kippschwelle — und stammt aus
Ausführungen **während** der Handelszeit auf liquide Titel. Die Eröffnungsauktion ist der
teuerste Moment des Tages; die Zahl ist also eine untere Schranke für das, was diese Strategie
zahlen müsste. Der Effekt wäre damit genau so groß wie die Unsicherheit über seine Kosten.

## Der eigentliche Ertrag dieser Rechnung

**Die Intraday-Session-Lane handelt ausschließlich in dem Zeitfenster, das strukturell nichts
abwirft.** Sie ist per Konstruktion zum Handelsschluss immer flach — also nimmt sie den
einzigen Zeitraum, in dem der Markt zuverlässig Rendite liefert, nie mit. Ihr gesamter Ertrag
muss aus Selektion kommen, gegen einen Zeitraum-Rückenwind von statistisch null.

Das erklärt keine einzelne Verlustzahl, aber es ordnet sie ein: Die Lane steht nicht bei
−2,6 %, weil ihre Regel besonders schlecht wäre, sondern sie arbeitet in dem Teil des Tages,
in dem 31 Jahre SPY und 325.000 Einzeltitel-Tage keinen Rückenwind zeigen. Bei ihrer
Beurteilung gehört dieser Satz dazu — sie braucht echtes Alpha, nicht nur eine positive Zahl.

**Nicht getan:** die Session-Lane deswegen geändert. Ihr Prüfstand läuft (161 Trades fehlen),
und sie wegen eines Kontextbefunds vorzeitig zu beerdigen wäre dieselbe Sorte Kurzschluss, die
dieser Plan bei den anderen Kandidaten vermeidet.
