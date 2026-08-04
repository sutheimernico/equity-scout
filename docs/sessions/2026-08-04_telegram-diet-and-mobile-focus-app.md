# 2026-08-04 — Telegram-Diät + Handy-Fokus-App

Ausgangspunkt: Nico war mit den Telegram-Benachrichtigungen beider Seiten (Autotrader
und Empfehlungs-Funnel) unzufrieden — „unübersichtlich, zu lang". Seine Vermutung war ein
Formatierungsproblem (mehr Absätze). Die Messung zeigte etwas anderes.

## Diagnose (gemessen, nicht geschätzt)

| Fläche | Vorher | Nachher |
|---|---|---|
| Täglicher Digest | 55 Zeilen / 2.313 Zeichen, 10 Sektionen | 17 Zeilen (15 + 2 Spacer) / 718 Zeichen |
| Pitch-Caption | bis 980 Zeichen, 4 Blöcke, 5–10 Stück in Folge | 4 Zeilen |
| Nächtlicher Auto-Depot-Push | 1 Zeile pro Trade (12 Mikro-Rebalances à ~60 $ = 12 Zeilen) | nur materielle Trades (≥ 1 % Buchgewicht), sonst gar keine Nachricht |

Das Problem war nicht die Formatierung — Absätze gab es seit dem 16.07.-Redesign. Es war:
alles wurde jeden Tag komplett gepusht, ohne Wesentlichkeitsschwelle, mit Wiederholung
(dieselben sechs offenen Pitches seit dem 16.07.) und ohne Handlungsbezug.

Leitbild: **drei Nachrichtenklassen** — LAUT (Handlungsbedarf/Störung), LEISE (ein
Tageskopf), NIE (Nachschlagewerk → Dashboard). Bindende Regel: nichts aus Telegram
entfernen, was im Dashboard nicht sichtbar ist. Deshalb sind Evidenz-Trefferquoten
(`stats_by_source` wird von KEINER Frontend-Komponente gerendert) und der
Earnings-Kalender (kein API-Endpoint) nur kondensiert, nicht gelöscht.

## Zwei Bugs, gefunden beim Nachsehen

1. **`run_notify.py:156` crashte seit dem 21.07.** — `from scripts.run_digest import …`
   fand kein Package `scripts`, weil die Cron-Kette das Skript als Pfad startet
   (`python scripts/run_notify.py` legt `scripts/` in `sys.path`, nicht den Repo-Root).
   Folge: **zwischen 21.07. und 04.08. ging kein einziger Pitch per Telegram raus** — die
   Kette loggte `FAILED notify` und lief weiter.
2. **Derselbe Import in `run_autotrader.py`** steckte in einem `except Exception` →
   `regime_level = None` → **das Regime-Gate griff seit dem 24.07. nie**. Der Autotrader
   handelte ohne Marktlage-Filter, still.

Fix: Repo-Root vor dem Sibling-Import verankern; die Degradation im Regime-Collector
warnt jetzt auf stderr. Regressionstest per Subprocess (`tests/test_script_path_invocation.py`),
weil der Pytest-Prozess den Repo-Root ohnehin im Pfad hat und ein Unit-Test die
Regression nicht gefangen hätte — gegengeprüft, dass der Test ohne den Fix rot wird.

## Was umgesetzt wurde

**Digest** (`src/equity_scout/digest.py`): Auto-Depot 7 → 3 Zeilen (Tagesbewegung in die
Kopfzeile gefaltet, Trades nach Materialität zusammengefasst), Arena 8 → 1 Zeile plus
Störungen, Chancen/Pitches/Earnings/Evidenz je eine Zeile. Offene Pitches listen nur noch,
was seit `decided_since` NEU ist. Deutsche Zahlenformatierung (`format_de`,
`format_de_pct`) — öffentlich, weil der nächtliche Push dieselben Zahlen formatiert.
Entfernt wurde nur, was das Dashboard zeigt: Exposure/Drawdown/Anker-Notiz, die
Prüfstand-Zähler pro Lane, die Alert-Liste (VoicesPanel), der Unter-Schwelle-Zähler.

**Deeplinks**: mit `DASH_URL` wird jede Abschnitts-Überschrift ein Link in die passende
Cockpit-Ansicht (`?view=depots|radar|inbox`). Query-Parameter statt Pfad, weil
`StaticFiles` bei `/depots` 404 liefern würde. Ersetzt den wöchentlichen Dashboard-Hinweis.

**Handy-App** (`frontend/`): vier Fokus-Tabs unter 720 px (🏠 Heute · 🤖 Depot ·
📬 Entscheiden · 🧾 Beweis) plus „⋯ Mehr"-Sheet für die anderen acht Ansichten; Desktop
unverändert. View-State in der URL (`parseView`, `replaceState`). Service Worker
(`es-v1`) mit App-Shell-Precache und Netz-zuerst-mit-Cache-Fallback für `/api/*`;
POST-Entscheidungen werden nie gecacht. Banner nennt bei Ausfall den letzten
erfolgreichen Kontakt, geprüft über den neuen, absichtlich billigen `/api/health`
(kein DB-, kein Feed-Zugriff — `/api/regime` hätte alle 30 s yfinance-Calls bedeutet).

## Verifikation

- **1207 Tests grün** (`pytest`), `ruff check .` clean, Frontend: 11 vitest-Tests grün,
  `tsc --noEmit` exit 0, Build ok, `dist/sw.js` ausgeliefert.
- Echter Digest gegen die Live-DB gerendert: 17 Zeilen / 718 Zeichen.
- **Echter Digest an Telegram gesendet** (`run_digest.py --force`), kein Pending → Zustellung ok.
- Token-Gate über Tailscale geprüft: 401 ohne Token, 200 mit Header-Token. Loopback ist
  bewusst ausgenommen (`api.py:152`).
- `equity-scout-dash.service` neu gestartet (nötig für `/api/health`), `sw.js` und
  `manifest.webmanifest` werden über Tailscale ausgeliefert.
- `DASH_URL=http://100.99.224.50:8420` an `.env` angehängt (Tailscale-Node `wsl-claude`).

## Abweichungen von den Plänen

- Plan 1 Tasks 1–4 wurden inline statt per Subagent umgesetzt (eine Datei, aufeinander
  aufbauend). Ab Task 5 Subagents.
- Der Digest landet bei 17 statt ≤ 16 Zeilen; zwei davon sind Leerzeilen als Struktur.
- Nach dem Digest-Umbau brachen 18 Tests in vier weiteren Dateien, die im Plan nicht
  erfasst waren (`test_autotrader_digest`, `test_digest_sections`, `test_digest_v8`,
  `test_shortterm_digest`) — nachgezogen, Absichten erhalten, wo ein Feature entfiel in
  explizite „bewusst nicht gerendert"-Zusicherungen umgeschrieben.
- Ein Review-Fund am Subagenten-Commit: bei mehr als 5 materiellen Trades wurden die
  überzähligen als „kleine Rebalance" gezählt. Getrennt in „+N weitere über der Schwelle"
  und „N kleine Rebalance", mit Regressionstest.
- Drei Absenz-Tests waren nach dem Umbau trivial wahr (prüften Wörter, die der Renderer
  nicht mehr kennt) — auf die aktuellen Marker geschärft.
- `vite-env.d.ts` musste ergänzt werden (erste `import.meta.env`-Nutzung im Projekt).

## Offen / Needs Nico

1. **Walk-Through am Handy**: `http://100.99.224.50:8420/?token=<DASH_TOKEN>` einmal
   öffnen (Token wandert ins Cookie), zum Startbildschirm hinzufügen, dann aus dem
   Digest eine Überschrift antippen — die App muss direkt im richtigen Fokus öffnen.
   Danach eine Entscheidung unter „Entscheiden" durchklicken und WSL einmal ausschalten,
   um Banner + Cache zu sehen.
2. **Pitches kommen erst wieder mit dem nächsten 18:00-Lauf** — die Caption-Änderung ist
   ungetestet gegen echte Telegram-Zustellung, weil seit dem 21.07. keine Pitches liefen.
3. `stats_by_source` (Evidenz-Trefferquoten) wird im Dashboard weiterhin nicht gerendert.
   Solange das so ist, muss die kondensierte Digest-Zeile bleiben.
4. Telegram-Token-Rotation steht weiter offen (aus früherer Session).


---

## Nachtrag: Handy-UX-Runde (2026-08-04, nach Nicos Feedback)

Nico: „mach die benutzerfreundlicher" + „ich erwarte da gerade heiße Aktien zu sehen und
die ausgeschriebenen Unternehmen wie Microsoft mit Logo".

Vier Befunde, alle per Screenshot auf 390×844 belegt (Chromium aus dem Playwright-Cache,
`--force-prefers-reduced-motion`, weil die `.reveal`-Animation in Headless sonst
unzuverlässig triggert und leere Kästen zeigt — das war zuerst als App-Bug fehlgedeutet):

1. **Alle Views scrollten seitwärts.** Headlines und Karten liefen über den rechten Rand.
2. **Der erste Bildschirm war Deko** — Titel plus drei Zeilen Onboarding-Prosa, dann eine
   Kachel pro Zahl (~130 px). Drei Kennzahlen = drei Bildschirme.
3. **Aktien erschienen nur als Ticker** (`9064.T · 9022.T`).
4. **Die Inbox-Buttons lagen unter der Textwand** — Entscheiden erforderte Durchscrollen.

Umgesetzt: Overflow-Regeln (`overflow-x: clip`, Umbruch, Tabellen scrollen selbst),
Erklärtexte auf Handy aus, KPI-Zeile zweispaltig mit halbiertem Padding, neue Sektion
„Aktuell vorne" mit Logo + Firmenname, Inbox-Karten mit Namenskopf und Entscheidung vor
Begründung, Logo-Endpoint mit lokalem Cache.

Zwei eigene Regressionen dabei gefunden und behoben:
- `overflow-wrap: anywhere` zerriss `29861 $` zu `2986 1 $` — eine falsch lesbare Zahl ist
  in einer Finanzansicht schlimmer als Overflow.
- Die erste Korrektur wirkte nicht, weil `.view *` (0,1,0) spezifischer ist als `td`
  (0,0,1). Danach war `nowrap` auf allen Zellen ebenfalls falsch (versteckte die
  Equity-Spalte hinter horizontalem Scrollen); jetzt brechen Zellen nur an Leerzeichen.

Befund des Logo-Subagenten, festgehalten weil kontraintuitiv: eine Byte-Schwelle kann den
„kein Favicon"-Platzhalter des Anbieters NICHT erkennen — der Platzhalter ist 726 Bytes,
ein echtes Microsoft-Logo nur 426. Erkennung läuft deshalb über einen SHA-256-Abgleich des
bekannten Platzhalters.

Gate: 1227 Python-Tests grün, ruff clean, 22 vitest-Tests grün, `tsc --noEmit` exit 0.


## Nachtrag 2: Aktien-Steckbrief (2026-08-04)

Nico: „man checkt nichts da, ich will auf den ersten Blick sehen was ich sehen muss, was
wäre ein guter Preis, sind wir da drin, was wäre Zielpreis zum Wiederausstieg, dann News-
Zusammenfassung durch KI, minimal auch pitchen was das Unternehmen macht."

Neu: `GET /api/briefs` bündelt pro Watchlist-Titel Name, Sektor/Branche, Kurs, Zone samt
Klartext-Urteil, Analysten-Konsens mit Upside, KGV und Score-Band; die Karte im Frontend
zeigt das in Leserichtung, Details (Zonengrenzen, Score, KGV, Modell-Kursziel) hinter
einem Tap.

Datenlage, geprüft und nicht schöngeredet:
- **Kein Modell-Kursziel.** `entry.compute_target_stop` liefert None, weil KEIN
  `entry_tb`-Champion registriert ist. Die Karte sagt genau das („kein trainiertes
  Modell") statt eine Zahl zu erfinden. Zielpreis kommt daher nur als Analysten-Konsens,
  klar als fremde Meinung gelabelt.
- **`fundamentals.py` hatte keinen Cache** — jedes App-Öffnen wären fünf yfinance-Calls
  gewesen. Jetzt 6-h-TTL im Prozess (0,86 s → 0,008 s gemessen); ein all-None-Ergebnis
  wird NIE gecacht, weil genau so ein rate-limitierter Fehlschlag aussieht.
- Offen aus Nicos Wunschliste: **die KI-Texte** (ein Satz „was macht die Firma", News-
  Zusammenfassung). Ollama ist installiert und die Modelle liegen lokal (`qwen2.5`,
  `llama3.1`), aber der Server läuft nicht — deshalb steht in den Pitches auch
  „Automatische Kurzeinschätzung nicht verfügbar". Geplanter Weg: Generierung in der
  18:00-Kette + Cache in der DB, nicht live im HTTP-Request (10–30 s Latenz wären auf dem
  Handy unbrauchbar).

### Vorbefund, NICHT gefixt (außerhalb des Auftrags)

`tests/test_entry_model.py::test_calibrated_model_scores_through_the_calibrator` ist
flaky: bei drei vollen Suite-Läufen fiel er zweimal durch und war einmal grün, isoliert
immer grün. Er prüft `plain_scores + calibrated_scores == 100` exakt; der elastic-net-Solver
weicht threadabhängig minimal ab und kippt damit eine Rundungsgrenze. Unabhängig von der
Arbeit dieser Session (die berührt kein ML-Training). Fix wäre eine Toleranz von ±1 in der
Assertion — Nicos Entscheidung, nicht ungefragt mitgefixt.


## Nachtrag 3: Zielbereich als Balken (2026-08-04)

Nico: „probier mal im Dashboard das visuell zu zeigen, also Zielbereich nicht mit Text
sondern so Balken."

Neu: `frontend/src/zone.ts` (pure Geometrie, 13 vitest-Tests) + `ZoneBar.tsx` — ein
Bullet-Balken pro Steckbrief mit drei Bändern (günstiger · guter Einstieg · zu teuer),
Kurs als Nadel mit Kopf, Analysten-Ziel als violette Raute; die Zonengrenzen stehen jetzt
sichtbar unter den Bandkanten statt nur hinter dem Tap.

**Skala normalisiert statt preis-proportional:** Fenster = Zone ± eine Zonenbreite, die
Zone ist damit immer das mittlere Drittel. Preis-proportional wäre Microns Zone bei 70 %
Abstand zum Kurs ~3 px breit gewesen, und jede Karte hätte eine andere Skala. Die Achse
misst also Abstand in Zonenbreiten, nicht in Währung — deshalb tragen nur die beiden
Grenzzahlen eine Beschriftung, keine Achsenticks, und die echte Prozentzahl bleibt in der
Verdict-Zeile. Kurse außerhalb des Fensters bekommen einen Pfeil am Rand, keinen an die
Kante geklemmten Marker (das würde eine Position behaupten, die der Kurs nicht hat).

Drei Befunde, die erst durch Messen/Ansehen kamen:

1. **Farben gemessen, nicht geschätzt.** Erste Wahl (Bänder als 42 %/38 %-Mischungen)
   trennte Grün↔Amber nur mit ΔE 11,6 für *normale* Farbsicht — also für alle schlecht
   unterscheidbar. Auf 60 %/55 % gehoben → ΔE 15,5. Deuteranopie liegt bei ΔE 7,9, was nur
   zulässig ist, weil Bandposition, die 2-px-Lücken, die gedruckten Grenzen und das ✓/⚠
   der Verdict-Zeile die Bedeutung unabhängig von der Farbe tragen. Nicht weiter dimmen.
2. **Die Nadel war vom Bandtrenner nicht zu unterscheiden** (beides dünne vertikale
   Linien) — sie hat jetzt einen Kopf. Erst im Screenshot aufgefallen.
3. **Auf Desktop (Karte ~875 px) las der Balken als gestreckte, leere Schiene** und die
   Grenzzahlen lösten sich von ihren Kanten → `max-width: 460px`.

Eigener Review-Fund am fertigen Code: Der Balken war als `role="img"` mit Label gebaut.
Die Zeile ist aber ein `<button>`, also wäre das Label in seinen Accessible Name gefaltet
worden und ein Screenreader hätte Kurs, Zone und Urteil doppelt vorgelesen. Jetzt
`aria-hidden` — die Aussage steht vollständig als Text darunter, die exakten Grenzen im
Detail hinter dem Tap.

Ein Test fand sofort einen falsch konstruierten Testfall: „Kurs unter dem Fenster" ist bei
einer Zone von 100–200 unerreichbar, weil die Fenster-Untergrenze (2·low − high) dort auf 0
fällt und kein gültiger Kurs darunter liegen kann. Realistisch sind enge Zonen — Tele2
154,3–167,0 hat die Untergrenze bei 141,6.

Gate: 35 vitest-Tests grün, `tsc --noEmit` exit 0, Build ok. Python unberührt, daher nicht
neu gelaufen. Kein `CACHE_VERSION`-Bump nötig: Navigationen laufen network-first und Vite
content-hasht die Assets, der Service Worker liefert also von sich aus die neue Version.

### Vorbefund, NICHT gefixt (außerhalb des Auftrags)

Die Analysten-Zeile bricht auf 390 px um und der Fortsetzungstext
(„(11 Schätzungen, fremde Meinung)") hängt ohne Einzug am linken Rand — bestand vor dieser
Runde, fällt mit dem Raute-Swatch davor nur mehr auf.

### Korrektur direkt danach: das linke Band war eine Fehlaussage

Nico am Balken: „der graue Balken ganz links macht nicht so viel Sinn, das doch alles unter
der Linie basically grün." Die Intuition ist fachlich falsch, die Kritik am Band trifft aber
zu — und die Ursache war ein Wording-Fehler aus dieser Session.

`radar.entry_zone` baut die Zone aus Support-Levels: `high = max(supports)` (auf SMA200
gedeckelt), `low = max(min(supports) − ATR, min(supports) × 0.8)`. Unter `zone_low` heißt
also nicht „billiger", sondern: alle Supports sind gefallen, plus ein ATR Puffer darunter —
kein Halt mehr darunter. `radar.zone_note` sagt das seit je („tiefer als die Support-Levels"),
und `in_zone` ist ein Pitch-Gate (`notify.py:73`, `lanes.py:172`): unter der Zone wird so
wenig gepitcht wie darüber.

`briefs.zone_gap` textete das aber als **„noch günstiger"** — ein Kaufsignal, das dem
eigenen Konzept widersprach und genau so gelesen wurde. Jetzt „Support gebrochen", in Schritt
mit `zone_note`; Regressionstest schließt „günstig" in dieser Aussage aus. Das linke Band ist
entsprechend amber wie das rechte: beide Seiten sind ein „nicht jetzt", die Seite trägt der
Marker, den Grund die Verdict-Zeile.

Lehre für künftige Runden: Die Zone ist ein Support-Band, kein Fair-Value-Band. Formulierungen
in dieser Fläche müssen mit `radar.zone_note` übereinstimmen, sonst erzeugt das Dashboard
Kaufsignale, die der Funnel nie gegeben hat.
