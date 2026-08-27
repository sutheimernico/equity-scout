# Wie viele unabhängige Wetten hat das Auto-Depot? — 3,19 von 12

**Datum:** 2026-08-27 · **Reproduzierbar:** `uv run python scripts/run_diversification_study.py`
**Rohdaten:** `docs/research/2026-08-27-diversification.json`
**Material:** ETF-Panel 2018-06-19 bis 2026-08-26, alle zwölf Sleeves im Backtest, 10 bps
Kosten, bewertet ab Tag 252 (dem ersten Zeitpunkt, an dem jedes Verfahren eigene Gewichte
hat).

## Anlass

Der Allocator gewichtet elf Sleeves nach inverser Volatilität. Dieses Verfahren kennt keine
Korrelationen — es behandelt zwölf Strategien, die im Kern dieselben zwanzig ETFs handeln,
als wären es zwölf unabhängige Wetten. Die Frage war nie gemessen worden.

## Befund 1: Es sind 3,19 unabhängige Wetten, nicht 12

Durchschnittliche Paar-Korrelation der Tagesrenditen: **0,65** (Spanne 0,28 bis 1,00).
Effektive Anzahl unabhängiger Wetten nach Meucci (2009), also die Entropie der normierten
Eigenwerte der Korrelationsmatrix: **3,19**.

Zwölf Sleeves tragen so viel unabhängiges Risiko wie gut drei. Das ist keine Kritik an den
Strategien — es ist die zwangsläufige Folge davon, dass alle aus demselben ETF-Universum
auswählen. Aber es heißt: jeder neue Sleeve, der wieder aus diesem Universum wählt, fügt
dem Depot fast nichts hinzu, und die Gewichtung sollte nicht so tun, als täte er es.

## Befund 2: Zwei Sleeves sind dasselbe — Korrelation 1,000

**DCA (12-month entry)** und **60/40** korrelieren mit **1,000**. Das ist kein Zufall,
sondern Bauart: DCA kauft sich über zwölf Monate in ein 60/40-Portfolio ein und ist danach
per Konstruktion identisch damit. Im Backtestfenster liegt der Einstiegszeitraum am Anfang,
danach laufen beide Reihen gleich.

Praktische Folge im Live-Depot: diese eine Position wird **doppelt gewichtet** — bei elf
gleichgewichteten Sleeves 18,2 % statt 9,1 %. Der Allocator kann das nicht sehen, weil er
nur Volatilitäten vergleicht.

Die nächsten Paare, in derselben Größenordnung: GEM ↔ Multi-Strategie-Mix 0,93 (der Mix
enthält GEM), Permanent Portfolio ↔ Risk Parity 0,91, 60/40 ↔ Volatility Targeting 0,91.

## Befund 3: Kein Gewichtungsverfahren schlägt Gleichgewichtung

Walk-forward, Gewichte monatlich neu aus den letzten 252 Tagen:

| Verfahren | CAGR | Vola | Rend/Vola | Sharpe (r_f 5 %) | MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: |
| **gleichgewichtet** | **9,47 %** | 10,16 % | **0,93** | 0,44 | −18,3 % |
| inverse Vol *(heute live)* | 8,38 % | 9,12 % | 0,92 | 0,37 | −16,5 % |
| ERC (korrelationsbewusst) | 7,95 % | 8,78 % | 0,91 | 0,34 | −16,1 % |
| Minimum-Varianz | 8,73 % | 9,87 % | 0,88 | 0,38 | −18,3 % |
| SPY | 16,07 % | 19,67 % | 0,82 | **0,56** | −33,7 % |

Das ist der Befund von DeMiguel/Garlappi/Uppal (2009), auf diesem Depot reproduziert: die
klügeren Verfahren gewinnen genau so viel Risiko, wie sie an Rendite verlieren. Auch ERC —
das Verfahren, das die Korrelationen *kennt* — liegt nicht vorn.

**Konsequenz für den 17.08.-Umbau:** Der Wechsel von Sharpe-Softmax auf inverse Volatilität
war methodisch richtig (eine Sharpe-Schätzung über 63 Tage ist Rauschen). Er kauft
1,0 Prozentpunkte weniger Drawdown für 1,1 Prozentpunkte CAGR — ein fairer Tausch, aber
kein Fortschritt beim Rendite-Risiko-Verhältnis. Wer maximale Rendite pro Risiko will,
nimmt schlicht Gleichgewichtung. Kein Grund, den Live-Modus umzustellen; wohl aber ein
Grund, keine weitere Optimierungsstufe auf dieser Ebene zu erwarten.

## Befund 4: Auch bei gleichem Risiko schlägt das Depot den Markt nicht

Die bequeme Lesart wäre: „Rend/Vola 0,93 gegen 0,82 — das Depot schlägt den Markt." Sie
hält nicht. Wer den Unterschied ausnutzen will, muss den fehlenden Risikoanteil leihen, und
dann zählt die Überrendite über den Finanzierungssatz.

Auf Marktvolatilität skaliert (Faktor 1,94, Finanzierung 5 % p. a., bewusst pessimistisch):

| | CAGR | Vola | MaxDD |
| --- | ---: | ---: | ---: |
| Depot × 1,94 | 12,63 % | 19,67 % | −33,5 % |
| SPY | **16,07 %** | 19,67 % | −33,7 % |

Bei identischem Risiko und identischem Drawdown bleiben 3,4 Prozentpunkte pro Jahr Rückstand.
Der echte Sharpe sagt dasselbe direkt: 0,44 gegen 0,56.

**Das ist die ehrliche Antwort auf „schlägt der Autotrader den Markt": nein, und zwar nicht
knapp.** Was er tut, ist ein deutlich ruhigeres Depot zu liefern — halbe Volatilität, halber
maximaler Rückgang. Das ist ein echtes Produkt, nur ein anderes als „schlägt den Markt".

## Was daraus folgt

1. **Duplikate zusammenfassen.** Sleeves mit einer Korrelation über 0,95 sind eine Wette
   und müssen sich deren Gewicht teilen. Umgesetzt in `autotrader_allocator.duplicate_groups`
   + `split_within_groups`, wirksam in BEIDEN Modi (im Anker-Modus ist der Effekt am
   größten, weil dort jeder Sleeve exakt 1/n bekommt).

   **Live-Wirkung heute: null, nachgemessen.** Die Erkennung liest die Forward-Reihen, und
   die ältesten Sleeves haben 30 gemeinsame Beobachtungen — unter der Schwelle von 40, ab
   der eine Korrelation von 0,95 mehr ist als eine kleine Stichprobe. Bei täglichem
   Forward-Lauf greift sie also ab etwa **Mitte September 2026**. Bewusst nicht aus dem
   Backtest gespeist, obwohl die Zahl dort belegt ist: der Allocator entscheidet
   ausschließlich aus dem, was die Sleeves live gezeigt haben.
2. **Neue Sleeves aus demselben ETF-Universum lohnen sich nicht.** Der dreizehnte Sleeve
   hebt die effektive Wettenzahl praktisch nicht. Wer diversifizieren will, braucht eine
   andere Anlageklasse oder einen anderen Horizont — nicht eine weitere Auswahlregel auf
   denselben zwanzig ETFs.
3. **Die Messlatte gehört korrigiert, nicht die Zahl.** „Schlägt den Markt" ist mit diesem
   Bauteil nicht erreichbar; „liefert zwei Drittel der Marktrendite bei halbem Risiko" ist
   erreicht und belegt. Die Oberflächen sollten das zweite behaupten.

## Fehler, der beim Messen passiert ist

Der erste Durchlauf meldete für alle vier Verfahren denselben maximalen Rückgang von
−18,3232 % am selben Tag. Vier identische Zahlen auf vier Nachkommastellen sind kein
Ergebnis. Ursache: die Renditereihe war bereits um 252 Tage gekürzt, und `walk_forward`
begann trotzdem erst nach weiteren 252 Tagen zu gewichten — der gesamte Corona-Einbruch
lief bei jedem Verfahren mit dem Startgewicht. Behoben, indem die Funktion nur noch den
Teil ab der ersten eigenen Gewichtung zurückgibt.
