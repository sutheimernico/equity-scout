# 2026-08-05 — Handy-Cockpit: Potenzial, Chart, KI-News + Autotrader-Tab

Nicos Zielbild, in seinen Worten: „Das Ziel der Handy App ist es, dass ich da einmal am Tag
draufschaue. Auf'n ersten Blick sehe, okay, was gibt's grade für interessante Aktien? […]
am besten auch den aktuellen einen Jahreschart […] und wenn ich dann reinklicke, dann sehe
ich so, was gute Einstiegspreis wäre, dann noch weitere Kennzahlen. Aber auch, was so
aktuelle News sind kurz von der KI zusammengefasst […] Ich will weg von diesen Telegram
Nachrichten hin zu, dass ich einmal auf mein Handy schaue."

Plus ein zweiter Tab: „wie es der Autotrader macht, also der Short Term und Long Term
Trader […] am besten einfach so aktuelles Depot, aber auch was für Trades gemacht wurde."

## Drei Entscheidungen (Nico, vor dem Plan)

1. **„Potenzial" ist Analysten-Konsens, klar gelabelt.** Kein selbst erfundenes Kursziel.
2. **News werden sichtbar gemacht, ändern aber die Rangfolge nicht.** Ein Score-Eingriff
   wäre nach Hausregel backtestpflichtig (eigenes Ledger, DSR-Hürde).
3. **Telegram behält einen Anstoß-Push pro Tag.** Die PWA kann selbst nicht pushen.

## Ein Befund gegen Nicos Annahme

Er ging davon aus, das News-System fließe schon in die Vorschläge ein („wir hatten da ja so
ein System mit den News"). Gemessen: `grep -n evidence src/equity_scout/radar.py
src/equity_scout/signals.py src/equity_scout/engine.py` findet **nichts**. News waren immer
nur Anzeige (VoicesPanel, `/api/stack`, Pitch-Text), nie Rangfolge. Das ist so geblieben.

## Messungen, die das Design bestimmt haben

| Frage | Messung | Konsequenz |
|---|---|---|
| LLM live im Request? | 27,2 s kalt / 5,6 s warm | Nein — nächtliche Erzeugung + SQLite-Cache |
| Analysten-Coverage? | 11/12 der Top-Titel haben ein Ziel | „Potenzial" tragfähig, fehlende Coverage zeigt „—" |
| Reicht eine Liste? | Rang 1 = **−7 %**, Rang 3 = **+69 %** | Nein — zwei benannte Sektionen |
| Besseres Modell? | `llama3.1:8b` 52,8 s statt 7,1 s **und** Prompt ignoriert | `qwen2.5:7b` bleibt |

Das Ranking-Ergebnis ist der Kern: `rank_entries` sortiert in-zone zuerst (unser Signal),
also stand ein negatives Potenzial oben. Nach Upside zu sortieren hätte die fremde Meinung
über das eigene Signal gestellt. Deshalb „Jetzt im Einstiegsbereich" (unser Signal) und
darunter „Höchstes Potenzial · laut Analysten, nicht unser Modell".

## Was gebaut wurde

**Backend.** `insights.py` (reine Prompts, LLM-Output-Bereinigung, Sparkline-Downsampling),
`insights_storage.py` (zwei Tabellen: `stock_insights` für Interpretationen ohne Verfall,
`price_series` für tagesaktuelle Fakten — getrennte Frische-Stempel, damit die UI beide
korrekt labeln kann), `scripts/run_insights.py` als nächtlicher Schritt in
`daily_copilot.sh` nach `radar`, und `/api/briefs` liefert beide Caches mit (Default-Limit
5 → 12). `scripts/install_ollama_service.sh` hält Ollama als systemd-User-Service.

**Frontend.** Potenzial als größte Zahl mit Attribution direkt darunter, zwei Sektionen
(`stocklist.ts`), Inline-SVG-Sparkline aus eigenen Kursen (`sparkline.ts` +
`MiniYearChart.tsx`), KI-Texte plus Original-Schlagzeilen im Detail, und `PhoneDepot.tsx`
als kompakter Autotrader-Tab unter 720 px.

## Drei Fehler, die erst das Ausführen zeigte

1. **Die News beschrieben fremde Firmen.** `clean_company_query` verkürzte „Yamato Holdings
   Co., Ltd." (9064.T) auf „Yamato" — die Zusammenfassung handelte dann von TSE:1967,
   TSE:5444 und TSE:8127, drei anderen Unternehmen. Gleichzeitig blieben die
   Börsen-Beschreibungen der Nasdaq-Namen („Air T, Inc. - Common Stock") in der Suchphrase
   und **4 von 12 Titeln fanden gar keine Schlagzeilen**. Zwei entgegengesetzte Symptome,
   ein Defekt. Neue Regel: Rechtsformen (Inc/Corp/Ltd/NV/SE…) fallen immer,
   „Holdings"/„Group" nur, wenn danach ≥ 2 Wörter bleiben — bei asiatischen Konzernen ist
   „Holdings" namenstragend, eine Rechtsform nie. Danach **12/12 mit Schlagzeilen**, und
   Yamato trifft TSE:9064. Ein bestehender Test kodierte den Defekt (`"X Holdings Inc."` →
   `"X"`) und wurde mit Begründung umgeschrieben.
2. **NaN hat `/api/briefs` komplett auf 500 gesetzt.** yfinance liefert für einen Tag ohne
   Close NaN — und zwar als **letzten** Punkt des Jahres bei 9064.T und 9022.T. Die eigene
   Zusicherung „erster und letzter Punkt sind echt" (`sampled[-1] = closes[-1]`) hat den NaN
   damit garantiert mitgeschleppt. `json.dumps` schreibt ihn als das ungültige Literal `NaN`,
   `json.loads` liest ihn zurück, und erst FastAPIs strikter Encoder scheiterte — ein
   schlechter Ticker riss alle Karten mit. Jetzt werden nicht-finite Werte vor dem Sampling
   verworfen (ein fehlender Tag ist kein Wert), und `save_price_series` schreibt mit
   `allow_nan=False`, damit so etwas nie mehr still in die DB kommt.
3. **Die Handelszeilen waren am Handy unlesbar.** Die Bücher speichern exakte Bruchteile,
   also stand dort „BUSE 32.19510896380651" und „BTC 0.038163611924095855". Das drückte den
   Kurs aus der Zeile, und `.view *`s `overflow-wrap: anywhere` brach mitten im Token —
   „sell" wurde zu „sel l", „BTC" zu „BT C". Stückzahlen jetzt mit vier signifikanten
   Stellen, und Tag/Seite/Ticker stehen zusammen mit `.num` auf der Umbruch-Ausnahmeliste.

## Verifikation

- **Gate**: 1314 Python-Tests grün, `ruff check .` clean, 46 vitest-Tests grün,
  `tsc --noEmit` exit 0, Build ok, `dist/sw.js` + Manifest ausgeliefert.
- **Screenshots auf 390 × 844** (Chromium aus dem Playwright-Cache,
  `--force-prefers-reduced-motion`): beide Tabs ohne horizontales Scrollen, Sektionen in
  der richtigen Reihenfolge, Sortierung +69/+64/+38/+32, Detail mit Chart, Kennzahlen und
  KI-Texten. Desktop bei 1440 px unverändert (Sidebar + sieben Tabs).
- **Farbe gemessen statt geschätzt**: Yamatos „−7 %" schien im herunterskalierten
  Screenshot grün — die Pixelmessung ergab `(245,178,62)` = `#F5B23E` = `--warning`.
  Kein Fehler, aber der Anschein war Grund genug zum Nachmessen.
- **Live über Tailscale**: 401 ohne Token, 200 mit Token, `/api/briefs` liefert 12 Briefs,
  **12 mit KI-Text und 12 mit Chart**.

## Abweichungen vom Plan

- **Kein `sys.path`-Anker in `run_insights.py`.** Der Plan verlangte ihn nach dem Muster von
  `run_notify.py`. Geprüft: dieser Tanz ist nur für `from scripts.<sibling> import …` nötig;
  `equity_scout` ist editable installiert, also lösen die Imports von überall auf. Der Anker
  wäre toter Code mit irreführendem Kommentar gewesen.
- **CSS-Tokens hießen anders als im Plan.** Real sind `--positive`, `--warning`,
  `--bg-surface` (nicht `--good`/`--warn`/`--surface`).
- **Zwei zusätzliche Fixes** (siehe oben: News-Query, NaN) waren im Plan nicht vorgesehen,
  betreffen aber die Korrektheit genau der Fläche, die gebaut wurde.
- **`clean_company_query` wurde geändert**, also auch der Telegram-Pitch-Pfad — dort ist es
  dieselbe Verbesserung. `test_pitch`, `test_notify`, `test_digest` bleiben grün.
- **Eine leere `data/equity_scout.db`** hatte ein Test-Aufruf von mir versehentlich angelegt
  (die echte DB liegt im Repo-Root); leer bestätigt und gelöscht.

## Offen / Needs Nico

1. **Walk-Through am Handy**: `<DASH_URL>/?view=today` öffnen, eine Karte antippen — Chart,
   Kennzahlen und KI-Text müssen erscheinen; dann `?view=depots` prüfen (Allokation,
   Toggle „+ N kleine Rebalances", Lanes).
2. **Die deutschen KI-Texte sind holprig** („Yamato Holdings kämpft mit Gewinnsträften").
   Das ist die Qualitätsgrenze eines lokalen 7B-Modells; `llama3.1:8b` war gemessen
   schlechter und 7× langsamer. Wenn das störend ist, wären die nächsten Optionen ein
   größeres lokales Modell (RAM-Frage) oder eine bewusste Entscheidung für eine bezahlte
   API — letzteres verletzt die private Kostengrenze und braucht deshalb Nicos Wort.
3. **Ollama läuft jetzt dauerhaft** als User-Service. Wenn das RAM störend ist:
   `systemctl --user disable --now ollama` — dann bleiben die KI-Felder leer, alles andere
   funktioniert weiter.
4. **Kein Modell-Kursziel**, solange kein `entry_tb`-Champion registriert ist. Damit ist
   „Potenzial" ausschließlich Analysten-Konsens.
5. Aus früheren Sessions offen: Telegram-Token-Rotation, `autopilot/work` → `main`.

### Vorbefund, NICHT gefixt (außerhalb des Auftrags)

Die Desktop-Panels (`KurzfristArenaPanel`, `AutoDepotPanel`) zeigen Stückzahlen mit
`num(qty, 4)`, also z. B. `32.1951` — am Desktop lesbar, aber dieselbe Rohdaten-Optik.
Die Handy-Ansicht nutzt jetzt vier signifikante Stellen; eine Vereinheitlichung wäre eine
eigene kleine Runde.
