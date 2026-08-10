# Plan: Crypto-Lane — Haltedauer trägt die Kosten (2026-08-10)

## Warum

Messung heute (32 geschlossene Trades, 2026-08-04 bis 2026-08-10):

| Kennzahl | Wert |
|---|---|
| Summe realisiert | −451,60 USD |
| Gebühren (nur Verkaufs-Legs in `st_trades.fees`) | 230,86 USD |
| Gebühren inkl. Kauf-Legs (geschätzt, symmetrisch) | ~460 USD |
| Trefferquote | 12 % (4/32) |
| Ø Gewinner / Ø Verlierer | +22,51 / −19,34 |
| Exit-Grund | 32× `Donchian-10-Exit`, 0× Stop |

**Vor Kosten ist die Lane etwa ±0, nach Kosten ein Totalverlust.** Kein Alpha-Problem,
ein Kostenproblem: 80 bps Kraken-Taker × 2 Seiten + 2 × 10 bps Slippage = ~180 bps pro
Roundtrip, bei ~2.660 USD Positionsgröße also ~43 USD. Der durchschnittliche Gewinner
bringt +22,51 USD — er kann die Kosten arithmetisch nicht decken.

Ursache ist die Zeitskala: Donchian 20/10 auf **15-Minuten-Bars** ist ein Kanal über 5 h
bzw. 2,5 h. Die erwartete Bewegung pro Trade ist damit kleiner als die Reibung.

## Nicos Entscheidung und eine Korrektur daran

Gewählt: „auf Maker + längere Haltedauer umbauen". Die Haltedauer-Achse wird umgesetzt.
Die Maker-Achse **nicht**, und zwar aus einem Grund, der beim Anbieten übersehen wurde:

- Geprüfte Faktenlage (kraken.com/features/fee-schedule, 2026-08-10): Tier 1 ist
  **Maker 0,40 %, Taker 0,80 %** — nicht die 25–40 bps, die die Option angedeutet hat.
  Maker halbiert die Kosten, streicht sie nicht.
- Entscheidend: Diese Lane **routet nichts** — sie ist eine Simulation ohne Kraken-Konto.
  Ein Donchian-Ausbruch ist per Konstruktion ein Market-Take: das Signal IST, dass der Preis
  durch das Kanalniveau geht. Ein Limit-Order auf diesem Niveau wird bei einem echten
  Ausbruch gerade NICHT gefüllt — der Preis läuft weg. Die Fee auf 40 bps zu setzen und
  ansonsten dieselben Fills anzunehmen, würde 32 Trades billiger buchen, die es in dieser
  Form nie gegeben hätte. Das ist genau die Sorte Zahl, die dieses Repo nicht erfindet.
- Ein ehrliches Maker-Modell (Limit am Kanal, gefüllt nur bei Retest, sonst verpasster
  Trade) wäre implementierbar — aber es ist eine **andere Strategie** (Breakout-Retest),
  keine Kostenoptimierung derselben. Das gehört in einen eigenen Plan mit eigener Messung.

Also: Taker-Fee bleibt bei 80 bps, die Zeitskala wird verschoben. Damit trägt die Bewegung
die Reibung, ohne dass eine Gebührenannahme geschönt wird.

## Rechnung, die den Umbau tragfähig macht

Auf Tagesbars ist die erwartete Bewegung pro Trade um ~√96 ≈ 10× größer als auf
15-Minuten-Bars (gleiche Vol-Skalierung, 96 Bars pro Tag). Kosten bleiben 180 bps pro
Roundtrip. Ein klassischer Turtle-Trade (20/10 Tage) hält 10–30 Tage; bei BTC-Tagesvol
von ~2–3 % liegt der erwartete Gewinnbereich bei 10–30 %. Kosten wären dann 6–18 % des
Gewinns statt 190 % davon.

## Tasks

- [ ] **T1** `kraken_data`: Tagesintervall als benannte Konstante, Docstring auf die
      720-Bar-Grenze bei `interval=1440` anpassen (720 Tagesbars ≈ 2 Jahre).
- [ ] **T2** `st_crypto`: Zeitskala auf Tagesbars umstellen. Lookbacks bleiben 20/10 (jetzt
      Tage — der klassische Turtle). `STOP_PCT` von 2 % auf 15 %: auf Tagesbasis läge ein
      2 %-Stop innerhalb eines einzigen Bars und würde den Kanalexit systematisch ersetzen,
      statt ihn abzusichern. Docstring sagt die Zeitskala und den Kostengrund.
- [ ] **T3** Runner: Tagesbars holen, Bar-Marker pro Tag, Report-Zeile nennt die Zeitskala.
      Cron bleibt `*/15` — er prüft dann, ob ein neuer Tagesbar fertig ist (No-Op sonst).
- [ ] **T4** Track-Bruch markieren: `strategy_regime`-Lane-State mit Umstellungsdatum, in
      API und Cockpit angezeigt — wie `execution_regime` beim Session-Lane-Bruch. Die 32
      Trades vom 15-Minuten-Regime sind KEINE Serie mit dem, was danach kommt.
- [ ] **T5** Tests: Kanal-/Stop-Logik auf Tagesbars, Marker-Idempotenz, Regime-Anzeige.

## Grenzen (bewusst nicht in diesem Plan)

- Kein Maker-Fill-Modell (Begründung oben) — eigener Plan, wenn Nico Breakout-Retest will.
- Keine ATR-Positionsgrößen: `ENTRY_FRACTION = 0.25` bleibt. Vol-Targeting wäre die nächste
  Verbesserung, aber erst nach genug Trades auf der neuen Zeitskala messbar.
- Die 32 Alttrades werden nicht neu bewertet. Sie bleiben als ehrlicher Kostenbefund stehen.

## Outcome

_(wird nach der Umsetzung mit gemessenen Zahlen gefüllt — nicht vorher)_
