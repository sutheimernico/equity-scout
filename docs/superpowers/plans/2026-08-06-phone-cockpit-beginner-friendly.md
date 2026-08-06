# Handy-Cockpit einsteigerfreundlich machen — Implementierungsplan

> **Für den ausführenden Agenten:** Dieser Plan setzt die Arbeit vom 05./06.08. fort.
> Vorgeschichte und Begründungen stehen in
> `docs/sessions/2026-08-05_phone-cockpit-insights-and-autotrader.md` (vier Nachträge) —
> **vor Task 1 lesen**, besonders die dort dokumentierten Fehlschläge, damit sie nicht
> wiederholt werden.
>
> Empfohlen: `superpowers:subagent-driven-development` oder `superpowers:executing-plans`.

**Leitmotiv (Nicos Worte, 06.08.):** „Arbeite einmal komplett drüber und wirklich aus der
Sicht eines totalen Vollidioten draufzuschauen. Also checkt man das? Es soll halt sehr
einsteigerfreundlich sein." Der Informationsgehalt der Ansichten ist gut — die
Verständlichkeit ist das Problem.

**Grundregel für jede Änderung:** Nichts schönrechnen, nichts verstecken. Wo eine Zahl
fehlt oder eine Aussage nicht belegbar ist, sagt die UI das (dieses Projekt hat sich das
mehrfach erarbeitet — siehe „zu teuer", „noch günstiger", NaN-Kurse).

---

## Was schon fertig ist (nicht erneut anfassen)

Handy-Fokus-Tabs, Deeplinks, Service Worker, Freshness-Banner, KI-Texte + 1-Jahres-Chart
mit Achsen, Zonen-Meter, Potenzial als Hauptzahl mit Label, deutsche Schlagzeilen,
Long-Term-Donut + ETF-Klartext, Day-Trader-Switch mit „Läuft noch"/„Abgeschlossen",
Stroke-Icons, neutrale Palette (Marke = Blau, Grün/Rot nur Richtung).

Gate-Stand am Ende der letzten Session: **1348 Python-Tests, 61 vitest, ruff clean,
tsc exit 0.**

---

## Bereits ermittelte Fakten (Recherche NICHT wiederholen)

| Frage | Befund |
|---|---|
| Wo kommen die Alerts her? | `api.py:842` → `load_alerts(db_path, limit=20)`; Rows tragen `ticker`, **keinen Firmennamen** |
| Firmennamen-Quelle | Watchlist (`radar_storage.load_latest_watchlist` → `entries[].name`) und `run_scores` (`storage.load_run_scores` → `name`). Für off-watchlist Ticker gibt es evtl. keinen Namen → dann Ticker zeigen |
| Inbox-Buttons | `InboxPanel.tsx:170-195`, CSS `.pitch-actions` (`index.css:1504`) ist `display:flex; gap` **ohne** wrap; **kein** Mobile-Override gefunden. Ursache des Umbruchs ist daher vermutlich die Button-Breite (`padding: var(--space-2) var(--space-4)` = 24 px seitlich × 3 Buttons). Messen, nicht raten |
| Tokens | `--text-secondary`, `--text-primary`, `--radius-pill` existieren (je 1× definiert) |
| „Beweis"-Label | `views.ts:35` (NAV) und `views.ts:50` (MOBILE_LABELS) |
| ETF-Klartext | `frontend/src/etfs.ts`, `ETF_NOTES[ticker] = {name, what}` — 21 ETFs hinterlegt |
| Lane-Bezeichnungen | `shortterm_storage.LANE_LABELS` existiert bereits (prüfen, was drinsteht); Lanes sind `swing`, `session`, `crypto` |
| Assistent | `ChatPanel.tsx` → `POST /api/chat` (`api.py:691`) → `chat.ask_ollama` mit `build_dashboard_context`. Ollama läuft als User-Service (`scripts/install_ollama_service.sh`), Modell `qwen2.5:7b` |
| Modellqualität | `qwen2.5:7b` ist gesetzt; `llama3.1:8b` wurde **zweimal gemessen und war schlechter** (52,8 s statt 7,1 s, ignorierte Prompts). Nicht erneut testen |
| CJK-Falle | qwen antwortet auf Übersetzungs-Prompts gern chinesisch; `insights.split_bullets` filtert CJK. Bei **jedem** neuen LLM-Prompt für Deutsch beachten |

## Arbeitsumgebung

```bash
cd ~/private/equity-scout
# Gate
.venv/bin/python -m pytest -p no:warnings --tb=line -rf | tail -2
.venv/bin/python -m ruff check .
cd frontend && npm test && npx tsc --noEmit && npm run build

# Deploy (nötig nach JEDER Backend-Änderung; dist/ liest StaticFiles pro Request)
systemctl --user restart equity-scout-dash.service

# Screenshot auf Handy-Viewport (Chromium aus dem Playwright-Cache, kein Playwright-Paket)
CHROME=/home/nicosutheimer/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome
"$CHROME" --headless --disable-gpu --no-sandbox --hide-scrollbars \
  --force-prefers-reduced-motion --window-size=390,1400 --virtual-time-budget=9000 \
  --screenshot=/tmp/shot.png "http://127.0.0.1:8420/?view=today"
```

`--force-prefers-reduced-motion` ist Pflicht: ohne es triggert die `.reveal`-Animation in
Headless unzuverlässig und zeigt leere Kästen (wurde einmal als App-Bug fehlgedeutet).
Loopback ist vom Token-Gate ausgenommen, `127.0.0.1` braucht also keinen Token.

**Zum Prüfen von aufgeklappten Zuständen** gibt es kein CDP-Setup: temporär
`useState(true)` setzen, bauen, Screenshot, zurücksetzen, neu bauen. Nicht vergessen —
einmal ist ein Screenshot mit dem alten Build entstanden, weil der Rückbau nicht gebaut
wurde.

---

## Task 1: ETF-Namen direkt in der Long-Term-Liste

**Dateien:** `frontend/src/components/PhoneDepot.tsx` (`EtfRow`), `frontend/src/index.css`

Nico: „dass dieser High dann halt auch zumindest bei den plus zehn Prozent oder plus fünf
Prozent da irgendwie Namen drinstehen."

Aktuell zeigt die Zeile nur den Ticker; der Klartext liegt hinter dem Tap. Bei den großen
Positionen soll der Name schon in der Zeile stehen.

- [ ] **Schritt 1:** In `EtfRow` unter dem Ticker `ETF_NOTES[ticker]?.name` als zweite,
  kleinere Zeile rendern — aber nur, wenn `Math.abs(weight) >= 0.05`. Begründung im
  Kommentar: bei elf Positionen würde jede Zeile zweizeilig und die Liste wieder zur
  Wand; die kleinen Positionen behalten den Namen hinter dem Tap.
- [ ] **Schritt 2:** Layout prüfen — `.pd-alloc-main` ist ein Flex-Row. Der Name braucht
  eine eigene Spalte (Ticker + Name links untereinander, Balken/Prozent/Betrag rechts).
- [ ] **Schritt 3:** Screenshot 390 px: kein Seitwärts-Scrollen, Balken nicht zerdrückt.
- [ ] **Schritt 4:** Commit.

## Task 2: Aufklappen mit Pfeil, Inhalt darunter

**Dateien:** `PhoneDepot.tsx` (`EtfRow`, `OpenPosition`), `StockList.tsx` (`BriefRow`),
`index.css`

Nico: „mach am besten, dass es dadrunter aufgeklappt wird. Das heißt, dass da irgendwie so
ein Pfeil nach unten ist und darunter aufgeklappt wird."

Der Inhalt klappt schon darunter auf — was fehlt, ist der **sichtbare Hinweis, dass die
Zeile aufklappbar ist**. Ein Chevron, der sich beim Öffnen dreht.

- [ ] **Schritt 1:** Chevron in `frontend/src/components/ui/TabIcon.tsx` ergänzen (dort
  liegt schon das Stroke-Icon-Set mit einheitlichem 24er-Raster und `currentColor`) —
  oder eine kleine eigene `Chevron`-Komponente daneben. Nicht als Emoji/Unicode: die
  Session vom 06.08. hat Emoji-Glyphen genau deswegen entfernt.
- [ ] **Schritt 2:** In allen drei aufklappbaren Zeilen rechts einsetzen, mit
  `transform: rotate(180deg)` im offenen Zustand und einer kurzen Transition.
  `aria-expanded` ist überall schon gesetzt — nicht doppelt beschriften.
- [ ] **Schritt 3:** Screenshot beider Zustände, Commit.

## Task 3: Day-Trader-Lanes klar trennen und erklären

**Dateien:** `PhoneDepot.tsx` (`LaneCard`, `DayTrader`), `index.css`, evtl. neue
`frontend/src/lanes.ts`

Nico: „die sind noch nicht klar abgetrennt. Da steht läuft noch, läuft noch zweimal.
Crypto, dann Session, Swing — macht da irgendwie ein i für Info hin, dass sie deutlich
erläutert sind und klarer abtrennen."

Drei Lanes mit je zwei Untergruppen erzeugen sechs gleich aussehende Überschriften.

- [ ] **Schritt 1:** Klartext-Namen und Erklärungen je Lane hinterlegen (analog `etfs.ts`,
  z. B. `frontend/src/lanes.ts`). Prüfen, ob `shortterm_storage.LANE_LABELS` schon
  brauchbare Namen hat — **wenn ja, die verwenden statt neue zu erfinden** (sonst driften
  Backend und UI auseinander). Vorschlag für die Erklärungen, fachlich gegen
  `st_swing.py` / `st_session.py` / `st_crypto.py` verifizieren:
  - `swing`: hält Aktien einige Tage nach guten Nachrichten (Ziel +5 %, Stop −3 %, max. 7 Tage)
  - `session`: kauft am Morgen aus der Eröffnungsspanne und ist zum Handelsschluss flach
  - `crypto`: folgt Ausbrüchen bei Kryptowährungen, Stop −2 %, Ausstieg am 10-Tage-Tief
- [ ] **Schritt 2:** Jede Lane wird eine **abgesetzte Karte** (eigene Fläche
  `--bg-inset`, Radius wie die anderen Karten, Abstand dazwischen) statt nur einer
  Trennlinie. Der Lane-Kopf trägt Klartextnamen + kleines Info-Icon (ⓘ als Stroke-Icon),
  das die Erklärung aufklappt.
- [ ] **Schritt 3:** Die Untergruppen-Überschriften eindeutig machen. „Läuft noch" /
  „Abgeschlossen" mehrfach untereinander liest sich als Wiederholung — z. B. in die
  Kartenstruktur einrücken oder als Zähler formulieren („2 laufen noch", „5 abgeschlossen").
- [ ] **Schritt 4:** Screenshot, Commit.

## Task 4: „Was zuletzt passiert ist" — Firmennamen statt Ticker

**Dateien:** `src/equity_scout/api.py` (`/api/evidence`), `frontend/src/components/TodayView.tsx`,
Test in `tests/test_api.py`

Nico: „Da steht V — 2 Kongressmitglieder haben gekauft. UNH — 2 Kongressmitglieder haben
gekauft. Ich kann damit nichts anfangen. Was ist V? Du musst da schon die Aktien
hinschreiben."

`V` = Visa, `UNH` = UnitedHealth. Für einen Einsteiger ist ein Ticker keine Information.

- [ ] **Schritt 1 (Test zuerst):** `/api/evidence` liefert pro Alert-Row ein zusätzliches
  `name`-Feld. Test: ein Alert auf einem Watchlist-Ticker bekommt den Namen; ein Alert auf
  einem unbekannten Ticker bekommt `null` (und die UI zeigt dann den Ticker — **kein
  erfundener Name**).
- [ ] **Schritt 2:** Namens-Lookup serverseitig: Watchlist-Entries und `load_run_scores`
  des letzten Runs zu einem `{ticker: name}`-Dict zusammenführen. Beides ist bereits
  geladen bzw. billig; **kein** yfinance-Call im Request (das Projekt hat sich diese Regel
  mit dem 6-h-Cache in `fundamentals.py` erarbeitet).
- [ ] **Schritt 3:** Frontend: `shortCompanyName(name)` nutzen (existiert in
  `frontend/src/company.ts`), Ticker klein dahinter. Gleiche Darstellung wie die
  Aktienliste, damit dieselbe Firma überall gleich aussieht.
- [ ] **Schritt 4:** Auch prüfen, ob der **Alert-Text selbst** verständlich ist. „2
  Kongress-Mitglieder haben gekauft" ist ok; andere Alert-Gründe (`reasons[0]`) können
  Fachjargon sein — Stichprobe über die letzten 20 Alerts ziehen und die kryptischen
  übersetzen.
- [ ] **Schritt 5:** Gate, Screenshot, Commit.

## Task 5: Inbox-Entscheidungen in eine Zeile

**Dateien:** `frontend/src/index.css` (`.pitch-actions`, `.pitch-btn`)

Nico: „Bei den Entscheidungen kaufen, ablehnen und später fängt jedes Mal eine neue Zeile
an. Sorg dafür, dass es in einer Zeile steht."

- [ ] **Schritt 1: Ursache messen, nicht raten.** `.pitch-actions` ist `display:flex` ohne
  `flex-wrap`, und ein Mobile-Override wurde nicht gefunden — der Umbruch kommt also
  vermutlich aus der Button-Breite (seitliches Padding `var(--space-4)` = 24 px × 3) oder
  einem `flex-wrap` weiter oben in der Kaskade. Per `--dump-dom` bzw. Screenshot auf
  390 px verifizieren, welche Regel greift.
- [ ] **Schritt 2:** Im Mobile-Block seitliches Padding reduzieren und `flex-wrap: nowrap`
  setzen; die drei Buttons als `flex: 1` gleich breit. 44 px Mindesthöhe bleibt Pflicht.
- [ ] **Schritt 3:** Screenshot auf 390 px: eine Zeile, alle drei Labels vollständig
  lesbar (nicht abgeschnitten), Tap-Ziele ≥ 44 px.
- [ ] **Schritt 4:** Commit.

## Task 6: Sortierung und Wording der Einstiegs-Bewertung

**Dateien:** `frontend/src/components/RadarPanel.tsx` bzw. die Ansicht, in der
„Einstieg schwach / neutral / stark" erscheint — **zuerst mit `grep -rn "Einstieg schwach"
frontend/src` finden**; `src/equity_scout/pitch.py` (`_VERDICT_LEVELS`)

Nico: „die ganzen Einstiege schwach oben, aber Einstieg neutral dann weiter unten. Also
macht schon Sinn, absteigend zu sortieren. Des Weiteren sind dann Aktien, die gar keinen
Einstieg neutral haben, Einstieg stark."

- [ ] **Schritt 1:** Die Ansicht finden und den Ist-Zustand per Screenshot festhalten.
- [ ] **Schritt 2:** Absteigend sortieren (stark → neutral → schwach). Die Bänder kommen
  aus `pitch._VERDICT_LEVELS` (<40 / 40–70 / ≥70, mit Abzug bei sehr schwachem
  Teilsignal) — **dort ist die einzige Quelle**, nicht im Frontend nachbauen.
- [ ] **Schritt 3:** Titel ohne Bewertung: prüfen, warum sie keine haben (kein Score? kein
  Reading?) und sie **als eigene Gruppe am Ende** zeigen, nicht mit einem geschätzten Band
  auffüllen.
- [ ] **Schritt 4:** Gate, Screenshot, Commit.

## Task 7: „Ergebnisse" — die Ansicht verständlich machen (Umbenennung ist erledigt)

**Dateien:** `frontend/src/views.ts:35,50`, `frontend/src/components/ProofView.tsx`,
`src/equity_scout/proof.py` (nur lesen)

Nico: „Bitte anderes Naming für Beweis — was soll ein Beweis sein? Das musst Du auch noch
mal das Prinzip überarbeiten, da checkt man gar nix."

Die Ansicht zeigt, ob die Paper-Depots nach Kosten tatsächlich etwas geliefert haben
(Sharpe/CAGR ab 60 Tagen, MaxDD, Trefferquote, Kostenanteil, vs. Benchmark, Urteil).

- [x] **Schritt 1: ERLEDIGT 2026-08-06.** Nico hat „Ergebnisse" gewählt und der Tab ist
  umbenannt — inklusive `ProofView`-Kopfzeile, dem Verweis im Monatsbericht
  (`digest.py`: „Monats-Ergebnisbericht", Tab-Verweis) und README. Der technische View-Key
  bleibt `proof`: die Telegram-Deeplinks zeigen auf `?view=proof`, ein Umbenennen hätte
  jeden bereits verschickten Link gebrochen. **Es bleibt also nur die inhaltliche Arbeit
  unten.**
- [ ] **Schritt 2:** Ansicht neu aufbauen mit **einer Leitfrage pro Block**, in
  Alltagssprache: „Hat es mehr gebracht als einfach den Markt zu kaufen?" · „Wie viel ist
  zwischenzeitlich verloren gegangen?" · „Wie viel davon frisst die Gebühr?" · „Reicht die
  Datenmenge überhaupt für ein Urteil?"
- [ ] **Schritt 3:** Fachbegriffe erklären, wo sie nötig sind (Sharpe, Drawdown,
  Kostenanteil): kurzer Klartext hinter einem ⓘ, nicht im Fließtext.
- [ ] **Schritt 4:** Das bestehende Ehrlichkeits-Verhalten NICHT abschwächen: unter 60
  Tagen liefert `proof.book_report` bewusst kein Sharpe/CAGR. Diese Lücke muss sichtbar
  bleiben („zu wenig Historie für ein Urteil").
- [ ] **Schritt 5:** Gate, Screenshot, Commit.

## Task 8: Assistent prüfen — beantwortet er Aktienfragen?

**Dateien:** zunächst nur Messung; dann `src/equity_scout/chat.py`
(`build_dashboard_context`), `frontend/src/components/ChatPanel.tsx`

Nico: „schauen wir, ob der Assistent in der Lage ist, mittlerweile auch jegliche Fragen zu
irgendwelchen Aktien zu beantworten."

- [ ] **Schritt 1: Messen, bevor etwas geändert wird.** Ollama läuft als User-Service.
  Fünf echte Fragen über `POST /api/chat` stellen und die Antworten wörtlich protokollieren:
  1. „Was macht Micron und warum ist die Aktie im Radar?"
  2. „Wie steht mein Auto-Depot im Vergleich zum Markt?"
  3. „Warum wurde Yamato nicht gekauft?"
  4. „Was bedeutet die Einstiegszone?"
  5. „Soll ich Micron kaufen?" ← **muss ablehnen** (keine Anlageberatung)
- [ ] **Schritt 2:** Bewerten: Welche Fragen kann er aus `build_dashboard_context`
  überhaupt beantworten, welche fehlen im Kontext? Der Kontext enthält heute Strategien/
  ML-Zahlen — **prüfen, ob Watchlist, Briefs, Insights und Depots darin vorkommen.**
- [ ] **Schritt 3:** Ergebnis dokumentieren, DANN entscheiden, was der Kontext braucht.
  Kein Umbau vor der Messung.
- [ ] **Schritt 4:** Falls erweitert wird: Guardrail beibehalten — der LLM interpretiert
  nur vorhandene Zahlen, keine Prognosen, keine Empfehlungen (`chat.SYSTEM_PROMPT`,
  gleiche Regel wie `pitch.py`).

## Task 9: Alle „Mehr"-Ansichten einsteigerfreundlich (der große Durchgang)

**Betroffen:** `FunnelView`, `RadarPanel`, `VoicesPanel`, `StrategyDashboard`,
`ModelPanel`, `MLPanel`, `LearningCurvePanel`, `ChatPanel`

Nico: „die sind ja ganz gut vom Informationsgehalt. Das Problem ist, sie sind halt alle
komplett unübersichtlich und dann checkt man nix. Was ganz gut aussieht, ist Signal-Filter."

**Das ist kein Ein-Task-Paket.** Vorgehen:

- [ ] **Schritt 1:** Bestandsaufnahme. Von jeder der acht Ansichten einen Screenshot auf
  390 px machen und in EINEM Dokument sammeln
  (`docs/research/2026-08-XX-mehr-ansichten-review.md`), je Ansicht notiert:
  - Welche Frage beantwortet sie in einem Satz?
  - Welche Begriffe darin versteht ein Einsteiger nicht?
  - Was ist Kontext und könnte hinter einen Tap?
- [ ] **Schritt 2:** `Signal-Filter` (`MLPanel`) als Referenz analysieren — Nico findet die
  Ansicht gut. Herausarbeiten, WARUM (wahrscheinlich: eine Leitfrage oben, wenige Zahlen,
  Klartext-Urteil) und daraus ein Muster für die anderen sieben ableiten.
- [ ] **Schritt 3:** Pro Ansicht eine eigene, kleine Runde mit Screenshot-Vergleich davor/
  danach. Nicht alle acht in einem Commit.
- [ ] **Schritt 4:** Nach jeder Ansicht Gate + Screenshot; erst danach die nächste.

Muster, das sich in dieser Session bewährt hat und hier gelten sollte:
1. **Eine Leitfrage pro Block**, in Alltagssprache, als Überschrift.
2. **Höchstens eine große Zahl** pro Karte — zwei konkurrieren miteinander.
3. **Fachbegriff = Klartext dahinter oder hinter ⓘ**, nie unerklärt.
4. **Fehlende Daten sichtbar machen**, nie mit einem Platzhalterwert füllen.
5. **Tiefe hinter einen Tap**, nicht in die Liste.

---

## Bewusst nicht in diesem Plan

- **Kein Modell-Kursziel.** Braucht einen registrierten `entry_tb`-Champion; ohne den
  bleibt „Potenzial" der Analysten-Konsens (so von Nico entschieden).
- **Kein News-Einfluss auf die Rangfolge.** Wäre ein Funnel-Eingriff und nach Hausregel
  backtestpflichtig (eigenes Ledger, DSR-Hürde).
- **Kein Modellwechsel bei Ollama.** `llama3.1:8b` wurde zweimal gemessen und war
  schlechter und 7× langsamer.
- **Kein Web Push.** Telegram bleibt der Anstoß; die Links tragen den Token.

## Offene Punkte für Nico (nicht durch diesen Plan gelöst)

1. ~~Neuer Name für „Beweis"~~ — entschieden: **„Ergebnisse"**, umgesetzt am 06.08.
2. **Qualität der lokalen KI-Texte.** `qwen2.5:7b` schreibt holpriges Deutsch
   („Gewinnsträften"). Besser würde nur ein größeres lokales Modell (RAM) oder eine
   bezahlte API — letzteres berührt die private Kostengrenze und braucht seine Entscheidung.
3. **Telegram-Token-Rotation** steht weiter offen; der Token liegt inzwischen im
   Session-Transcript und in der Telegram-Historie (auf Nicos ausdrücklichen Wunsch).
4. `autopilot/work` → `main` mergen/pushen.
