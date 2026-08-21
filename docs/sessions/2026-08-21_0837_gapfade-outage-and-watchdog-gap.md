# Session 2026-08-20 20:10 – 2026-08-21 08:37 — Gap-Fade-Ausfall + Watchdog-Lücke

## Kontext & Ziel

Einstieg von Nico: „wie siehts mit dem Autotrader aus? Pitch mal minimal tldr aktuellen
stand", danach „ja mach einfach weiter".

Der Pitch legte einen Befund offen, der bis dahin niemandem aufgefallen war: die
**gapfade-Lane hatte an allen vier Handelstagen seit ihrem Start (17.–20.08.) keine
einzige Order platziert** und trotzdem nie Alarm ausgelöst. Das wurde der Arbeitsauftrag.

Depot-Stand aus demselben Pitch, als Referenz für den nächsten Vergleich: Auto-Depot
+2,19 % vs SPY +2,72 %, swing +1,22 % vs SPY +3,62 %, crypto −6,91 % vs BTC +6,44 %
(der ganze Crypto-Verlust ist Gebühr: 548 € auf 68 Trades), session pausiert seit 13.08.,
ignition +2,11 % seit 19.08. **Kein Trader schlägt seine Benchmark.**

## Ergebnis

Vier Commits auf `autopilot/work`, Gate 2483 grün, ruff clean, **gepusht** (`a5da355`,
damit sind auch die 39 Altlast-Commits vom 11./20.08. draußen).

| Commit | Inhalt |
|---|---|
| `9525d1a` | `fix(gapfade)`: `us_symbols` — Alpaca nur noch nach US-Notierungen fragen |
| `3a50cef` | `style(tests)`: ruff E741 aus `test_mem_guard.py` (Altlast von `d746193`) |
| `16212a6` | `feat(watchdog)`: gapfade als Kadenz-Kette + Herzschlag |
| `a5da355` | `docs(autopilot)`: Befund und beide Fixes im `AUTOPILOT_LOG.md` |

Die vollständige Fehlerkette, die Messwerte und die Lehren stehen im
`AUTOPILOT_LOG.md`-Eintrag vom 2026-08-20 — hier nur das Nötigste zum Wiedereinstieg:
globale Watchlist trifft US-only-Broker, **ein** `0006.HK` lässt Alpacas
Multi-Symbol-Endpunkt die **ganze** Anfrage mit 400 beantworten, der Tagesmarker wurde
nie gesetzt, der 5-Minuten-Cron wiederholte das 36-mal pro Tag.

**Live verifiziert, nicht nur getestet:**
- Echte Watchlist gegen Alpaca: 43 getrackt → 24 US, **24 Kurse statt 400-Fehler**.
- Trockenlauf des vollen Signalpfads gegen eine **Kopie** der DB, Orders abgefangen:
  3 MOO wären platziert (OPHC, PTGX, ADAM), 3 Ablehnungen ins Nicht-Trade-Buch.
- **Laufzeit 4,3 s** gegen den 240-s-Deckel der Lane — der Timeout war nie die Ursache,
  obwohl er meine erste Hypothese war.
- Beide neuen Testgruppen **gegen den alten Code gegengeprüft** (Fix raus → rot, rein →
  grün); ein grüner Test, der den Bug nicht fängt, wäre hier wertlos gewesen.

Nächtliche Ketten liefen durch: nightly 02:30–02:47 `rc=0` (dritte Nacht in Folge),
Prefetch-Segment 1250/7499 ohne Fehler, WSL seit dem Neustart >20 h stabil bei 8/19 GB.

## Entscheidungen

- **Suffix-Filter statt `"." in ticker`** — die billigere Regel der SEC-Kollektoren
  (`form4`, `edgar_8k`) wirft auch US-Klassenaktien wie `BRK.B` weg, und ein still
  geschrumpftes Universum ist genau dieselbe Fehlerklasse, die gerade vier Tage kostete.
- **Punkt-Vorprüfung vor der Suffix-Prüfung** — `T` ist AT&T, `L` ist Loews: beide
  buchstabieren als ganzer Name einen Börsensuffix.
- **Filter vor dem Preis-Panel, nicht erst vor der Kursanfrage** — ein Kurs, den wir
  nicht bekommen können, ist ein Bar, den wir nicht laden müssen.
- **Watchdog als Kadenz-Kette, nicht auf Alters-SLA** — sonst hätte gapfade jedes
  Wochenende denselben Fehlalarm produziert wie die nightly-Kette am 10.08.
- **Herzschlag dort, wo der Tagesmarker gesetzt wird** — also bei jedem Lauf, der eine
  *Entscheidung erreicht* hat. Keine Order zu platzieren ist gesund, gar nicht erst
  dorthin zu kommen nicht.
- **Grenze gepinnt statt verschwiegen** — eine Kette, die nie geschlagen hat, wird nie
  alarmiert; der neue Eintrag hätte **genau diesen** Ausfall nicht gefangen.
- **Matrix-Hold-out bewusst nicht gestartet** — Einmalschuss laut eigenem Design,
  gehört Nico.
- **Fremde uncommittete Dateien nicht angetastet**: `scripts/run_train_entry.py`,
  `tests/test_run_train_entry.py`, `docs/research/2026-08-18-news-latency-decay.md`.

## Offene Fragen

- **Ein einzelnes delistetes US-Symbol tötet die Batch weiterhin.** Der Filter löst die
  Auslandsnotierungen, nicht den allgemeinen Fall: Alpaca antwortet auf *jedes*
  unbekannte Symbol mit 400 für die ganze Anfrage, und die Watchlist wird täglich aus
  ~7 500 Titeln neu gebaut (`prefetch.log` zeigt laufend Delistings). Bewusst nicht
  mitgefixt (Scope) — der naheliegende Weg wäre ein Fallback, der bei 400 einmal in
  Einzelanfragen zerlegt und das schuldige Symbol benennt.
- **Misst die Lane überhaupt, was sie messen soll?** Von den 24 US-Tickern sind viele
  Small Caps (OPHC, ADAM, CHMG, PKBK) mit dünnem Pre-Market — die Evidenzkette
  (`docs/research/2026-08-16-*`) stammt aus einem anderen Universum. Und die Watchlist
  wechselt täglich, während das Stop-Kriterium der Lane bei 60 geschlossenen Trades
  liegt: das Universum ist dann über die Messreihe hinweg nicht konstant.
- Die drei Ticker aus dem Trockenlauf sind **kein** Signal für heute — der Lauf nutzte
  Nachmittagskurse gegen den Vortagesschluss, nicht echte Pre-Market-Gaps.

## To-dos

### Nico

1. **Entscheiden, ob der Matrix-Hold-out 2023–2025 aufgeht.** Das ist der nächste große
   Schritt und laut deinem eigenen Design ein Einmalschuss mit vorher registrierter
   Hypothese. Ich habe angeboten, die Registrierung als Plan-Dokument vorzubereiten,
   ohne den Lauf zu starten — dazu fehlt dein Go.
2. **Heute ab 15:00 kurz draufschauen, ob die Lane wirklich feuert.** Erwartbar ist
   entweder „Gap-Fade: N MOO platziert" oder eine Liste verworfener Titel — beides ist
   gesund. Bleibt es still, ist der Fix nicht die ganze Geschichte.
3. **Der Rechner muss heute 15:30–22:00 laufen**, sonst handelt nichts (unverändert).
4. **Telegram-Bot-Token rotieren** — steht seit Wochen offen und liegt im Klartext in
   einem alten Log.

### Nächste Session (Agent)

- Verify des ersten echten gapfade-Laufs: `st_state`-Eintrag `gapfade_signal_day`,
  Heartbeat `heartbeat_gapfade` in `equity_scout.db`, Zeilen in `st_rejections`.
- `docs/sessions/` ist hier **nicht** gitignored — Session-Docs werden mitcommittet.
- Für neue Langläufer `scripts/mem_guard.sh` vorschalten, nicht nackt starten.
- Der Stunden-Wächter dieser Session (CronCreate) ist **session-only** und stirbt mit
  ihr; in einer neuen Autopilot-Session neu armen.

## Einstieg für die nächste Session

Branch `autopilot/work`, synchron mit `origin`, Gate 2483 grün. Es liegt **keine
angefangene Arbeit** herum — der gapfade-Strang ist geschlossen und wartet nur noch auf
seinen ersten echten Lauf heute 15:00 (Verify siehe Agent-To-dos).

Die offene Entscheidung ist Nicos Hold-out-Freigabe. Kommt sie, ist der erste Schritt
`writing-plans` für die Hypothesen-Registrierung vor Gate 4 — **nicht** direkt
`run_matrix_qualify.py` starten. Kommt sie nicht, ist der nächste sinnvolle Griff die
erste offene Frage oben (Einzelsymbol-Robustheit der Alpaca-Batch), weil sie dieselbe
Ausfallklasse betrifft, die diese Session gerade vier Tage rückwirkend aufgedeckt hat.
