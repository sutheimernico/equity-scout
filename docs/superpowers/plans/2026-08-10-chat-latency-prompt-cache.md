# Plan: Chat-Latenz — stabiles Präfix statt kurzer Prompts (2026-08-10)

## Auftrag

Nico: „hab nur den laptop für Rechenleistung" → „ja fix das alles erstmal lokal so wie es
geht". Also: Assistent schneller machen, ohne GPU, ohne bezahlte API.

## Was gemessen wurde (und was davon meine Vorannahme widerlegt hat)

### 1. Die Hardware ist nicht der Hebel

Intel Iris Xe (integriert, kein dediziertes VRAM). Ollama unterstützt Intel-iGPUs nicht
offiziell, und selbst mit einem SYCL-Backend teilt eine iGPU den Speicherbus mit der CPU —
genau die Ressource, die LLM-Inferenz limitiert. Kein realistischer Gewinn.

### 2. Prompt-Längen (last-unabhängig, vor den Fixes)

| Fragetyp | Prompt-Token |
|---|---|
| Aktienfrage | 1.652 |
| Empfehlung | 1.794 |
| Überblick | 1.665 |
| Strategie | 1.408 |
| Person | 821 |
| Lexikon | 463 |
| Depot | 332 |

Damit war meine erste Hypothese („60–106 s bis zum ersten Token ⇒ Prompt hat 6.000–11.000
Token") **falsch**. Bei 103 tok/s Prefill kostet eine Aktienfrage ~16 s, nicht 100 s. Die
historischen Zahlen entstanden vermutlich unter Last oder mit Kaltstart.

### 3. Der eigentliche Befund: Ollama cached das Prompt-Präfix

| Lauf | prompt_eval_count | Prefill |
|---|---|---|
| A: Präfix + Frage 1 | 1480 | **108,6 s** |
| B: *gleiches* Präfix + andere Frage | 1478 | **2,3 s** |
| C: *anderes* Präfix | 672 | **42,7 s** |
| D: gleiches Präfix + Frage 3 | 1478 | **1,8 s** |

Faktor ~50 zwischen Cache-Treffer und Cache-Fehler. Damit kippt die Optimierungsrichtung:
**ein stabiles Präfix ist wertvoller als ein kurzes.** Das bisherige Topic-Trimming des
Glossars (`glossary_for`) baute pro Themenkombination ein anderes Präfix und warf den Cache
bei jedem Themenwechsel weg — es optimierte die erste Frage und verteuerte alle folgenden.

## Umgesetzt

- [x] **T1 Substring-Routing gefixt** (`chat_retrieval.route_topics`). `any(w in q)` behandelte
      jedes Keyword als Substring; drei feuerten in fremden Wörtern:
      `hält` in „Was **hältst** du von Microsoft?" → Depot-Block (~157 Token);
      `offen` in „**offensichtlich**" → Inbox-Block;
      `ml` in „Sa**mml**ung" → Strategie-Block + Strategie-Wissen (~739 Token).
      Kosten sind nur die Hälfte des Problems — ein themenfremder Block ist das, worüber ein
      7B-Modell dann antwortet. Matching jetzt am Wortanfang verankert (deutsche Flexion und
      Komposita brauchen das: `kennzahl`→„Kennzahlen", `markt`→„Marktlage"), drei Keywords
      zusätzlich mit Wortende (`_WHOLE_WORD_ONLY`).
- [x] **T2 Überblick-Fallback unterdrückt, wenn die Frage einen Anker hat** (`api._chat_context`).
      Direkte Folge von T1: mit korrektem Routing war `["ueberblick"]` der einzige Treffer bei
      „Was hältst du von X?" — und der Fallback zieht JEDEN Block. Der Prompt wuchs dadurch
      1.652 → **2.985** Token, das Gegenteil der Absicht. Eine erkannte Aktie oder Person IST
      der Anker; der Fallback bleibt für Fragen ohne jeden Anker.
- [x] **T3 Glossar konstant statt getrimmt** (`chat.glossary_for`). Immer das volle Glossar,
      an fester Position ganz vorn. Begründung = Messung 3.
- [x] **T4 ADVICE_BRIEF hinter das Glossar** (`api._chat_context`). Als erster Block änderte er
      das Präfix für jede Empfehlungsfrage und zerstörte genau den Cache, den T3 aufbaut.
- [x] **T5 Tests**: Substring-Fallen + erhaltene Flexion, Fallback-Unterdrückung, konstantes
      Glossar (ersetzt die alte „trimmt Abschnitte"-Erwartung), Brief-Position in beiden
      Chat-Pfaden.

## Ergebnis (Prefill-Anteil, der nach dem ersten Aufruf noch bezahlt wird)

Gemeinsames Präfix über **alle** Fragetypen: 668 Token — nach dem ersten Aufruf gratis.

| Fragetyp | vorher | jetzt | neu zu rechnen |
|---|---|---|---|
| Lexikon | 6,5 s | **0,0 s** | 0 Token |
| Depot | 8,0 s | **1,5 s** | 157 |
| Person | 12,8 s | **6,3 s** | 647 |
| Aktienfrage | 14,5 s | **8,0 s** | 827 |
| Strategie | 18,5 s | **12,0 s** | 1.233 |
| Überblick | 21,0 s | **14,5 s** | 1.491 |
| Empfehlung | 22,2 s | **15,7 s** | 1.619 |

(Zeiten bei 103 tok/s Prefill = gemessene Ruhe-Rate. Die absoluten Werte skalieren mit der
Systemlast, das Verhältnis nicht.)

## Grenzen, ehrlich benannt

- **Alle Zeitmessungen dieser Runde liefen unter Fremdlast** (parallele Session mit 5
  `scan.py`-Prozessen, Load 7→16). Die last-unabhängigen Größen — Prompt-Token, Präfix-Länge,
  Cache-Treffer-Verhältnis — sind belastbar; absolute Sekundenwerte sind es nicht.
- **Der 1.5b-Vergleich ist ungültig**: unter Last generierte qwen2.5:1.5b mit 4,2 tok/s
  *langsamer* als 7b mit 5,9 tok/s. Physikalisch unmöglich, also reines Rauschen. Ein
  Modellwechsel bleibt ungeprüft und ist NICHT umgesetzt.
- Der Cache hält einen Präfix-Zustand; abwechselnde Fragen teilen weiterhin das Glossar-Präfix,
  aber ein Dossier-Wechsel (MSFT → AAPL) rechnet den Dossier-Teil neu. Das ist korrekt.
- `MAX_ANSWER_TOKENS = 400` bleibt unangetastet: das Cockpit streamt (`/api/chat/stream`),
  die gefühlte Wartezeit ist das Prefill, nicht die vollständige Antwort.

## Outcome

Der Live-Qualitätstest fand einen echten Antwort-Defekt und führte zu einem fünften Task.

### T6 (ungeplant): Hausbegriffe brauchten ein eigenes Routing-Topic

Erster Live-Lauf, „Was ist die Einstiegszone?": **121 s** und die Antwort *„Es wird nicht im
gegebenen Datenkontext erwähnt…"* — falsch, denn die Definition stand im Glossar direkt über
den Daten. Ursache: der Begriff traf kein Keyword, also griff der Überblick-Fallback und
schüttete das ganze Dashboard in den Prompt; das Modell antwortete über die Daten statt über
die Definition. Neues Topic `begriffe` (Hausvokabular + „was bedeutet/was ist ein/was heißt")
bekommt bewusst **keinen** Datenblock — das Glossar ist ohnehin immer da.

`signal-filter` steht absichtlich in `begriffe` UND `strategien`: „Wie gut ist der
Signal-Filter?" will die Zahlen. Verboten ist nur der Whole-Dashboard-Fallback.

### Gemessen, nach dem Fix (Load 3,3 — Fremdlast war abgeklungen)

| Frage | vorher | jetzt |
|---|---|---|
| „Was ist die Einstiegszone?" | 121 s, **falsche** Antwort | **8 s**, korrekte Definition |
| „Was bedeutet Meldeverzug?" | — | **11 s**, korrekt inkl. 800-Tage-Vorbehalt |
| „Wie steht mein Depot?" | — | **23 s** (noch unter Load 10), Zahlen korrekt |
| „Was hältst du von Microsoft?" | 169 s | unverändert fundiert, keine Regression |

Prompt-Token bei Begriffsfragen: 2.159 → **668**, und das sind exakt die 668 Token des
gecachten Präfixes — also **null** neu zu rechnende Token.

### Keine Regression bei Aktienfragen — und warum das strukturell so ist

Bei einer Aktienfrage war das Glossar schon vorher vollständig (`has_dossier=True` zog alle
drei Abschnitte). Der Umbau auf ein konstantes Glossar ändert dort am Prompt-Inhalt nichts;
mehr Glossar bekommen nur Depot-, Strategie- und Begriffsfragen — und die profitieren.

### Gate

1879 Tests grün, ruff clean.

### Offen (nicht in dieser Runde, bewusst)

- **Zwei Modellschwächen, unabhängig von dieser Änderung**, im MSFT-Lauf sichtbar: das Modell
  nannte ein Perzentil „F-Score … 59/100", obwohl das Glossar „F-Score (Piotroski, 0-9)"
  definiert, und erfand das Wort „Hoheitswertverhältnis" für das Kurs-Buchwert-Verhältnis.
  Beides ist Ausdruck eines 7B-Modells, nicht des Prompt-Aufbaus — ein Fix müsste am
  Dossier-Wording ansetzen (Kennzahlen mit ihrer Skala beschriften).
- Die MSFT-Antwort wurde von `MAX_ANSWER_TOKENS = 400` mitten im Satz abgeschnitten.
- **Modellwechsel auf qwen2.5:1.5b bleibt ungeprüft** — der Vergleich lief unter Fremdlast und
  lieferte Unsinn (1.5b langsamer als 7b). Bei Ruhe wiederholbar, jetzt nicht getan.
