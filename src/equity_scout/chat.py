"""Local chatbot over the dashboard data via Ollama.

No RAG, no vector DB: the dashboard's numbers are small and structured, so we just fold a compact
snapshot of the current state into the prompt and let a local model answer from it. Talks to a local
Ollama server (localhost:11434 by default); if it isn't reachable, the caller gets a clear, honest
error instead of a hang. The system prompt keeps it grounded: answer from the data, no advice, no
price forecasts — the same honesty guardrails as every other surface.
"""
from __future__ import annotations

import os

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
# How long Ollama holds the model in RAM after a call (~5 GB for qwen2.5:7b).
KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "24h")
MAX_ANSWER_TOKENS = 400
# A cold model needs ~90 s before the first token; the 2026-08-07 eval ran one question
# into a 120 s ceiling and reported it as "server unreachable", which sent debugging in
# entirely the wrong direction.
REQUEST_TIMEOUT_SECONDS = 240.0
# Ollama's runtime default is 4 096 tokens and it silently DROPS what does not fit — a
# four-stock comparison plus glossary clears that, and the part that would fall out is the
# system prompt with the guardrails. Set explicitly; qwen2.5:7b itself allows 32 768.
NUM_CTX = 8192

SYSTEM_PROMPT = (
    "Du bist der Assistent von equity-scout, einem lokalen Recherche-Tool (Paper-Trading, "
    "keine Anlageberatung). Regeln, ohne Ausnahme:\n"
    "1. Antworte NUR aus dem DATEN-Kontext unten. Steht etwas nicht darin, sage wörtlich, "
    "dass es nicht im Datenbestand ist — erfinde nichts, auch keine Ticker oder Gründe.\n"
    "2. Keine Empfehlungen, keine Ratschläge, keine Kursprognosen. Formulierungen wie "
    "'es wäre ratsam' sind verboten.\n"
    "3. Zahlen immer mit ihrer Quelle aus dem Kontext benennen (z.B. 'laut Watchlist', "
    "'laut Analysten-Konsens').\n"
    "4. Hausbegriffe bedeuten exakt das, was das GLOSSAR sagt — keine Lehrbuch-Definitionen.\n"
    "5. Werden mehrere Aktien genannt, stelle sie Kennzahl für Kennzahl gegenüber und "
    "benenne fehlende Werte. Kein Sieger, keine Rangliste, keine Kauf-Andeutung.\n"
    "Antworte knapp und auf Deutsch."
)

# Fixed answer for advice questions — served BEFORE the LLM (api.py), so the refusal can
# never be watered down by a 7B model's helpfulness.
REFUSAL_ANSWER = (
    "Das entscheide ich nicht für dich: equity-scout gibt keine Anlageberatung und sagt "
    "dir nie, ob du kaufen oder verkaufen sollst. Ich kann dir aber die Fakten zeigen — "
    "frag z.B. »Wie bewertet das Modell den Einstieg bei X?« oder »Was sagen die "
    "Analysten zu X?«."
)

# The house terms, defined ONCE — the measurement showed the model explaining
# "Einstiegszone" from its training data instead of our definition.
GLOSSARY_HOUSE = (
    "GLOSSAR:\n"
    "- Einstiegszone: Unterstützungs-Band aus den letzten Halte-Niveaus (Support-Levels) "
    "einer Aktie — eine ZEITPUNKT-Aussage unseres Modells, kein Kursziel.\n"
    "- Einstiegs-Score (0-100): wie attraktiv unser Modell den EinstiegsZEITPUNKT bewertet "
    "(<40 schwach, 40-70 neutral, ab 70 attraktiv). Kein Kursversprechen.\n"
    "- Potenzial: Abstand vom aktuellen Kurs zum Durchschnitts-Kursziel der Bank-Analysten "
    "(Meinung Dritter, ~12 Monate) — nicht unsere Rechnung.\n"
    "- Signal-Filter: lokal trainiertes ML-Modell, sortiert dieselben Signale nach (0-100).\n"
    "- Verfallen: Pitch wurde zurückgezogen, weil der Titel die Watchlist verlassen hat."
)

# Split from the house terms because every 1 000 prompt characters cost real seconds on
# CPU inference (measured 2026-08-07: 82 s to the first token on a dossier question). A
# depot question does not need the metric definitions.
GLOSSARY_METRICS = (
    "KENNZAHLEN (jede mit ihrer Grenze — eine gute Zahl ist kein Kaufgrund):\n"
    "- KGV (Kurs-Gewinn-Verhältnis): Kurs geteilt durch Jahresgewinn je Aktie. Niedrig "
    "heißt billig ODER dass der Markt fallende Gewinne erwartet. Negativ = Verlustjahr.\n"
    "- Kurs-Buchwert-Verhältnis: Kurs gegen bilanziellen Substanzwert. Bei Software fast "
    "immer hoch, bei Banken fast immer niedrig — nur innerhalb einer Branche vergleichbar.\n"
    "- Eigenkapitalrendite: Gewinn je eingesetztem Eigenkapital. Hoch kann auch heißen: "
    "viel Fremdkapital im Spiel.\n"
    "- Nettomarge: was vom Umsatz als Gewinn übrig bleibt.\n"
    "- 6-Monats-Rendite / Tagesschwankung: reine Kursstatistik, keine Aussage über morgen.\n"
    "- 52-Wochen-Hoch: höchster Kurs der letzten 12 Monate. Eine Marke, kein Kursziel.\n"
    "- F-Score (Piotroski, 0-9): wie viele Bilanz-Kriterien sich zum Vorjahr verbessert "
    "haben. Trend der Bilanz, keine Bewertung des Kurses.\n"
    "- Perzentil (0-100): Rang im Vergleich zu den anderen gescreenten Titeln derselben "
    "Branche — 87 heißt 'günstiger als 87 % der Vergleichsgruppe', kein Prozentwert."
)

GLOSSARY_FILINGS = (
    "MELDEWEGE (wer kauft, und wie man das erfährt):\n"
    "- Kongress-Meldung: US-Abgeordnete und Senatoren müssen eigene Wertpapiergeschäfte "
    "offenlegen (STOCK Act).\n"
    "- Meldeverzug: Tage zwischen Kauf und Offenlegung. Er ist oft groß (im Bestand bis "
    "über 800 Tage) — eine 'neue' Meldung kann ein uralter Kauf sein. Immer mitnennen.\n"
    "- Form 4: Meldung von Insidern (Vorstand, Aufsichtsrat, Großaktionäre) an die SEC, "
    "meist binnen 2 Tagen.\n"
    "- 13F: Quartalsbericht großer Fonds über ihre US-Aktienbestände, bis 45 Tage nach "
    "Quartalsende — zeigt Vergangenheit, nicht die aktuelle Position.\n"
    "- 8-K: Pflichtmitteilung eines Unternehmens über ein meldepflichtiges Ereignis.\n"
    "- Stimme: jemand wurde in einem Artikel zu dem Titel erwähnt. Presse, keine Meldung."
)

# The whole vocabulary, for callers that want everything (and for the tests that pin it).
GLOSSARY = "\n".join((GLOSSARY_HOUSE, GLOSSARY_METRICS, GLOSSARY_FILINGS))


def glossary_for(topics: list[str], *, has_dossier: bool) -> str:
    """Only the glossary sections this question can possibly need.

    House terms always (they appear in every dossier and depot line); metrics when a stock
    or a key figure is on the table; filing routes when people are.
    """
    parts = [GLOSSARY_HOUSE]
    if has_dossier or "kennzahlen" in topics:
        parts.append(GLOSSARY_METRICS)
    if "personen" in topics or has_dossier:
        parts.append(GLOSSARY_FILINGS)
    return "\n".join(parts)


class ChatError(Exception):
    """Raised when the local Ollama server can't be reached or the model isn't available."""


def _fmt_pct(x: float, *, signed: bool = False) -> str:
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def build_dashboard_context(
    *,
    strategies: list,
    ml: dict | None,
    research: dict | None,
    forward: list,
    screener: dict | None = None,
) -> str:
    """A compact, model-readable snapshot of the current dashboard numbers — including the concrete
    holdings so "what should I buy" questions can be answered: each strategy's current ETF allocation
    and the screener's top-ranked individual stocks per risk bucket."""
    lines: list[str] = []
    if strategies:
        lines.append("STRATEGIEN (Backtest nach Kosten, gegen 60/40; 'Allokation' = was die Strategie JETZT hält):")
        for s in strategies:
            m = s["metrics"]
            weights = s.get("current_weights") or {}
            alloc = (
                ", ".join(f"{t} {round(v * 100)}%" for t, v in sorted(weights.items(), key=lambda kv: -kv[1]))
                if weights
                else "—"
            )
            lines.append(
                f"- {s['name']}: Sharpe {m['sharpe']:.2f}, Rendite p.a. {_fmt_pct(m['cagr'])}, "
                f"Max. Verlust {_fmt_pct(m['max_drawdown'])} | Allokation: {alloc}"
            )
    if screener:
        lines.append(
            "\nAKTIEN-SCREENER (regelbasiert, Einzelaktien; Top-Picks je Risiko-Bucket, Composite-Score 0–100):"
        )
        for bucket, picks in screener.items():
            top = "; ".join(f"{p['ticker']} – {p['name']} ({p['region']}, Score {p['composite']})" for p in picks)
            lines.append(f"- {bucket}: {top}")
    if ml and ml.get("trained"):
        lines.append(
            f"\nML-META-MODELL (out-of-sample): Trefferquote {_fmt_pct(ml['oos_hit_rate'])}, "
            f"{ml['n_bets']} Signale, Ø Exposure {_fmt_pct(ml['avg_exposure'])}"
        )
    if research and research.get("available"):
        champ = research.get("champion")
        if champ:
            feats = ", ".join(champ["features"])
            lines.append(
                f"\nAUTO-RESEARCH: {research['n_trials']} Konfigurationen getestet. Champion: "
                f"{champ['model']} mit [{feats}], DSR {champ['dsr']:.2f}, Sharpe {champ['sharpe']:.2f}."
            )
        if research.get("pbo"):
            lines.append(
                f"PBO (Overfitting-Wahrscheinlichkeit): {_fmt_pct(research['pbo']['pbo'])} — "
                "hoch heißt, die Bestenliste ist eher Glück als Können."
            )
    if forward:
        lines.append("\nFORWARD (fortlaufend, live, nach Kosten):")
        for a in forward:
            lines.append(
                f"- {a['strategy_name']}: {_fmt_pct(a['total_return'], signed=True)} "
                f"(Benchmark {_fmt_pct(a['benchmark_return'], signed=True)}), {a['n_points']} Bewertung(en)"
            )
    return "\n".join(lines) if lines else "Keine Daten verfügbar."


def ask_ollama(
    question: str,
    context: str,
    *,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    import httpx

    payload = {
        "model": model,
        "stream": False,
        # Keep the model resident for a day: the 2026-08-07 measurement paid a 90 s cold
        # start on the first question. Costs RAM while idle, saves ~80 s per first answer.
        "keep_alive": KEEP_ALIVE,
        # A phone answer needs ~10 lines, not an essay; shorter generation = faster done.
        "options": {"num_predict": MAX_ANSWER_TOKENS, "num_ctx": NUM_CTX},
        "messages": [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nDATEN-Kontext:\n{context}"},
            {"role": "user", "content": question},
        ],
    }
    try:
        resp = httpx.post(f"{host}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ChatError(
            f"Ollama antwortet mit {exc.response.status_code}. Ist das Modell '{model}' geladen? "
            f"(`ollama pull {model}`)"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ChatError(
            f"Das Modell '{model}' hat nach {timeout:.0f}s noch nicht geantwortet "
            "(meist ein Kaltstart). Nächster Versuch ist deutlich schneller."
        ) from exc
    except Exception as exc:  # connection refused, DNS …
        raise ChatError(
            f"Ollama ist unter {host} nicht erreichbar. Läuft `ollama serve`? "
            "Modell wählbar über die Umgebungsvariable OLLAMA_MODEL."
        ) from exc

    content = resp.json().get("message", {}).get("content", "").strip()
    if not content:
        raise ChatError("Ollama hat eine leere Antwort geliefert.")
    return content


def stream_ollama(
    question: str,
    context: str,
    *,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
):
    """Yield answer chunks as Ollama produces them. Same guardrails as ask_ollama —
    only the transport differs. Raises ChatError on connection problems BEFORE the
    first chunk; mid-stream errors end the generator (the client shows what arrived).

    Perceived latency is the point: the measurement clocked 37-90 s to a full answer,
    which reads as broken on a phone. First tokens arrive in a few seconds.
    """
    import json as jsonlib

    import httpx

    payload = {
        "model": model,
        "stream": True,
        "keep_alive": KEEP_ALIVE,
        "options": {"num_predict": MAX_ANSWER_TOKENS, "num_ctx": NUM_CTX},
        "messages": [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nDATEN-Kontext:\n{context}"},
            {"role": "user", "content": question},
        ],
    }
    try:
        with httpx.stream("POST", f"{host}/api/chat", json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = jsonlib.loads(line).get("message", {}).get("content", "")
                if chunk:
                    yield chunk
    except httpx.HTTPStatusError as exc:
        raise ChatError(
            f"Ollama antwortet mit {exc.response.status_code}. Ist das Modell '{model}' geladen?"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ChatError(
            f"Das Modell '{model}' hat nach {timeout:.0f}s noch nicht geantwortet "
            "(meist ein Kaltstart)."
        ) from exc
    except ChatError:
        raise
    except Exception as exc:  # connection refused, DNS …
        raise ChatError(f"Ollama ist unter {host} nicht erreichbar.") from exc


def warm_model(*, model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST) -> bool:
    """Load the model into RAM with a one-token request. Best effort: returns False on any
    problem and never raises — a cold assistant is a slow assistant, not a broken service.

    Called once at service start (api.create_app(warm_model=True)) so Nico's first question
    of the day costs seconds instead of the measured 90-120 s cold start.
    """
    import httpx

    try:
        resp = httpx.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": {"num_predict": 1},
                "messages": [{"role": "user", "content": "ok"}],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except Exception:  # noqa: BLE001 - warming is optional by definition
        return False
    return True
