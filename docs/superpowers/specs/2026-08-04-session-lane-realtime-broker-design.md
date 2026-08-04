# Design: Session-Lane auf Echtzeitdaten und Broker-Ausführung

Datum: 2026-08-04
Status: Entwurf, wartet auf Nicos Approve
Betrifft: `shortterm.db` Lane `session`, `src/equity_scout/st_session.py`,
`src/equity_scout/intraday_bars.py`, `scripts/run_shortterm.py`

## Warum

Die Session-Lane hat zwischen dem 2026-07-20 und dem 2026-07-24 zehn Trades geschlossen und
dabei 179,95 verloren. Der Verlust ist zu 98 % kein Strategieergebnis:

| Exit-Art | Trades | PnL |
|---|---|---|
| Strategie (Ziel / Stop / Session-Ende) | 5 | −3,25 |
| `Altbestand (zwangsflat)` nach Ausfall | 5 | −176,70 |

Ein einzelner TSLA-Trade steht für 155,24 davon. Ursache war ein Ausfall: zwischen dem
2026-07-21 20:00 und dem 2026-07-23 13:00 lief kein Durchgang, obwohl fünf Positionen offen
waren. Weder der In-Session-Force-Flat noch `_session_overnight_sweep` feuerte. Der
Schutzmechanismus `_flatten_stale_positions` (P0 aus dem Review 2026-07-20) hat korrekt
gegriffen und die Altbestände beim ersten bekennbaren Preis geschlossen — er ist nicht der
Fehler, sondern das Netz, das Schlimmeres verhindert hat.

Dazu kommt ein zweiter, schwerwiegenderer Befund. Die Lane bucht Fills zu Preisen, die zum
Entscheidungszeitpunkt nicht mehr verfügbar waren:

```
10:00 ET      Opening Range steht (2 Bars)
10:00–10:15   Bar schließt über OR-High  →  Signal
10:35 ET      Bar wird "settled" (Ende + SETTLE_MINUTES) — hier fällt die Entscheidung
              Fill laut st_session.py:99 = Open des nächsten Bars = Preis um 10:15
```

Das ist **kein Look-Ahead-Bias** — beide Bars waren beobachtet. Es ist ein
**Executability-Bias**: um 10:35 ist der 10:15-Open nicht mehr handelbar. Weil
Breakout-Momentum im Schnitt weiterläuft, wirkt der Fehler systematisch zugunsten der
Strategie. Dieselbe Verzerrung trifft die Exits: `st_session.py:84` nimmt an, dass ein Stop
*während* des Bars auslöst, was eine im Markt liegende Order voraussetzt. Es liegt aber
keine — es wird alle 15 Minuten auf 20 Minuten alte Daten gepollt.

Der bestehende Track ist damit strukturell zu gut, und jede Optimierung darauf würde gegen
einen Fill optimieren, den es nie gab.

## Ansatz

Statt die Verzerrung genauer zu modellieren, wird ihre Ursache entfernt: Echtzeit-Kursdaten
für die Signale, echte Broker-Orders für die Ausführung, im Markt liegende Stops für die
Exits.

**Alpaca Paper** deckt alle drei ab, kostenlos und ohne KYC (Paper-Only-Konto):

| | Alpaca Paper | T212 Demo |
|---|---|---|
| Echtzeit-Kursdaten | ja, IEX, Basic-Plan gratis | keine (API hat keine Kursdaten) |
| Order-Platzierung | ja | unverifiziert |
| Liegende Stop-Orders | ja | unverifiziert |
| KYC | nein | ja |
| SPY/QQQ handelbar | ja (Paper, kein PRIIPs) | nein |
| Fills | simuliert gegen Echtzeit-Quotes | im Demo ebenfalls simuliert |

Die letzte Zeile ist der Grund gegen T212 in dieser Stufe: dessen Alleinstellung — echte
Ausführung — existiert erst im Live-Konto mit echtem Geld. Im Demo-Modus bietet T212 nichts,
was Alpaca nicht auch bietet, kostet aber KYC, eine Beta-API und zwei Ticker.

T212 bleibt der Kandidat für einen späteren Echtgeld-Schritt, nicht für diesen.

### Vorbedingung: Verifikation

`scripts/verify_alpaca_paper.py` prüft die vier Annahmen, auf denen dieses Design steht:
Credentials, Bar-Aktualität, Market-Order, liegende Stop-Order. Der Bar-Aktualitätstest ist
der entscheidende und **nur bei offenem US-Markt aussagekräftig** (15:30–22:00 MESZ). Ergibt
er ein Bar-Alter deutlich über einem Intervall, ist die Prämisse falsch und dieses Design
muss verworfen werden.

Keine Zeile Umbau vor einem grünen Verifikationslauf.

## Architektur

### Grundprinzip: der Broker ist die Wahrheit

Bisher ist `shortterm.db` das Buch. Künftig hält das Broker-Konto den Positionsstand, und
die lokale DB ist Journal und Spiegel. Nach jedem Durchgang werden die Broker-Positionen
abgerufen und gegen die DB abgeglichen; eine Divergenz ist ein lautes Fehlerbild, kein
stiller Merge. Ohne diese Regel gibt es zwei Bücher, die auseinanderlaufen — und bei einem
Ausfall ist genau das der wahrscheinliche Zustand.

### Neue Module

**`src/equity_scout/alpaca_data.py`** — Bar-Abruf über
`https://data.alpaca.markets/v2/stocks/bars` mit `feed=iex`. Liefert denselben
DataFrame-Vertrag wie `intraday_bars.fetch_bars` (tz-aware Index auf America/New_York,
Spalten `open/high/low/close/volume`), damit `st_session.decide()` unverändert bleibt.
Netzwerkcode isoliert und in Tests faked — dieselbe Struktur wie das bestehende Modul.

Das Settle-Gate entfällt, aber nicht die Abgeschlossenheitsprüfung: ein Bar ist erst nutzbar,
wenn sein Intervall abgelaufen ist. Aus 20 Minuten Sicherheitsmarge wird damit die reine
Bar-Grenze.

**`src/equity_scout/alpaca_broker.py`** — Order-Platzierung, Positions- und
Order-Abfrage, Storno. Entries gehen als **Bracket-Order** raus (`order_class: "bracket"`):
Entry, Stop-Loss und Take-Profit in einem Auftrag, mit derselben Range-Geometrie wie heute
(Stop = Entry − 0,5 × Range, Target = Entry + 1 × Range). Die Position ist damit ab
Ausführung im Markt geschützt, ohne dass die Maschine pollt.

### Geänderte Module

**`scripts/run_shortterm.py`**, Session-Pfad: Signalermittlung bleibt `st_session.decide()`.
Statt Fills lokal zu buchen, werden Orders platziert; die Fills kommen aus der
Broker-Antwort zurück ins Journal. Reihenfolge pro Durchgang:

1. Broker-Positionen und offene Orders abrufen
2. Gegen DB abgleichen, Divergenz melden
3. Altbestände aus früheren Tagen schließen (`_flatten_stale_positions`, unverändert)
4. Bars holen, `decide()` aufrufen
5. Entries als Bracket-Order platzieren, sofern das Staleness-Gate offen ist
6. Journal und Bewertung schreiben

**`st_session.py`** behält seine Entscheidungslogik unverändert — Opening Range, Ausbruch,
Stop- und Target-Geometrie. Was sich ändert, ist die Bedeutung des Preisfelds in
`SessionAction`: bisher ist es der gebuchte Fill-Preis, künftig der **erwartete** Preis, gegen
den der echte Broker-Fill in der Reconciliation gemessen wird. Der Executability-Bias
verschwindet also, weil der Fill vom Broker kommt, nicht weil die Signallogik anders rechnet.
Das erhält die Vergleichbarkeit zum bestehenden Track.

### Ausführungsgarantie

Drei Ebenen, absteigend nach Verlässlichkeit:

1. **Liegende Bracket-Orders** — greifen ohne die Maschine. Deckt Stop und Target ab.
2. **15-Minuten-Takt** im US-Marktfenster statt stündlich (`install_windows_task.sh`).
   Bar-Takt und Lauf-Takt müssen übereinstimmen, sonst werden Bars systematisch verpasst.
3. **Staleness-Gate vor dem Entry** — liegt der letzte erfolgreiche Durchgang mehr als
   einen Bar zurück, öffnet dieser Durchgang keine Position und managt nur Bestehendes.
   Begründung: wer nicht belegen kann, in 15 Minuten wieder da zu sein, soll keine neue
   Position eröffnen.

`_session_overnight_sweep` und `_flatten_stale_positions` bleiben als letztes Netz.

**Bekannte Grenze, nicht wegdiskutiert:** Bracket-Orders mit Tagesgültigkeit schützen
innerhalb der Session, stellen die Lane aber nicht am Tagesende flat. Fällt der Abend-Sweep
aus, schließt die Position erst am nächsten Öffnen. Das Risiko sinkt von „ungeschützte
Position über Tage" auf „verspäteter Flat" — es verschwindet nicht.

### Reconciliation

Eine Tabelle hält pro Fill den erwarteten Preis (aus dem Signal-Bar) und den tatsächlichen
Broker-Fill. Die Differenz ist der erste belastbare Messwert für Slippage in diesem Projekt
und die Grundlage, um das Kostenmodell des Auto-Depots zu prüfen — dort greift bei liquiden
ETFs bisher immer der 10-bps-Boden, der Corwin-Schultz-Schätzer kommt nie darüber.

## Tests

- `alpaca_data`: DataFrame-Vertrag, tz-Behandlung, Abgeschlossenheitsprüfung, Fehlerpfade
  bei kaputtem Feed — gegen gefakte Responses, wie `fetch_bars` heute.
- `alpaca_broker`: Bracket-Payload-Aufbau, Fehler- und Teilausführungspfade, Storno.
- Staleness-Gate: kein Entry bei Lücke, Exits weiterhin erlaubt.
- Reconciliation: Divergenz-Erkennung zwischen Broker- und DB-Stand.
- Idempotenz: zweimal derselbe Durchgang platziert keine zweite Order.

## Nicht im Scope

- T212-Anbindung (Kandidat für einen späteren Echtgeld-Schritt)
- Mean-Reversion als zweiter Arm — die Begründung dafür war der Delay; mit Echtzeitdaten
  ist ORB legitim. Erst messen, dann erweitern.
- WebSocket-Streaming: REST-Polling genügt für 15-Minuten-Bars
- Short-Seite unter OR-Low
- Größeres Ticker-Universum
- Echtgeld

## Erforderliche Entscheidung von Nico

`LOOP.md` verbietet aktuell „no real-money trading or order routing — ever". Alpaca Paper ist
kein Echtgeld, aber es ist Order-Routing. Vorgeschlagene Neufassung: Order-Routing an ein
Paper-Konto erlaubt, Echtgeld-Handel weiterhin ausgeschlossen. Die autonome Loop ändert diese
Zeile nie selbst.

## Was zu erwarten ist

Der Track wird schlechter aussehen als der bestehende. Der aktuelle Verlauf beruht auf Fills
zu Preisen, die nicht handelbar waren; echte Fills nehmen diesen Vorteil weg. Der Gewinn ist
ein Track, auf den später Kapital gesetzt werden kann, plus die erste echte Slippage-Messung
im Projekt.

Fünf Strategie-Trades sind keine Stichprobe. Die Strategie ist nach diesem Umbau nicht
bewiesen — sie ist erstmals ehrlich messbar.
