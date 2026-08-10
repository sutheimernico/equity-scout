# Server mieten: was es kostet und was es bringt (2026-08-11)

Nicos Frage: „wir können gerne einen Server mieten, aber bitte einmal aufarbeiten, was mich da
so kosten würde. Und ich weiß nicht, ob's sinnig ist … irgendwo in Frankfurt oder New York
direkt an der Börse einen Server zu nehmen, weil damit man einen möglichst geringen Ping hat."

## Kurzantwort

**Ein Server: ja, ~5 €/Monat, aber aus einem anderen Grund als Ping.** Der Ping ist bei diesem
System messbar irrelevant; die Verfügbarkeit ist das echte Problem. **Colocation an der Börse:
nein** — für Retail nicht verfügbar und bei diesem Zeitraster wirkungslos.

## Warum Ping hier nicht das Problem ist — gemessen, nicht geschätzt

| Größe | Messwert (2026-08-11, dieser Laptop) |
|---|---|
| Ping zu `paper-api.alpaca.markets` | **110 ms** (min 108 / max 112) |
| Kompletter HTTPS-Roundtrip inkl. TLS-Handshake | **~347 ms** (DNS 7 ms, Connect 118 ms, TLS 237 ms) |
| Gemessene Fill-Latenz der Session-Lane (2026-08-07) | **~5.000 ms** |
| Entscheidungsraster der Lane | **60.000 ms** (1-Minuten-Bars, minütlicher Cron) |
| Gemessene Slippage (34 Executions) | **1–3 bps** |

Die Rechnung, die die Frage beantwortet: Ein Server in **New York** würde den Ping von 110 ms
auf ~5–15 ms senken, also **~100 ms sparen**. Das sind

- **2 %** der gemessenen Fill-Latenz von 5 s,
- **0,17 %** des 60-Sekunden-Entscheidungsrasters.

Ein Server in **Frankfurt** spart gegenüber dem Heimanschluss praktisch nichts, weil Alpaca in
den USA sitzt — die Distanz bleibt dieselbe. Frankfurt wäre nur bei einem europäischen Broker
sinnvoll.

Und die 5 s Fill-Latenz sind ohnehin **nicht Netzwerk**: davon gehen ~2,4 s allein auf die
eigene Poll-Schleife (`FILL_POLL_ATTEMPTS 6 × FILL_POLL_SECONDS 0,4`), der Rest auf
Alpaca-seitige Verarbeitung. Selbst eine perfekte Leitung ändert daran nichts.

**Kernpunkt:** Der Diagnose-Befund vom 2026-08-10 bleibt gültig — der Engpass ist Edge und
Kosten, nicht Geschwindigkeit. Bei 1–3 bps Slippage ist die Ausführung nicht das Problem.

## Warum Colocation ausfällt

1. **Nicht verfügbar.** Börsen-Colocation braucht Direct Market Access über einen
   Prime-Broker. Alpaca ist eine Retail-REST-API und bietet das nicht an; der Weg zur Börse
   führt immer über Alpacas eigene Infrastruktur, egal wo der eigene Rechner steht.
2. **Kostenordnung.** Colocation-Fläche gilt als „cost prohibitive and labor intensive", mit
   langen Vertragslaufzeiten — vier- bis fünfstellig pro Monat, nicht zweistellig.
3. **Wirkungslos für diese Strategien.** ORB auf 1-Minuten-Bars, Swing über Tage, Donchian auf
   Tagesbars. Mikrosekunden entscheiden bei keiner davon.

Colocation lohnt bei Market Making und Latenz-Arbitrage, wo der Vorsprung in Mikrosekunden das
Geschäftsmodell IST. Das ist ein anderes Geschäft als dieses.

## Was ein Server wirklich löst: Verfügbarkeit

Das ist das teure Problem, und es ist heute zweimal aufgetreten:

- **2026-08-10, 19:00:** Die Daily-Kette starb, weil `insights` unter CPU-Last kroch und der
  Windows Task Scheduler die Kette am 1-Stunden-Limit abbrach. `evidence`, `fscore`, die
  Resolver **und die Telegram-Zustellung** fielen aus. Stumm.
- **Struktureller Rest:** Windows erlaubt Wake-Timer nur am Netzstrom. Im Akkubetrieb fällt der
  Nachtlauf aus — und damit der Depot-Advance und die Next-Open-Fills.
- Dazu die Konkurrenz um dieselbe Maschine: eine parallele Session mit 5 `scan.py`-Prozessen
  trieb die Load auf 16 und machte Ollama-Antworten unbrauchbar langsam.

Ein Server, der nichts anderes tut, hat keine dieser Fehlerquellen. **Das** rechtfertigt die
Ausgabe, nicht der Ping.

## Kostenaufstellung (recherchiert 2026-08-11)

| Stufe | Was | Kosten/Monat | Löst |
|---|---|---|---|
| **1 — empfohlen** | Kleiner VPS in DE (z. B. Hetzner CX22: 2 vCPU, 4 GB, 40 GB) | **~4,50–5,50 €** | Ketten laufen 24/7, unabhängig von Laptop, Akku und Fremdlast |
| 2 — optional | Derselbe VPS, aber US-Region (näher an Alpaca) | ~5–12 € | Zusätzlich ~100 ms Ping. Wirkung: siehe oben, marginal |
| 3 — nur für den Assistenten | VPS mit 16 GB RAM für Ollama (ohne GPU) | ~15–25 € | Assistent läuft ohne den Laptop — aber CPU-Inferenz bleibt langsam |
| 4 — nur wenn der Assistent zentral wird | GPU-Instanz | 50–200+ € | Schnelle LLM-Antworten. Deutlich teurer als der Rest zusammen |

**Wichtige Einschränkung zu Stufe 1:** 4 GB RAM tragen die Ketten (pandas/sklearn/yfinance),
**nicht** Ollama — qwen2.5:7b braucht allein ~5 GB. Der Assistent bliebe auf dem Laptop, was
in Ordnung ist: er ist interaktiv und braucht kein 24/7.

Hetzner hat 2026 zweimal die Preise erhöht (April und Juni), Stand August 2026 sind die oben
genannten Werte aktuell. Alternativen in derselben Klasse: Netcup, Contabo, Hostinger; DigitalOcean/Vultr/Linode liegen typisch höher.

## Was zu bedenken ist, bevor umgezogen wird

- **Alpaca-Keys wandern auf einen fremden Rechner.** Heute liegen sie in einer lokalen `.env`
  auf einer Maschine, die Nico physisch besitzt. Ein VPS ist Paper-only, also ist der Schaden
  begrenzt — aber die Keys sollten vor dem Umzug rotiert werden und der Server SSH-key-only
  sein.
- **Die Windows-Task-Schicht wird überflüssig** und sollte dann abgebaut werden, sonst laufen
  zwei Scheduler auf dieselben DBs (der Lock fängt es ab, aber zwei Wahrheiten sind eine zu
  viel).
- **Die DBs müssen mitwandern oder neu starten.** Der Depot-Track läuft seit 2026-07-16; ein
  Umzug darf ihn nicht abschneiden. Sauber: DBs kopieren, Laptop-Crons abschalten, ein Lauf
  zur Kontrolle, dann erst produktiv.
- **Datenlage bleibt gleich.** yfinance/EDGAR/Kraken sind von jedem Server erreichbar; der
  Umzug bringt keine besseren Daten, nur mehr Betriebszeit.

## Empfehlung

**Stufe 1 buchen, wenn dich die verpassten Läufe störten — sonst nicht.** Es ist die einzige
Stufe mit einem messbaren Problem dahinter. Stufe 2 nur mitnehmen, wenn der Preis gleich ist
(US-Region kostet oft dasselbe); als eigenständiger Grund trägt der Ping nicht. Stufen 3 und 4
erst, wenn der Assistent für dich wirklich zentral wird — heute ist er Komfort, nicht Ertrag.

**Nichts davon ist gebucht.** Kosten sind eine Nico-Entscheidung, die der Autopilot nie selbst
trifft.

## Quellen

- [Hetzner Cloud VPS Pricing Calculator (Aug 2026)](https://costgoat.com/pricing/hetzner)
- [Hetzner Price Adjustment 15 June 2026](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)
- [Hetzner Cloud Review 2026: Benchmarks, Pricing, Trade-offs](https://betterstack.com/community/guides/web-servers/hetzner-cloud-review/)
- [Hetzner cloud server price increases in 2026](https://northflank.com/blog/hetzner-cloud-server-price-increases)
- [Best Broker APIs for Algorithmic Trading in 2026](https://www.tradealgo.com/trading-guides/tools/best-broker-apis-for-algorithmic-trading-in-2026)
- [Rethinking the low-latency trade value proposition (AWS Local Zones)](https://aws.amazon.com/blogs/industries/rethinking-the-low-latency-trade-value-proposition-using-aws-local-zones/)
- Eigene Messungen: Ping/HTTPS-Roundtrip zu Alpaca 2026-08-11; Fill-Latenz und Slippage aus
  `st_executions` (2026-08-06/07); Kettenausfall aus `copilot.log` (2026-08-10).
