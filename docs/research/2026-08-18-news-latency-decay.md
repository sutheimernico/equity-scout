# News-Latenz: wie schnell zerfällt die Reaktion? (2026-08-18)

Nicos Frage: sollen wir viele Quellen scrapen, um schneller als andere zu sein? Diese
Messung entscheidet sie, statt sie zu diskutieren. Reproduzierbar über
`uv run python scripts/run_news_latency.py`.

**URTEIL: Latenz ist NICHT der Engpass, weil es keinen Effekt gibt, den man verpassen könnte: keine Verzögerungsstufe ist nach Kosten positiv und signifikant. Schneller zu werden würde nichts kaufen.**

## Datenbasis

- 262,953 Artikel mit **sekundengenauem** Zeitstempel (2012-04-17 bis 2025-12-30), Alpaca/Benzinga-Wire
- gegen Minutenbars von 70 Instrumenten gehalten
- Kostenannahme 4 bp Roundtrip (liquide Titel)

## Zerfallskurve

„verpasst" = Bewegung zwischen Meldung und verzögertem Einstieg (der Preis der Latenz).
„danach" = was ab dem verzögerten Einstieg noch kommt. „netto" = danach minus Kosten.

| Verzögerung | Halten | n | verpasst | danach | netto | t |
|---|---|---|---|---|---|---|
| 0 min | 5 min | 207,287 | +0.02 bp | +0.06 bp | -3.94 bp | -82.06 |
| 0 min | 15 min | 203,408 | +0.02 bp | +0.07 bp | -3.93 bp | -49.13 |
| 0 min | 30 min | 197,945 | +0.02 bp | -0.01 bp | -4.01 bp | -36.87 |
| 0 min | 60 min | 187,908 | +0.03 bp | +0.00 bp | -4.00 bp | -26.91 |
| 1 min | 5 min | 206,877 | +0.02 bp | +0.04 bp | -3.96 bp | -83.91 |
| 1 min | 15 min | 203,127 | +0.02 bp | +0.05 bp | -3.95 bp | -49.93 |
| 1 min | 30 min | 197,657 | +0.02 bp | -0.04 bp | -4.04 bp | -37.53 |
| 1 min | 60 min | 187,577 | +0.03 bp | +0.01 bp | -3.99 bp | -27.01 |
| 2 min | 5 min | 206,450 | +0.06 bp | +0.02 bp | -3.98 bp | -84.91 |
| 2 min | 15 min | 202,755 | +0.06 bp | +0.04 bp | -3.96 bp | -50.51 |
| 2 min | 30 min | 197,307 | +0.07 bp | -0.14 bp | -4.14 bp | -38.77 |
| 2 min | 60 min | 187,263 | +0.08 bp | -0.03 bp | -4.03 bp | -27.39 |
| 5 min | 5 min | 205,230 | +0.07 bp | +0.02 bp | -3.98 bp | -87.93 |
| 5 min | 15 min | 201,720 | +0.08 bp | +0.02 bp | -3.98 bp | -52.44 |
| 5 min | 30 min | 196,361 | +0.10 bp | -0.05 bp | -4.05 bp | -38.58 |
| 5 min | 60 min | 186,218 | +0.12 bp | -0.04 bp | -4.04 bp | -27.69 |
| 15 min | 5 min | 201,743 | +0.08 bp | +0.03 bp | -3.97 bp | -93.04 |
| 15 min | 15 min | 197,961 | +0.10 bp | -0.06 bp | -4.06 bp | -55.35 |
| 15 min | 30 min | 193,188 | +0.12 bp | -0.02 bp | -4.02 bp | -39.43 |
| 15 min | 60 min | 182,750 | +0.13 bp | +0.11 bp | -3.89 bp | -27.25 |
| 30 min | 5 min | 196,381 | +0.03 bp | +0.03 bp | -3.97 bp | -97.18 |
| 30 min | 15 min | 193,183 | +0.06 bp | +0.03 bp | -3.97 bp | -56.69 |
| 30 min | 30 min | 187,919 | +0.09 bp | -0.04 bp | -4.04 bp | -41.14 |
| 30 min | 60 min | 176,747 | +0.05 bp | +0.15 bp | -3.85 bp | -27.24 |

## Grenzen

- **Der Wire ist nicht das Ereignis.** Gemessen wird ab der Benzinga-Veröffentlichung; die Verzögerung zwischen dem eigentlichen Vorfall und dem Wire steckt in „verpasst" mit drin. Eine schnellere Quelle würde einen Teil davon einsammeln — wie viel, sagt diese Messung nicht.
- **Kein Richtungsfilter.** Alle Artikel zählen gleich; „gute" und „schlechte" Nachrichten sind nicht getrennt. Ein Richtungssignal wäre der nächste Schritt, aber erst wenn die Zerfallskurve zeigt, dass überhaupt Zeit zum Handeln bleibt.
- **Nur Intraday-News.** Meldungen außerhalb der Handelszeit (Pre-Market, After-Hours — also die Mehrheit der Earnings) werden verworfen, weil ihr „Einstieg" sonst ein Overnight-Gap als Reaktion buchen würde. Verworfen (schnellste Stufe): pre_too_far 176,696, entry_gap 2,095, exit_gap 1,733, no_pre_bar 162.
- **Ein Wire-Item mit mehreren Symbolen zählt pro Symbol.** Eine Makro-Headline über SPY/QQQ/IWM liefert fast identische Renditen mehrfach; die t-Werte sind dadurch überzeichnet. Die Zahl distinkter Items steht oben; eine geclusterte Statistik ist der nächste Härtungsschritt.
- **Long-only, kein Hebel, Papier.** Wie überall in diesem Projekt.
