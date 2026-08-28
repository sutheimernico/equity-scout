# Session 2026-08-27 16:20–22:00 — Handy-Push, APK, Investierbarkeitsfilter, Diversifikations-Studie

## Kontext & Ziel

Nico war rund fünf Stunden weg und hat einen offenen Auftrag hinterlassen: Push-Meldungen
**von der App selbst** (nicht nur Telegram), die App „live stellen" und als APK beziehbar
machen, täglich laufen lassen, frühzeitig über Chancen informieren — mit KI-Begründungen,
die ein Laie versteht —, das Frontend übersichtlicher machen und „die Systematik hinter dem
Autotrader weiterentwickeln", Fernziel: ein Autotrader, der den Markt schlägt.

Gearbeitet wurde durchgehend auf `autopilot/work`, 12 Commits (`a66c1eb` … `7776154`),
**nicht gepusht**. Gate am Ende: 2 707 pytest, 197 vitest, ruff sauber. Der Dash-Service
läuft mit dem neuen Stand.

Erzählender Überblick als Artifact (für Nico geschrieben, nicht für den Agent):
https://claude.ai/code/artifact/cfb4f5bb-1e96-4319-b630-ce8ad28e7335

## Ergebnis

Details stehen in `PLAN.md` (Abschnitt „Runde 2026-08-27"), `AUTOPILOT_LOG.md`, `README.md`
und `docs/research/2026-08-27-diversification.md`. Hier nur, was dort **nicht** steht.

**Push-System** (`a66c1eb`, `c552f56`) — `channels.deliver` ist der einzige Fan-out;
`push.py`/`push_storage.py` (Web Push, VAPID), `ntfy.py` (Reserve), Telegram unverändert.
Ansicht `AlarmeView` + `PushSetup` + `OpportunityList`, Endpunkte `/api/push/*` und
`/api/opportunities`. ntfy wurde **live gegen ntfy.sh getestet** (Zustellung bestätigt);
Web Push konnte nicht end-to-end verifiziert werden, weil die HTTPS-Origin fehlt (Root).

**APK-Weg** (`d640b58`) — `.github/workflows/android-apk.yml` (Bubblewrap auf GitHub-Runner),
`scripts/setup_https.sh`, `/.well-known/assetlinks.json`, `docs/handy-app.md`. Der
Signaturschlüssel liegt unter `.state/android-keystore.p12` (gitignored) und als Repo-Secrets
`ANDROID_KEYSTORE_B64` / `ANDROID_KEYSTORE_PASSWORD` — beide über `gh secret set` gesetzt,
Werte stehen nirgends im Repo und nicht in diesem Dokument.

**Chancen-Meldungen** (`da9b984`, `2cd484b`, `4be8cce`) — `opportunity.py`,
`opportunity_storage.py`, `scripts/run_opportunities.py`, eingehängt in `daily_copilot.sh`
nach `notify`. `kaufplan_service.py` ist eine reine Extraktion aus `api.py`, damit Job und
Endpunkt dieselben Pläne sehen.

**Investierbarkeitsfilter** (`da9b984`, `693182f`) — `liquidity.py`, verdrahtet in
`pipeline.py`, `Quote` um `market_cap`/`avg_volume` erweitert, Quote-Cache-Migration über
`is_stale_schema`.

**Autotrader-Studie** (`cbce0eb`, `c903c98`) — `scripts/run_diversification_study.py`,
`duplicate_groups`/`split_within_groups` im Allocator, `/api/diversification` +
`HonestVerdict` im Cockpit.

**Frontend** (`8e141a6`) — `TodayAction` auf der Startseite, Logik in `today.ts` getestet.

**Nebenbei behoben:** der seit dem Vortag rote `test_watchdog.py`-Test las die
Produktions-`shortterm.db` (Needs-Nico-Punkt (c) der Nachtschicht) — jetzt hermetisch.

## Entscheidungen

- **TWA statt WebView für die APK**, obwohl aufwendiger: eine Android-WebView kann kein Web
  Push, und Push war der ganze Anlass.
- **`/.well-known/assetlinks.json` vor das Token-Gate gelegt** — Chrome holt die Datei ohne
  Cookie; dahinter liefe die App dauerhaft mit Adressleiste, ohne sichtbaren Grund.
- **ntfy zusätzlich zu Web Push**, obwohl redundant: Web Push hängt an einem Root-Schritt,
  den ich nicht ausführen konnte; ntfy funktioniert sofort und überlebt eine Neuinstallation.
- **Zweite Meldungsklasse „Bald" eingeführt**, statt die Qualitätsschwelle zu senken —
  sonst hätte das System am Starttag null Meldungen gehabt, und eine gesenkte Schwelle wäre
  genau der „Müll", gegen den die v8-Regel existiert.
- **Das LLM formuliert nur die Gründe um, nie die Gegenrede** — im Live-Test verlor sie den
  Stop-Kurs, also die einzige konkrete Zahl der Meldung.
- **Liquiditätsfilter schließt aus, statt zu ranken** — ein Titel ist investierbar oder
  nicht; „ein bisschen schlechter bewerten" ließe ihn bei genug Value-Punkten trotzdem durch.
- **Fail-open bei gescheiterter FX-Umrechnung, fail-closed bei fehlenden Rohwerten** — ein
  Infrastrukturausfall ist kein Befund über den Titel.
- **Duplikat-Erkennung liest nur die Forward-Reihen, nicht den Backtest**, obwohl DCA ≡ 60/40
  dort längst belegt ist: der Allocator entscheidet ausschließlich aus dem, was die Sleeves
  live gezeigt haben. Preis: greift erst ab ~Mitte September.
- **Inverse-Vol-Modus NICHT auf Gleichgewichtung zurückgestellt**, obwohl die Studie zeigt,
  dass Gleichgewichtung das bessere Rendite-Risiko-Verhältnis hat — der Unterschied ist ein
  fairer Tausch (1,1 pp CAGR gegen 1,8 pp Drawdown), und eine Rückabwicklung ohne Not würde
  nur einen laufenden Track brechen.
- **Screener-Lauf abgebrochen statt zu Ende laufen lassen** — er war mit dem Code von vor
  dem FX-Fix gestartet und hätte im schlechtesten Fall eine leere Watchlist gespeichert.

## Offene Fragen

- **Web Push ist ungetestet.** Der ganze Pfad (VAPID → FCM → Service Worker → Sperrbildschirm)
  ist gebaut und einzeln geprüft, aber nie am echten Gerät gelaufen. Der erste Test nach
  `setup_https.sh` ist der eigentliche Beweis.
- **Reicht der ntfy-Weg Nico als Dauerlösung?** Inhalte laufen unverschlüsselt über einen
  öffentlichen Server. Entscheidung liegt bei ihm, Abschalten ist ein `.env`-Eintrag.
- **Wie kommt der Screener je wieder durch?** 7 500 Titel gegen Yahoo-Drosselung; der
  Nachtlauf vom 27.08. starb mit rc=143, meiner kam auf 40 %. Der Nachtschicht-Befund
  (`--max-workers 2` war **schneller** als 6) ist weiterhin nicht umgesetzt.
- **Richtungsfrage Autotrader:** andere Anlageklasse oder anderer Horizont — oder das Ziel
  „schlägt den Markt" durch „zwei Drittel der Rendite bei halbem Risiko" ersetzen und die
  Oberflächen darauf ausrichten.

## To-dos

### Nico

1. **Einmal mit Root ausführen:** `sudo bash scripts/setup_https.sh`. Danach den
   Dash-Service neu starten. Ohne diesen Schritt gibt es keine App-Benachrichtigungen,
   keine installierbare App und keine sinnvolle APK.
2. **Auf dem Handy testen:** Cockpit über die Tailscale-Adresse öffnen → Chrome-Menü →
   „App installieren" → in der App unter *Mehr → Benachrichtigungen* einschalten. Es kommt
   sofort eine Testnachricht. Kommt sie nicht, sagt die Karte, woran es liegt.
3. **Optional: APK bauen** — auf GitHub unter Actions → „Android-APK" → Run workflow, als
   `host` die Tailscale-Adresse eintragen.
4. **Entscheiden, ob ntfy anbleibt.** Es läuft über einen öffentlichen Server; Firmenname,
   Kurs und Begründung gehen unverschlüsselt darüber.
5. **Richtungsentscheidung zum Autotrader:** Der aktuelle Aufbau schlägt den Markt nicht und
   wird es mit weiteren Strategien auf denselben zwanzig ETFs auch nicht. Entweder eine neue
   Anlageklasse dazu, oder das Ziel auf „ruhigeres Depot" umstellen.
6. **Weiterhin offen aus früheren Runden:** Telegram- und DASH_TOKEN rotieren, Windows-
   Energieeinstellungen, `--max-workers` in der Cron-Kette senken.

### Nächste Session (Agent)

- [ ] **Web Push end-to-end verifizieren**, sobald `PUBLIC_BASE_URL` gesetzt ist: Abo
      anlegen, `/api/push/test`, Zustellung in der Geräteliste prüfen (`last_ok_at`).
- [ ] **Screener-Lauf zu Ende bringen** — mit `--max-workers 2` (Befund 27.08. früh) und dem
      gefixten Code. Danach prüfen, wie die Watchlist nach dem Investierbarkeitsfilter
      aussieht; erst dann ist der Chancen-Job wirklich beurteilbar.
- [ ] **Ersten echten Lauf von `run_opportunities.py` in der Kette beobachten** (Mo–Fr nach
      `notify`) — insbesondere, ob nach dem Filter überhaupt Kandidaten übrig bleiben.
- [ ] **Duplikat-Erkennung ab ~Mitte September nachmessen**: greift sie, und welche Paare
      fasst sie zusammen? Erwartung laut Backtest: DCA ↔ 60/40.
- [ ] Prüfen, ob `docs/sessions/` in diesem Repo versioniert bleiben soll — hier sind die
      Dateien **eingecheckt**, anders als die Skill-Konvention es vorsieht. Nicht
      eigenmächtig ändern.

## Einstieg für die nächste Session

Branch `autopilot/work`, 12 unpushte Commits, Gate grün. Erste Frage: hat Nico
`scripts/setup_https.sh` ausgeführt? Wenn ja → Web Push am Gerät verifizieren (siehe
Agent-To-dos) und `docs/handy-app.md` um das Ergebnis ergänzen. Wenn nein → nicht darauf
warten, sondern den Screener-Lauf mit `--max-workers 2` starten; er ist die Voraussetzung
dafür, dass der Chancen-Job überhaupt etwas zu melden hat. Kontext zum Autotrader steht in
`docs/research/2026-08-27-diversification.md`; die Richtungsfrage dort ist eine
Nico-Entscheidung, kein Agent-Task.
