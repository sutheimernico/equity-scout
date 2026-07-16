# Vision v8 — Klarheit auf einen Blick + Sektorrotation + Markt-Ampel (2026-07-16)

**Nico-Direktive (wörtlich zusammengefasst):** Die täglichen Nachrichten sind unübersichtlich,
unverständlich und nicht zielgerichtet. Vision: *"Ich schau da drauf und seh auf den ersten Blick:
aha, gute Aktie, aha, schlechte Aktie."* Kein Müll senden — nur guten Input. Oberflächliche
(wichtige) Informationen hervorheben, Detailtiefe zum Nachlesen dahinter, mit Absätzen arbeiten
(aktuell wirkt alles wie Klartext ohne Absätze). Außerdem: Sektorrotation einbauen, weitere
recherchierte Anlegerstrategien ergänzen, Konzept insgesamt "krasser" machen.

## Ist-Stand-Diagnose (Session-Recherche 2026-07-16)

1. **Formatierung:** `telegram_client.py` sendet bewusst plain text (kein `parse_mode`) — kein
   Fettdruck, keine visuelle Hierarchie. Emojis sind die einzige Struktur. Genau das erzeugt den
   "Klartext ohne Absätze"-Eindruck.
2. **Kein Urteil:** Die Caption zeigt `Score 59/100`, aber kein sofort lesbares gut/neutral/schlecht.
   Nico muss den Score selbst interpretieren.
3. **Müll-Quelle gefunden:** `run_notify.py --min-pitches 5` füllt auf 5 Pitches **auf**, auch wenn
   nur 1–2 über der Qualitätsschwelle liegen — mittelmäßige Kandidaten werden mitgesendet, nur um
   die Mindestzahl zu erreichen.
4. **Keine Detail-Nachfrage:** Der Receiver versteht nur buy/pass/later-Buttons. Die lange,
   erklärende Pitch-Version existiert (Inbox), ist aber per Telegram unerreichbar.
5. **Sektorrotation:** Existiert NICHT als Strategie. Nur sektor-relative Faktor-Rankings
   (Perzentile innerhalb des Sektors) und Sektor-Metadaten für Filter. CAPE-Sektorrotation wurde
   2026-06-24 mangels freier Daten verworfen — die Momentum-Variante über Sektor-ETFs ist mit
   yfinance aber sauber machbar und wurde damals nicht erwogen.

## Recherche-Synthese (Quellen im Recherche-Report, Session 2026-07-16)

Priorisierte Lücken (Machbarkeit mit yfinance/EDGAR × Mehrwert × Komplexität):

1. **Sektor-ETF-Momentum-Rotation** — 11 SPDR-Sektoren (XLK XLF XLV XLI XLE XLU XLB XLP XLY XLRE
   XLC), Top-3 nach Momentum, monatlich. Quantpedia-Backtest (1928–2009): ~13.9 % CAGR,
   MaxDD ~10 Punkte unter Buy&Hold. Technisch nah an vorhandenem `dual_momentum.py`. → **bauen**
2. **Markt-Regime-Ampel** — 4 robuste Signale: SPY vs. 200d-MA, VIX-Band, Marktbreite
   (% Universum > 200d-MA, aus bereits gecachten Kursen ableitbar), Zinskurve (^TNX−^IRX).
   Composite = Anzahl grüner Signale (0–4). Bewusst KEIN Regime-ML/HMM (Overengineering). → **bauen**
3. **52-Week-High-Momentum** — George/Hwang (2004): Nähe zum 52W-Hoch schlägt Rohmomentum,
   robust international. Triviale Ergänzung der Momentum-Familie. → **bauen**
4. **Piotroski F-Score** — 9 binäre Bilanz-Checks als Quality-TREND-Signal (bestehender
   Quality-Faktor misst nur Level). Primärquelle SEC EDGAR XBRL `companyfacts` (offizielle
   Zahlen, UA-Header genügt) statt der bekannt löchrigen yfinance-Fundamentals. → **bauen, zuletzt**

**Bewusst verworfen** (dokumentiert, nicht bauen): CANSLIM (institutionelle Ownership-Daten +
Chart-Pattern nicht frei/objektiv abbildbar), Business-Cycle-Sektorrotation (PMI/GDP nicht im
freien Quellen-Scope; ohne echte Phasenerkennung nur Pseudo-Heuristik), Net-Net/NCAV
(Micro-Cap-Datenqualität bei yfinance zu riskant, Universum aktuell winzig), RSI-2 Mean Reversion
(Swing-Trading-Taktik, passt nicht zur Anlage-Empfehlungslogik), Risk Parity (sinnvoll, aber
kein zweiter konkreter Bedarf — YAGNI).

## Ziel-Erlebnis (die Vision, gegen die jede Task geprüft wird)

Nico öffnet Telegram um 18:00 und sieht:

1. **Digest-Kopf:** Markt-Ampel (🟢🟡🔴) + die 3 stärksten Sektoren — ein Blick, Marktlage klar.
2. **Pro Pitch ein Chart-Foto**, Caption beginnt mit **fettem Ticker + Ampel-Urteil** und einem
   Ein-Satz-Warum. Danach kompakte Fakten in klar getrennten Absätzen.
3. **Detailtiefe auf Abruf:** aufklappbarer Block (`<blockquote expandable>`) bzw. 🔎-Details-Button
   liefert die lange, erklärende Version — Faktor-Breakdown, Einstiegsplan, Evidenz, Presse.
4. **Kein Müll:** Es kommen nur Pitches über der Qualitätsschwelle. Gibt es heute keine, sagt der
   Copilot das ehrlich in einer Zeile — statt mit Mittelmaß aufzufüllen.
5. Ampel-Urteile sind deterministisch aus Score + Risikosignalen abgeleitet und ehrlich gelabelt
   ("Einstiegs-Attraktivität laut Modell") — nie ein Kursversprechen. Disclaimer-Regeln unverändert.

## Leitplanken (unverändert aus LOOP.md/AUTOPILot.md)

Lokal & frei (yfinance/EDGAR/öffentliche Listen), Honesty-Guardrails auf jeder Surface, LLM
interpretiert und prognostiziert nie, Determinismus in Tests (FakeProvider/FakeAnalysis, kein
Netz), Gate = `uv run pytest -q` + `uv run ruff check .`, kleine Diffs, eine Task pro Iteration.

**Telegram-HTML-Vorsicht:** Live-Sendungen kann die Sandbox nicht testen (kein Netz). Der
HTML-Umbau braucht deshalb (a) einen Escaping-Helper mit Tests für alle dynamischen Inhalte
(Firmennamen mit `&`, `<` etc.), (b) defensiven Fallback: schlägt eine HTML-Sendung mit 400 fehl,
einmal als plain text ohne Tags retryen — eine kaputte Nachricht darf nie die tägliche Lieferung
verhindern. `<blockquote expandable>` in Foto-Captions gegen die Bot-API-Doku verifizieren;
falls nicht unterstützt: Detail-Block nur in Textnachrichten, Foto behält den 🔎-Button.
