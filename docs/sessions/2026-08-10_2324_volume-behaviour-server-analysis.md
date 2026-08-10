# Session 2026-08-10 23:24 — Volumen-Verhaltenssignale, Server-Analyse, Indikator-Landkarte

## Kontext & Ziel

Drei Aufträge von Nico, ineinander verschachtelt:

1. „wann kaufen Menschen Aktien und wann nicht? … Volumina ist x und y … hast Du bestimmt schon
   irgendwie so implizit drin … probiert das mal noch irgendwie aufzuarbeiten"
2. „wir können gerne einen Server mieten, aber bitte einmal aufarbeiten, was mich da so kosten
   würde … ob's sinnig ist, in Frankfurt oder New York direkt an der Börse einen Server zu
   nehmen, weil damit man einen möglichst geringen Ping hat"
3. Nachgeschärft: „Volumen war nur ein Beispiel … es gibt sicherlich ganz viele andere Indizes,
   die Du bei Tradingview einsehen kannst. Und daraus muss man verstehen, wie die Menschen
   ticken" — als **Wochenziel**.

## Ergebnis

Alles auf `main` = `origin/main` = `d001f60`. Gate 1957 Tests + ruff + tsc.

- **Volumen war ein vollständiger blinder Fleck** (`fcf26fd`). Geprüft statt angenommen: kein
  Panel hatte eine Volumen-Spalte, `_download_closes` zog `data["Close"]` und verwarf alles
  andere. Gebaut: `load_volume_panel` (eigener Snapshot), `volume_signals.py`
  (Ratio/OBV/Kapitulation), Verhaltensblock in `/api/regime` + Cockpit.
  Live-Befund: IEF 10,6× Volumen mit OBV +12,2, TLT 4,0×, GLD 2,1×, VEU −3,8 und VNQ −2,3
  abgegeben — Risk-Off-Bild, das die preis-only-Sicht nicht sehen konnte.
- **Volumen im Entry-Modell: Nullbefund** (`86b0917`, Plan
  `docs/superpowers/plans/2026-08-11-v17-volume-behaviour.md`). RF 0,4982 → 0,4973,
  EN 0,4972 → 0,4959, Rank-IC in beiden Fällen schlechter. Coverage diesmal **100 %**, also
  eine echte Antwort. `volume_index` bleibt im Produktionspfad `None`.
- **Server-Analyse** (`docs/research/2026-08-11-server-latency-and-cost-analysis.md`): gemessen
  Ping 110 ms, HTTPS-Roundtrip 347 ms, Fill-Latenz 5 s, Entscheidungsraster 60 s. New York
  spart 0,17 % des Rasters, Frankfurt nichts. Colocation fällt aus (DMA nötig, vier- bis
  fünfstellig, Mikrosekunden irrelevant hier). Empfehlung: ~5 €/Monat VPS wegen
  **Verfügbarkeit**, nicht wegen Ping.
- **Indikator-Landkarte** (`docs/research/2026-08-11-behavioural-indicator-landscape.md`) mit
  Wochenplan W1–W6.

Frühere Runden derselben Nacht (eigene Session-Docs): v16 Wellen 1–3 in
`2026-08-10_2300_v16-alpha-factory-autonomous.md`, Wartungsrunde in
`2026-08-10_1945_maintenance-round-after-autotrader-audit.md`.

## Entscheidungen

- **Nichts aus „Kategorie A" bauen** (RSI/MACD/Bollinger/Stochastik): Sie sind Funktionen
  derselben Kursreihe, tragen also keine neue Beobachtung — und die Literatur zeigt nach
  Transaktionskosten negative Renditen mit ab 2005 verschwindender Vorhersagekraft.
- **Verhaltenssignale gehören auf Markt-Ebene, nicht ins Entry-Modell**: dort ist zweimal
  gemessen, dass zusätzliche Spalten nichts bewegen (Evidenz +0,003, Volumen −0,001, AUC bleibt
  Münzwurf). Ziel sind Ampel und Exposure-Steuerung.
- **Ein Sentiment-Gate muss einseitig wirken** (Baker-Wurgler-Asymmetrie: Überbewertung hält
  sich, weil Short-Restriktionen ihren Abbau verhindern) — drosseln bei Überhitzung, nicht
  aufdrehen bei Pessimismus.
- **`volume_index` nicht in den Trainings-Default**, obwohl die Infrastruktur bleibt: ein Block,
  der die Metriken messbar verschlechtert, wird kein Standard.

## Offene Fragen

- **Der historische Abgleich der neuen Kandidaten fehlt.** Das ist die wichtigste Lücke dieser
  Session und ein echter Mangel im Wochenplan: W1 sagt „VIX-Struktur in die Ampel", aber ob
  VIX-Backwardation in UNSEREN Daten und UNSEREM Universum etwas vorhersagt, ist ungeprüft.
  Bisher stützt sich die Landkarte auf Fremdevidenz (Literatur) plus Erreichbarkeitstest; der
  aktuelle VIX-Stand 12,77/15,46/18,98 ist eine Momentaufnahme, kein Backtest.
  **Konsequenz: vor W1 muss ein W0 „historisch testen" stehen.**
- Trägt Cross-Sectional Momentum (v16, Backtest-Sharpe 1,00) auch forward? n ist noch 0.
- Springt das Depot-Brutto beim nächsten Nightly wirklich von 60 % auf ~84 % (Cap-Umverteilung),
  und greift dann der Vol-Target-Layer stärker?
- Put/Call: CBOE-CSV gibt 403. Gibt es überhaupt eine stabile freie Quelle, oder muss das
  ehrlich als „nicht verfügbar" stehen bleiben?

## To-dos

> **Auftrag mit Vorrang (Nicos ausdrückliche Anweisung, 2026-08-10):
> Jeder Verhaltensindikator wird gegen die Historie geprüft, bevor er eingebaut wird.**
> Kein Signal geht in Ampel, Depot oder Strategie, solange nicht an unseren eigenen Daten
> gemessen ist, ob es dort trägt. Literatur und ein Erreichbarkeitstest reichen ausdrücklich
> nicht — das ist die Lücke, die diese Session hinterlässt (siehe „Offene Fragen"), und sie
> gilt für alle Kandidaten der Landkarte: VIX-Terminstruktur, Marktbreite, AAII, Short
> Interest, Put/Call. Maßstab ist der Volumen-Test dieser Session: identisches Sample,
> Walk-Forward, und `significance.py` für die Frage, ob n überhaupt reicht — ein Nullbefund
> wird genauso berichtet wie ein Treffer.

### Nico

1. **`DASH_TOKEN` erneuern** — der alte ist in einem früheren Chat-Protokoll gelandet.
2. **Namensliste der beobachteten Investoren bestätigen** oder erweitern (`evidence/voices.py`,
   aktuell 8 Fondsmanager) — reine Ja/Nein-Entscheidung.
3. **Cockpit einmal am Handy durchklicken**: `http://100.99.224.50:8420` über Tailscale. Neu
   drin: „Wer handelt gerade" unter der Marktlage, Aussagekraft-Zeile und Verlustanatomie pro
   Handelsspur.
4. **Entscheiden, ob ein Server für ~5 €/Monat kommt** — Begründung ist Verfügbarkeit (heute ist
   die Tageskette zweimal ausgefallen), nicht Geschwindigkeit. Details in der Server-Analyse.
   Nichts gebucht.
5. **Zur Kenntnis:** Das Depot verhält sich ab heute Nacht anders (mehr Kapital investiert). Die
   Kurve vor und nach der Umstellung sind zwei getrennte Serien — das weist das System aus.
6. **Zur Kenntnis:** `docs/sessions/` ist in diesem Repo **nicht** gitignored, die Session-Docs
   liegen also auf dem öffentlichen GitHub. Keine Secrets darin (geprüft), aber Projektinterna
   und deine Zitate. Wenn dir das nicht passt: sag es, dann ändere ich es — ich fasse
   `.gitignore` nicht ungefragt an.

### Nächste Session (Agent)

- **W0 — HISTORISCHER ABGLEICH, blockiert W1–W6.** Nicos ausdrückliche Anweisung (siehe Kasten
  oben): kein Indikator wird eingebaut, ohne vorher an unseren eigenen Daten gemessen zu sein.
  Konkret für den ersten Kandidaten: VIX-Terminstruktur (^VIX9D/^VIX/^VIX3M) über die
  vorhandene Panel-Historie gegen Forward-Renditen testen — identisches Sample, Walk-Forward,
  `significance.py` für „reicht n überhaupt", und die Baker-Wurgler-Asymmetrie separat prüfen
  (wirkt das Signal nur in einer Richtung?). Erst wenn es trägt, geht es in `regime.py`.
  Nullbefund ist ein gültiges Ergebnis und wird genauso dokumentiert wie bei Volumen.
  Dasselbe Gate gilt für jeden weiteren Kandidaten, nicht nur den ersten.
- Danach W2–W6 laut `docs/research/2026-08-11-behavioural-indicator-landscape.md`.
- Rest von v16-Welle 2: Kosten-Netting über Handelsspuren; die Session-Lane nutzt nur 10 % ihres
  Broker-Kapitals.
- Der `insights`-Schritt der Tageskette passt nicht in sein 12-Minuten-Budget (heute per Timeout
  abgeschnitten). Erst einen einzelnen Aufruf messen, dann `--limit` senken oder eigener
  Cron-Slot.
- Mi 12.08.: erste `entry_predictions`-Auflösungen prüfen (`run_evidence_refresh.py`).

## Einstieg für die nächste Session

Branch `autopilot/work` = `main` = `origin/main` = `d001f60`, Tree sauber, Gate 1957 grün.
Erster Blick: `docs/research/2026-08-11-behavioural-indicator-landscape.md` (Wochenplan) und die
offene Frage oben — **W0 „historisch testen" fehlt und muss vor W1**. Ein CronCreate-Wächter
läuft alle zwei Stunden (:37) auf diesen Plan; er arbeitet aktuell W1 an, also entweder W0
einschieben oder den Wächter-Prompt anpassen. Für W0 passt `writing-plans` nicht — es ist ein
Messschritt, kein Feature. Keine Secrets in dieser Doku; Alpaca-Keys und `DASH_TOKEN` liegen in
`.env`.
