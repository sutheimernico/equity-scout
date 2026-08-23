# Handy-Cockpit: Bestandsaufnahme aller Ansichten (2026-08-23)

Task 9 aus `docs/superpowers/plans/2026-08-06-phone-cockpit-beginner-friendly.md`
(„alle Mehr-Ansichten einsteigerfreundlich"), neu bewertet gegen die **heutige** IA — der
Plan nennt acht Panel-Namen aus der Zeit vor dem Rebuild vom 08.08. (13 Views → 5 Tabs).

**Gemessen, nicht geschätzt:** Playwright gegen den laufenden Dienst auf `127.0.0.1:8420`,
Viewport 390 × 844 px (iPhone-Breite), `document.body.scrollHeight` als Maß. Ein Bildschirm
= 844 px.

## Die Zahlen

| Ansicht | vorher | Bildschirme | nachher | Bildschirme |
|---|---:|---:|---:|---:|
| **werkauft** (Wer kauft?) | **68 005 px** | **80,6** | **8 252 px** | 9,8 |
| **entscheiden** | **10 158 px** | **12,0** | **2 855 px** | 3,4 |
| labor | 4 955 px | 5,9 | 4 392 px | 5,2 |
| ergebnisse | 3 964 px | 4,7 | 4 041 px | 4,8 |
| wie | 1 896 px | 2,2 | 1 973 px | 2,3 |
| depot | 1 768 px | 2,1 | 1 845 px | 2,2 |
| heute | 1 453 px | 1,7 | 1 521 px | 1,8 |
| aktien | 844 px | 1,0 | 844 px | 1,0 |

Der leichte Zuwachs bei den unveränderten Ansichten ist der neue Fußfreiraum (`.content`
räumt jetzt 140 px statt 64 px), damit der Chat-Knopf nicht mehr auf der letzten Zeile sitzt.

## Was pro Ansicht die Frage war — und was sie beantwortet hat

**werkauft — „Wer kauft gerade was"** · war die schlimmste Ansicht des Cockpits und der
Grund, warum diese Runde überhaupt lohnt.
- `VoicesPanel` rendert**e** *jedes* Stimmen-Ereignis als volle Karte: **262** an diesem Tag.
- **205 der 262 Stimmen-Ereignisse** sind `context`, also „wird in der Presse erwähnt". Die
  Ansicht, die verspricht zu zeigen, wer kauft, bestand zu **vier Fünfteln** aus Karten mit
  dem Satz „keine erkennbare Kauf- oder Verkaufsrichtung" — jedes Mal wörtlich derselbe.
- `PeoplePanel` sortierte innerhalb einer Personenkarte nur nach Datum. Michael Burry hatte
  95 Ereignisse; die sechs sichtbaren Zeilen waren Erwähnungen, seine gemeldeten Käufe
  standen hinter „+89 weitere anzeigen".
- **Behoben:** gerichtete Aussagen sind die Standardansicht (57 von 262), reine Erwähnungen
  hinter einem Tab; Liste bei 15 gedeckelt; Personenkarten bei 10; Meldungen und gerichtete
  Calls sortieren *innerhalb* einer Karte über die bloßen Erwähnungen; der immer gleiche
  Erklärsatz steht einmal oben statt 200-mal.

**entscheiden** · der obere Teil ist vorbildlich (eine Karte, drei Knöpfe, Begründung hinter
einem Tap). Darunter hingen **28 verfallene** von 30 Pitches in voller Kartenhöhe.
- **Behoben:** offene Pitches bleiben ungedeckelt — dafür ist der Schirm da —, die
  entschiedene/verfallene Historie zeigt fünf und benennt den Rest auf dem Knopf.

**labor** · acht Tabs, die auf 390 px auf **drei Zeilen** umbrachen: **193 px** verbraucht,
bevor irgendein Inhalt beginnt. Im Strategien-Tab noch einmal dasselbe mit **dreizehn**
Tabs (**553 px**), deren letzte Zeile unter dem Chat-Knopf lag. Beide Zahlen nachgemessen,
indem die Wrap-Regel im laufenden Browser wiederhergestellt wurde.
- **Behoben:** Leisten mit vielen Einträgen scrollen auf dem Handy seitwärts
  (`.tabbar.scroll`) statt umzubrechen — 193 px → **49 px** (Strategien 553 → 49). Leisten mit zwei oder drei
  Tabs brechen weiter um, dort wäre ein verstecktes Tab schlimmer als eine zweite Zeile.

**ergebnisse** · **unverändert gelassen, und zwar bewusst.** Diese Ansicht ist bereits das
Muster, das der Plan für alle anderen fordert: Leitfrage als Überschrift („Kann das
funktionieren?"), pro Block eine Alltagsfrage („Hat es mehr gebracht, als einfach den Markt
zu kaufen?"), Klartext-Antwort, ehrliche Leerzustände („Noch nicht messbar (braucht
abgeschlossene Trades mit Gewinn)"), Fachwort hinter ⓘ. 4,8 Bildschirme sind für eine
Auswertung von fünf Büchern angemessen.

**heute · aktien · depot · wie** · in Ordnung, nichts geändert. `aktien` traf sogar den
leeren Zustand richtig: „Heute liegt kein Titel in seiner Einstiegszone — das ist ein
Ergebnis, kein Fehler."

## Das Muster, das „Signal-Filter" gut macht (Task 9, Schritt 2)

Nico nennt `MLPanel` als die Ansicht, die funktioniert. Am Screenshot abgelesen, warum:

1. **Eine Leitfrage als Überschrift**, in Alltagssprache: „Lohnt es sich, dem Signal zu folgen?"
2. **Die Methode hinter einem Aufklapper**, nicht im Fließtext („Wie funktioniert das?
   Meta-Labeling & der eingebaute Overfitting-Schutz").
3. **Ein kurzer Absatz sagt, was das Ding *nicht* tut** („entscheidet nicht, *was* steigt,
   sondern *ob* man dem Trendsignal folgen sollte").
4. **Wenige Zahlen, jede mit ihrer Vergleichsgröße daneben.**

`ergebnisse` folgt demselben Muster unabhängig davon — zwei Ansichten, ein Muster, beide
von Nico bzw. hier als gut befunden. Das ist die Vorlage für alles Weitere.

## Offen (Entscheidung, nicht Arbeit)

- **Der Chat-Knopf verdeckt weiterhin Text mitten in der Seite**, nicht mehr am Ende. Er
  schwebt fest über der rechten unteren Ecke; im Screenshot von `heute` liegt er auf einer
  Begründungszeile. Das Seitenende ist freigeräumt, der Rest ist die Natur eines FAB und
  eine Designentscheidung aus Mockup v2 — verschieben, verkleinern oder nur auf manchen
  Ansichten zeigen wäre je ein anderer Kompromiss. **Gehört Nico.**
- **`labor` bleibt bei 5,2 Bildschirmen**, weil der Strategien-Tab zwölf Systematiken mit
  vollen Kennzahlenblöcken zeigt. Das ist Inhalt, kein Rauschen — ein Deckel wäre hier
  Verlust, kein Gewinn.

---

## Nachtrag: Review der eigenen Zahlen (2026-08-23, Nicos „stimmen alle Zahlen?")

Alles oben gegen die Quelle nachgemessen. **Vier Korrekturen** — und beim Nachrechnen fiel
ein echter Bug auf, der ohne diese Runde live geblieben wäre.

### Korrigiert

| Behauptung | richtig | woher der Fehler kam |
|---|---|---|
| „475 der 589 Evidenz-Ereignisse sind Erwähnungen" | **205 der 262 Stimmen-Ereignisse** | Das Zählskript nutzte `details.get('kind', 'context')`; Quellen ohne `kind`-Feld (news_theme, edgar_8k, thirteen_f) zählten dadurch stillschweigend als „context" |
| Labor-Tab-Leiste „~350 px" | **193 px** | aus einem Screenshot mit `deviceScaleFactor: 2` abgelesen, Bildpixel nicht halbiert |
| Strategien-Leiste „~800 px" | **553 px** | dieselbe Ursache |
| Host-Schlaf bis „03:30" | **03:54** | 03:30 war der Zeitstempel der syslog-Rotation, nicht des ersten Cron-Laufs |

Die Schlussfolgerung „vier Fünftel der Karten sagen, dass keine Richtung erkennbar ist"
**bleibt richtig** — 205/262 = 78 % —, aber sie gilt für die Stimmen-Ereignisse, die das
Panel zeigt, nicht für die Evidenz insgesamt. Die abgeleiteten Maßnahmen ändern sich nicht.

### Bestätigt (unverändert)

68 005 → 8 252 px · 10 158 → 2 855 px · 262 Stimmen-Ereignisse · 57 gerichtete · 23 Personen
· 30 Pitches / 28 verfallen · Michael Burry 95 Ereignisse · vitest 127 → 142.

**Der Vorher/Nachher-Vergleich ist sauber:** zwischen beiden Messungen war die Datenbasis
identisch (589 Evidenz-Ereignisse, 30 Pitches), obwohl der News-Sweep minütlich läuft.

### Der Bug, den das Nachzählen fand

Beim Aufschlüsseln der Quellen fiel auf, dass die API `source: "thirteen_f"` sendet
(Backend-Konstante `SOURCE_13F` in `evidence/base.py`), `people.ts` aber an **drei** Stellen
gegen `"13f"` verglich. Alle drei Zweige waren tot:

> **80 Fonds-Meldungen von sechs Fonds** — Berkshire Hathaway, Baupost, Appaloosa, Duquesne,
> Himalaya Capital, Third Point — fielen in den Presse-Zweig und standen als
> „Investor / Stimme" mit dem Label „**wird in der Presse erwähnt**" da. In der Ansicht
> „Wer kauft gerade was". Ein 13F über 541 600 Amazon-Aktien, etikettiert als Geschwätz.

Der Fehler stammt aus `f52d59f`. **Ich habe ihn beim Umbau in `isAction()` repliziert**,
indem ich das Literal aus den Zeilen darüber übernommen habe, statt es gegen die Daten zu
prüfen — deshalb sind die Quellen-Strings jetzt eine benannte Konstante `SOURCE`, aus
`evidence/base.py` gespiegelt.

**Warum die bestehenden Tests ihn nicht fingen:** sie haben nie ein Fonds-Ereignis
gefüttert. Ein Label-Test, der nur die Quellen prüft, die der Code ohnehin behandelt,
beweist nichts über die, die er stillschweigend fallen lässt. Die neuen Tests vergleichen
jeden verzweigten Quellen-String gegen die Liste, die die API real sendet; Gegenprobe
gemacht (Konstante auf `"13f"` zurückgedreht → 4 Tests rot).

**Live verifiziert:** „Duquesne Family Office · **Fonds** · Amazon — **Position
aufgestockt**" statt „Investor / Stimme · wird in der Presse erwähnt".
