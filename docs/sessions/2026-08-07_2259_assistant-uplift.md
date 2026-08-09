# Session 2026-08-07 (Arbeitszeit ~12:55–14:05) — Assistent-Uplift „alles alles"

## Kontext & Ziel

Nicos Auftrag: *„mach mal den Assistenten krass in der App mit Dashboard für Aktien, es
sollte ein Plan stehen, mach das in einer Loop, der sollte in der Lage sein alles zu Aktien
zu beantworten, KGV, Kennzahlen, welche Mitglieder gekauft haben etc, also alles alles."*

Ausgangslage: Der Plan `docs/superpowers/plans/2026-08-07-assistant-uplift.md` existierte
bereits aus der Vormittagssession (11 Tasks, wartete auf Nicos Go). Die Messung davor
(`docs/research/2026-08-07-assistant-measurement.md`) hatte 4 von 5 Referenzfragen als FAIL
protokolliert. Der Auftrag war zugleich das Go **und** eine Erweiterung: Der Plan deckte
Kennzahlen und Personen nur am Rand ab.

## Ergebnis

**23 Commits auf `autopilot/work`**, von `2f17563` bis `0932899` (dazwischen liegen Commits
des parallelen Strangs, siehe unten).

- **Plan erweitert** um „Teil B — Vollabdeckung" (Tasks 12–17), begründet aus einer
  Datensichtung: `quote_cache` hatte 7 778 Titel mit allen Kennzahlen, die der Plan nicht
  anfasste; `evidence_events` 890 Kongress-Käufe, die der geplante 30-Tage-Filter fast
  vollständig weggeschnitten hätte.
- **Alle 17 Tasks umgesetzt.** Architektur, Datei-Landkarte und Task-Details stehen im Plan;
  der Outcome-Abschnitt dort listet die Abweichungen. Kern: `src/equity_scout/chat_retrieval.py`
  (neu) macht das gesamte Retrieval deterministisch **vor** dem LLM.
- **Messung: 15/15 inhaltlich korrekt** (vorher 4/5 FAIL), wiederholbar über
  `scripts/eval_chat.py --stream`. Vollständiges Protokoll inkl. Latenzaufschlüsselung in
  der Mess-Doku.
- Deploy ist durch: `systemctl --user restart equity-scout-dash.service`, Modell warm
  (`/api/ps` zeigt `qwen2.5:7b`, `context_length: 8192`, `expires_at` +24 h).

## Entscheidungen

- **Task 3 index-basiert statt Regex-Sweep gebaut**, obwohl der Plan einen Regex-Scan
  vorgab — Task 12 hätte ihn sonst sofort weggeworfen. Test-Vertrag blieb identisch.
- **Alle rein alphabetischen Ticker matchen nur in ihrer Schreibweise** (nicht nur kurze,
  wie geplant): Live gegen 6 197 Titel kollidieren 4-Buchstaben-Ticker regelmäßig mit
  deutschen Wörtern. Preis: „nvda" klein getippt findet nichts, „NVDA"/„Nvidia" schon.
- **Personen-Erkennung läuft unabhängig vom Keyword-Routing**, weil „Was hat Tuberville
  zuletzt gekauft?" auf „gekauft" = Depot-Thema routet und die Evidenz sonst nie erreicht.
- **Evidenz-Fenster 400 statt 30 Tage** — im Bestand stehen Meldeverzüge bis 867 Tage.
- **Kein Modellwechsel, kein Vektor-RAG, kein Function-Calling** (Plan-Vorgabe eingehalten).
- **yfinance-Lookup für unbekannte Symbole** bewusst gegen die Plan-Regel „kein Live-Fetch
  im Request" — genau ein Lookup pro Frage über den bestehenden 6-h-Cache, sonst wäre
  „alles alles" nicht erfüllbar. Im Plan als Abweichung dokumentiert.

## Fallen, die diese Session gekostet haben (alle mit Regressionstest)

Diese stehen so in keinem Commit-Text und sind der eigentliche Wert dieses Dokuments:

1. **Das Suffix-Regex aus dem Plan hatte keine Wortgrenze** — `s\.?a\.?$` fraß das Ende von
   „Vi**sa**", `co$` das von „Cis**co**". Beide Titel wären für den Assistenten unauffindbar
   gewesen, ohne dass ein Test angeschlagen hätte.
2. **`_GENERIC_FIRST_WORDS` hat 38 Einträge, nicht 4 836** — die 4 836 waren der Output des
   Drift-Scanners aus v13/Q4, nicht die Liste selbst. Meine Plan-Notiz war falsch; die Liste
   musste um deutsche Funktionswörter ergänzt werden.
3. **Ollamas `num_ctx`-Default (4 096) schneidet still ab.** Bei einem Vier-Aktien-Vergleich
   wäre der System-Prompt mit den Guardrails als Erstes herausgefallen — ein Korrektheits-,
   kein Performance-Problem. Jetzt explizit 8 192.
4. **Ein Warmup mit abweichenden Options ist schlimmer als kein Warmup.** Ollama lädt das
   Modell neu, sobald sich `options` ändern: `warm_model()` lud mit Default-Fenster, die
   erste echte Frage forderte 8 192 → Neuladen → 241 s Timeout. Identische Options sind
   Pflicht, Test dafür in `tests/test_chat.py`.
5. **Latenz-Messungen zwischen Läufen sind nicht vergleichbar.** Dieselbe Frage lag in
   Lauf 1 bei 2,8 s und in Lauf 3 bei 106 s bis zum ersten Token — bei kleinerem Kontext.
   Ursache ist der llama.cpp-Prompt-Cache. Ich hatte daraus zwischenzeitlich voreilig
   „Faktor 10 schneller" geschlossen und das gegenüber Nico korrigiert.

## Offene Fragen

- **Lohnt eine GPU?** `/api/ps` zeigt `size_vram: 0` — das Modell rechnet vollständig auf
  der CPU (~10–17 Token/s Prompt-Verarbeitung). Aktienfragen tragen 1 000–2 000 Prompt-Token,
  daraus folgen die 60–106 s bis zum ersten Wort. Kein Prompt-Tuning ändert daran etwas.
- **Ist die Schieflage der Offenlegungsdaten ein Bug oder die Realität der Quelle?** 654 von
  890 Käufen stammen von `senate_alan_armstrong` (Partei `None`), 164 von einem
  Exekutiv-Filer (`Donald J Trump`, `chamber=executive`). Der Assistent benennt beides
  ehrlich, aber die Verteilung sieht nach einem Sammel-Artefakt des kadoa-Backfills aus.
- **Soll `brief.model_target` denselben Weg gehen?** Der parallele Strang hat den
  Heuristik-Fallback bewusst dort ausgelassen — Berührungspunkt mit dem Cockpit-Umbau.

## To-dos

### Nico

1. **Assistent ausprobieren.** Cockpit öffnen (http://127.0.0.1:8420), Tab „Assistent", eine
   Aktienfrage stellen — z. B. „Wie hoch ist das KGV von Micron?" oder „Welche Mitglieder
   haben Intel gekauft?". Rechne mit 30–100 Sekunden bis zum ersten Wort; solange steht
   „liest die Daten…" in der Antwortblase.
2. **Entscheiden, ob dir das Tempo reicht.** Wenn nicht, gibt es drei Wege: eine Grafikkarte
   nutzen, ein kleineres Modell (schlechtere Antworten) oder eine bezahlte API — Letzteres
   kostet Geld und braucht deine ausdrückliche Zustimmung.
3. **RAM prüfen.** Das Modell bleibt jetzt 24 Stunden geladen und belegt rund 5 GB. Wenn dein
   Rechner dadurch träge wird, sag Bescheid — dann stellen wir das auf 30 Minuten zurück.
4. **Entscheiden, ob der Stand nach `main` soll.** Der Zweig `autopilot/work` ist grün.
5. **Wissen, dass die Kongress-Daten schief liegen:** Drei Viertel aller Käufe stammen von
   einer einzigen Person, und ein Teil kommt gar nicht aus dem Kongress, sondern aus der
   Regierung. Der Assistent sagt das ehrlich dazu — trotzdem gehört das beim nächsten
   Daten-Nachladen korrigiert.

### Nächste Session (Agent)

- `docs/sessions/` ist in diesem Repo **nicht** gitignored (die älteren Session-Dokumente
  sind committet). Bewusst nicht angefasst — Nico entscheidet, ob das so bleibt.
- Offener Plan-Schritt: nur noch Task 11 Step 2 (Handy-Smoke), gehört Nico.
- Beim vollen `pytest` schlagen zwei `/api/entry`-Tests fehl — die gehören dem parallelen
  Cockpit-Strang (uncommittete `resolve_target_stop`-Arbeit), nicht dem Assistenten. Vor
  einer Fehlersuche prüfen, ob dieser Strang inzwischen committet hat.
- Wenn die Latenz angegangen wird: zuerst messen, ob Ollama GPU-Layer nutzen kann
  (`OLLAMA_NUM_GPU`), bevor irgendetwas am Prompt gedreht wird. Prompt-Tuning ist
  nachweislich ausgereizt (28–59 % Kontext gespart, kein messbarer Latenzeffekt).
- Der Assistent hat noch **keine Chat-Historie** (jede Frage steht für sich) — bewusste
  Plan-Entscheidung („erst Qualität der Einzelantwort, dann Komfort"). Rückfragen wie „und
  wie sieht das bei Intel aus?" funktionieren deshalb nicht.

## Einstieg für die nächste Session

Branch `autopilot/work`, Repo `~/private/equity-scout`. Der Assistent ist fertig und
deployt; Stand und Begründungen im Outcome-Abschnitt von
`docs/superpowers/plans/2026-08-07-assistant-uplift.md`, Zahlen in
`docs/research/2026-08-07-assistant-measurement.md`. Vor jeder Änderung am Chat:
`.venv/bin/python scripts/eval_chat.py --stream` als Vorher-Messung fahren (braucht den
Dash-Service auf :8420 und Ollama). Achtung: In diesem Repo arbeitet parallel ein zweiter
Strang am Cockpit-Redesign (`company_api.py`, `entry.py`, `frontend/`) — Commits nur mit
expliziten Pfaden.
