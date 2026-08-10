# Plan: v17 „Verhaltenssignale aus Volumen" (2026-08-11)

## Auftrag

Nico: „man muss sich probieren, in die Lage der anderen Menschen zu versetzen, wann kaufen
Menschen Aktien und wann nicht? … Beispielsweise Volumina ist x und y, Menschen verkaufen …
weißt Du, so was hast Du bestimmt schon irgendwie so implizit drin, vielleicht auch schon aktiv.
Aber das vielleicht noch mal … probiert das mal noch irgendwie aufzuarbeiten und irgendwie maybe
zu berücksichtigen."

## Aufgearbeitet: die Vermutung traf nicht zu

**Volumen war ein vollständiger blinder Fleck.** Geprüft, nicht angenommen:

- Kein Panel hatte eine Volumen-Spalte (`etf_panel.csv`, `entry_panel.csv`,
  `autotrader_ohlc.csv` — alle nur Preise).
- `_download_closes` zog `data["Close"]` aus der yfinance-Antwort und **verwarf alles andere**.
- Volumen kam im ganzen `src/` nur in `alpaca_data.py` (Intraday-Bars) vor, nie in einer
  Strategie, einem Faktor oder einem ML-Feature.

Was an Verhaltenssignalen **schon** drin war und bleibt: die Evidence-Quellen (Insider,
Kongress, 13F, Voices, News) — das ist „wer kauft", aber auf Meldebasis mit Verzug von Tagen
bis Jahren. Dazu 52-Wochen-Hoch-Nähe (Aufmerksamkeitseffekt, v8) und Momentum. Was fehlte, war
das direkte, tagesaktuelle Signal: **wie viele Menschen haben heute überhaupt gehandelt.**

Gute Nachricht: Volumen kostet **keinen zusätzlichen Netzwerkaufruf** — ein `yf.download`
liefert alle Felder, nur wurde eines davon benutzt.

## Tasks

- [x] **T1 Volumen in die Datenpipeline** (`data/etf_panel.py`): `_download_field` generalisiert,
      `load_volume_panel` mit EIGENEM Snapshot. Nicht als Zusatzspalten im Preis-Panel — jeder
      bestehende Leser hält dieses Frame für „Spalten sind Ticker, Werte sind Preise", ein
      gemischtes Frame hätte Renditen, Marks und Korrelationen still vergiftet.
      Split-adjustiert wie die Preise; Null-Volumen-Tage überleben als Null (ein gehaltener
      Titel handelte wirklich nichts — `clean_panel` hätte das als kaputten Preis verworfen).
- [x] **T2 Verhaltenssignale** (`volume_signals.py`): Volumen-Ratio gegen den EIGENEN
      20-Tage-Median (Aufmerksamkeit), OBV-Trend normiert auf diese Baseline (Akkumulation vs.
      Distribution), Kapitulation (großer Abwärts-Move bei Extremvolumen). Plus
      `market_behaviour` als Gesamtbild über die Assetklassen.
      **Die eine Regel: immer gegen die eigene Historie normieren** — SPY handelt ~50 Mio.
      Stück, ein Small Cap ~50 Tsd.; absolute Zahlen vergleichen nichts.
      **Die eine Falle: die Baseline schließt heute aus** — sonst dämpft ein Spike sich in
      seinen eigenen Durchschnitt und verschwindet. Per Test festgenagelt.
- [x] **T3 Sichtbar machen** (`/api/regime` + `RegimeCard`): Die Ampel sagt WIE der Markt
      steht, der neue Block sagt WER handelt. Kostet keinen Fetch (liest die Snapshots).
- [x] **T4 Volumen ins Entry-Modell** (`ml/volume_features.py` + `entry_dataset`): additiv nach
      dem Muster der Evidence-Features (v15 P3) — `volume_index=None` reproduziert das alte
      Layout bitgenau, damit ein Vergleich die Features misst und nicht das Sample.
      Point-in-Time strikt: jedes Fenster endet **vor** `as_of`, weil am Rebalance-Tag die
      Sitzung nicht vorbei ist. Ein Test beweist, dass ein 50×-Spike AM `as_of` unsichtbar
      bleibt und einen Tag später auftaucht.

## Messungen

### Live-Verhaltensbild beim ersten Lauf (2026-08-11)

| Ticker | Ratio vs. eigener Median | Kaufdruck (OBV) | |
|---|---|---|---|
| IEF | **10,6×** | **+12,2** | 🔥 |
| TLT | **4,0×** | +1,7 | 🔥 |
| GLD | **2,1×** | **+10,5** | 🔥 |
| DBC | 1,4× | +11,4 | |
| SPY | 1,0× | +2,3 | |
| VNQ | 1,0× | −2,3 | |
| VEU | 0,8× | −3,8 | |

Anleihen und Gold werden massiv eingesammelt, Auslandsaktien und Immobilien abgegeben — ein
Risk-Off-Bild, das die preis-only-Sicht nicht sehen konnte.

### Coverage im Entry-Universum

**31 von 31 Tickern (100 %)** haben ausreichende Volumen-Historie (5.116 Tage). Das ist der
entscheidende Unterschied zur P3-Evidenz-Runde, wo die Coverage 2,5 % betrug und jeder
AUC-Vergleich damit bedeutungslos war. Diesmal ist der Vergleich aussagekräftig.

### Plain vs. Volumen im Walk-Forward — NULLBEFUND, und ein wichtigerer Befund dahinter

Identisches Sample (6.278 Zeilen, 5.188 Out-of-Sample), Triple-Barrier-Label, nur die
Feature-Breite unterscheidet sich (11 vs. 14):

| Modell | AUC plain | AUC mit Volumen | Δ AUC | Rank-IC plain | Rank-IC Volumen |
|---|---|---|---|---|---|
| random_forest | 0,4982 | 0,4973 | **−0,0009** | +0,0609 | +0,0467 |
| elastic_net | 0,4972 | 0,4959 | **−0,0013** | +0,0676 | +0,0640 |

**Volumen verbessert das Entry-Modell nicht — es verschlechtert es minimal.** Bei 100 %
Coverage und 5.188 OOS-Zeilen ist das diesmal ein echtes Ergebnis und kein Coverage-Artefakt
wie in der P3-Runde. Drei Features ohne Informationsgehalt erhöhen nur die Varianz; ein
leichter Rückgang ist genau, was man dann erwartet.

**Der wichtigere Befund steckt in der absoluten Zahl:** die AUC liegt bei **0,496–0,498, also
praktisch exakt beim Münzwurf — mit 11 Features wie mit 14.** Das Modell hat grundsätzlich
keine Trennkraft für diese Zielgröße, und das ist keine Frage der Feature-Auswahl. Zwei Runden
hintereinander (P3-Evidenz +0,003, v17-Volumen −0,001) haben jetzt dasselbe gezeigt:

> **Weitere Features an dieses Setup zu hängen, bewegt nichts.** Der Hebel liegt nicht in
> mehr Spalten, sondern in der Zielgröße, dem Horizont oder dem Universum — also in einer
> anderen Frage, nicht in einer besseren Antwort auf dieselbe.

Der Rank-IC bleibt bei beiden Varianten positiv (+0,05 bis +0,07), es gibt also eine schwache
monotone Beziehung zwischen Score und realisierter Relativrendite. Die AUC sagt nur: als
BINÄRER Klassifikator trennt das Modell nicht. Diese Diskrepanz ist selbst ein Hinweis — eine
Rangfolge kann brauchbar sein, wo eine Ja/Nein-Vorhersage es nicht ist.

### Konsequenz

- **`volume_index` bleibt im Produktionspfad auf `None`.** Ein Feature-Block, der die Metriken
  nachweisbar leicht verschlechtert, kommt nicht ins Trainingsdefault. Die Infrastruktur bleibt
  — sie kostet nichts und macht die Gegenprobe jederzeit wiederholbar.
- **Der wertvolle Teil dieser Runde ist das Cockpit-Verhaltensbild, nicht das ML.** Das
  Risk-Off-Muster (IEF 10,6×, Gold akkumuliert, Immobilien abgegeben) ist echte, sofort lesbare
  Information über das Verhalten anderer Marktteilnehmer — genau Nicos Frage. Dass ein 7B-Modell
  daraus keinen 20-Tage-Klassifikator machen kann, ändert daran nichts.

## Grenzen, ausdrücklich

- **Alles hier ist deskriptiv.** Volumen sagt, wie viele Menschen gehandelt haben, nicht wer
  richtig lag. Index-Umstellungen, Verfallstage und halbe Feiertags-Sitzungen erzeugen Spitzen
  ohne jeden Verhaltensinhalt; der Median blunted Einzelausreißer, kennt aber keinen Kalender.
- **Kein Handelssignal gebaut.** Die Kapitulations-Erkennung findet den Moment, in dem
  Panikverkäufer fertig sind — sie sagt nicht, dass man kaufen soll. Blind gekauft ist genau
  das, was „ins fallende Messer greifen" heißt.
- **Volumen-Datenqualität ist schlechter als Preis-Qualität** bei einem freien Feed. Ein
  fehlender Tag kommt als 0 an, und eine 0 darf nie als „niemand handelte" gelesen werden,
  ohne die Preisreihe daneben zu prüfen.
