# Session 2026-08-08 ~00:10 — Cockpit-Umbau auf Mockup v2 (stehender Auftrag)

## Kontext & Ziel
Der SessionStart-Hook trug den stehenden Auftrag (Nicos Go vom 07.08., „freie Macht"):
Handy-Cockpit auf die Mockup-v2-Struktur umbauen — Persona „Alex, 31", redundanzfrei,
13 Views → 5 Tabs + Mehr, ein kanonisches Aktienprofil. Nico fragte zu Session-Beginn,
ob die Handoffs (Assistent + App) komplett umgesetzt sind: Assistent war fertig, der
Cockpit-Umbau noch nicht begonnen → in dieser Session komplett umgesetzt.

## Ergebnis
**9 Commits (`c130f88..e65f495`) auf `autopilot/work`, deployt auf :8420, Playwright-
Smoke auf Phone-Viewport (alle Kern-Views als Screenshots verifiziert).**
Details und Abweichungen: Outcome-Abschnitt in
`docs/superpowers/plans/2026-08-07-cockpit-rebuild-from-mockup-v2.md` (jetzt DONE —
der SessionStart-Hook schweigt ab jetzt).

Kern: neue v7-IA (Heute · Aktien · Entscheiden · Depot · Mehr + Profil-Route +
Chat-Overlay hinter FAB), `StockProfileView` als das eine Drill-down, `AktienView` als
die eine Liste (Zonen-Segmente + Risiko-Chips), Depot 7→3 Sichten mit „Funktioniert
es?"-Kopf, Labor/Wer-kauft?/Wie-funktioniert-das? unter Mehr. Backend: stack-breakdown-
Bug gefixt, Briefs mit bucket + Scout-Ziel (Provenance), Company mit Kennzahlen aus dem
Quote-Cache, Pitch-Kontext mit bucket.

## Fallen, die diese Session gekostet haben
1. **`.chip-row` existierte schon** (generischer Status-Chip-Container) — meine neue
   Filterleiste hätte sie global überschrieben. Eigene Klasse `.style-chips`.
2. **`.brief-detail` ist ein dt/dd-Grid** — `<div>`-Wrapper um Paare brechen das Layout
   still. Fragments verwenden. Und die auto-Spalte quetscht lange Labels auf einen
   Buchstaben pro Zeile → `white-space: nowrap` am dt + `overflow-wrap` am dd.
3. **`zone_gap` lieferte beidseitig positive Werte**, `entry_note` testete auf `< 0` —
   der Below-Zone-Zweig war toter Code, Support-gebrochen-Titel lasen sich falsch.
   Sichtbar erst auf der neuen Karte, wo beide Texte nebeneinander stehen.
4. **git stash für Teil-Commits ist riskant:** `--keep-index` stashte die
   Working-Tree-Hälfte einer zusammengehörigen Änderung — der erste Commit wäre allein
   nicht lauffähig gewesen (api.py rief build_brief mit einem Argument auf, das briefs.py
   im Commit nicht kannte). Soft-Reset + ein konsistenter Commit.

## Offen / Needs Nico
1. **App auf dem Handy durchklicken** — Link kam per Telegram. Detailwünsche einfach in
   der nächsten Session sagen.
2. **DASH_TOKEN rotieren** (empfohlen): ist beim Playwright-Smoke im Session-Transcript
   gelandet. Tailscale-only erreichbar, daher kein akutes Risiko.
3. **Insider-Events (Form 4)** weiterhin nicht in der DB — Nightly sollte nachholen,
   morgen prüfen.
4. **merge nach main** wie immer deine Entscheidung; autopilot/work ist grün.

## Nachtrag gleiche Session (Nico live im Chat, 4 Aufträge)

1. **Insider-Käufe wieder screenen** → Root Cause war KEIN Rate-Limit: Die SEC liefert
   `primaryDocument` inzwischen als `xslF345X06/primarydocument.xml` (HTML-Rendering) —
   der Collector scheiterte seit Tagen an JEDEM US-Ticker. Fix: XSL-Präfix strippen
   (rohes XML liegt an der Accession-Wurzel), Regressionstest, Live-Lauf: 17/30 Ticker
   sauber, erstes Insider-Event in der DB (PKBK, CEO-Kauf ~44 T$).
2. **„Kann nichts kaufen/ablehnen"** → kein Bug: 0 offene Pitches (28 unter der
   Qualitätsschwelle am 07.08., 1 gekauft, 27 verfallen). UI-Fix: ehrliche
   Leerzustand-Karte in Entscheiden (warum nichts offen ist + Link zu Aktien).
3. **Autopilot-Verwirrung** → jede Depot-Sicht erklärt jetzt, wonach ihr Automat kauft
   (Langfrist: ETF-Regeln, nie Einzelaktien; Kurzfrist: 3 feste Taktiken; „Du": der
   Vergleichs-Zwilling, der jeden In-Zone-Scout-Vorschlag automatisch kauft);
   „Wie funktioniert das?" benennt alle drei.
4. **Assistent soll empfehlen (Policy-Wende!):** Nicos Direktive — private App, er WILL
   Empfehlungen. Feste Ablehnung raus; Advice-Fragen laufen durchs LLM mit
   EMPFEHLUNGS-AUFTRAG (Urteil + Fakten + Risiko + Kipp-Bedingung) und offenen Pitches
   im Kontext; System-Prompt erlaubt begründete Favoriten; kuratiertes
   KNOWLEDGE_STRATEGIES (Maßstab „beste" + Einordnung aller 8 Regelwerke). Live-Eval:
   3/3 Empfehlungs-Fragen PASS, Strategie-Antwort nennt Favorit Multi-Strategie-Mix mit
   Begründung + ehrlichem „Forward-Track zu jung". Eval-Cases an den neuen Vertrag
   angepasst. Hinweis: README-Framing („research assistant, not investment advice")
   bleibt fürs öffentliche Repo bestehen — die Empfehlungs-Funktion ist Nicos privater
   Betrieb.

Gates nach dem Nachtrag: 1741 Backend- + 110 Frontend-Tests, Build, deployt.
Kaltstart nach Service-Neustart gemessen: 228 s bis zum 1. Token (Modell-Reload),
warm 75–101 s bei Empfehlungs-Fragen (längerer Kontext) — die GPU/API-Frage wird
mit dem Empfehlungs-Modus noch relevanter.

## Einstieg für die nächste Session
Branch `autopilot/work`, alles committet und deployt. Der Cockpit-Hook ist stumm
(Outcome: DONE). Parallelstrang v15 (P2/P3) wartet weiter auf Nicos Go — Koordination
beachten (api.py war in dieser Session heiß, ist jetzt frei).
