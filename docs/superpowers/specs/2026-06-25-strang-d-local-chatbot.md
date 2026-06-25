# Strang D — Lokaler Chatbot (Spec + Outcome)

Stand 2026-06-25. Vierter Strang. Branch `feat/multi-strategy-ml`.

## Ziel

Ein lokaler Chatbot, der Fragen zu den Dashboard-Daten beantwortet — komplett lokal, nichts verlässt
den Rechner. Keine Anlageberatung (gleiche Honesty-Guardrails wie überall).

## Entscheidungen

- **Ollama** (`localhost:11434`), offenes Modell (Default `llama3.2`, per `OLLAMA_MODEL` / `OLLAMA_HOST`
  konfigurierbar). „GPT lokal" / „Claude lokal mit geringerer Version" geht **nicht** — keine offenen
  Gewichte; Ollama + offenes Modell ist der realistische Weg (war von Anfang an die Ansage an Nico).
- **Kein RAG / keine Vektor-DB.** Die Dashboard-Daten sind klein + strukturiert: ein kompakter Snapshot
  der aktuellen Zahlen (Strategien, ML, Auto-Research/PBO, Forward) wird direkt in den Prompt gefaltet.
  Die einfachste Lösung, die das Ziel erfüllt — eine Vektor-DB wäre hier Overengineering.
- **Keine neue Dependency** — `httpx` (vorhanden) für den Ollama-Call.

## Umsetzung

- `src/equity_scout/chat.py`: `build_dashboard_context(...)` (kompakter Daten-Snapshot als Text) +
  `ask_ollama(question, context)` (robust; `ChatError` bei Nichterreichbarkeit/fehlendem Modell statt
  Hänger). System-Prompt erzwingt: nur aus den Daten antworten, keine Beratung, keine Kursprognosen.
- `POST /api/chat {question}` → `{answer}` bzw. `{error}` (503 bei `ChatError`). Sammelt Strategien,
  ML (nur wenn schon gecacht — kein teures Training im Chat-Request), Research/PBO, Forward.
- Frontend: `ChatPanel` + **„Assistent"-Tab** (4. Top-Nav), Beispiel-Fragen, Verlauf, Lade-/Fehlerzustand.

## Verifiziert

`/api/chat` live: ohne laufendes Ollama → klare 503-Meldung statt Hänger (graceful degradation, getestet
in der Sandbox, wo Ollama nicht läuft). Unit-Test für den Kontext-Builder. Alle Gates grün (`ruff`,
`pytest`, FE `typecheck`+`build`).

## Setup (Nico, lokal)

```bash
ollama serve            # falls nicht eh als Dienst läuft
ollama pull llama3.2    # oder ein anderes Modell + export OLLAMA_MODEL=<name>
```
Dann im „Assistent"-Tab fragen. Mit laufendem Ollama beantwortet der Chat Fragen wie „Welche Strategie
hat den besten Sharpe?", „Was sagt der PBO-Wert?", „Wie läuft der Forward-Track?".

## YAGNI / Abgrenzung

Kein Streaming (eine Antwort pro Frage reicht), kein Konversations-Gedächtnis über die Session hinaus,
kein Tool-Calling/Funktionsaufrufe (der Kontext-Snapshot genügt für die Datenmenge).
