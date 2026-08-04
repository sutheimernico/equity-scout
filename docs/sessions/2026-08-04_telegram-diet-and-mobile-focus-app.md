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
