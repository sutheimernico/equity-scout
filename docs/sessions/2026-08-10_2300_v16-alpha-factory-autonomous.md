# Session 2026-08-10 ~21:00 → 23:00 — v16 „Alpha-Fabrik", autonom

## Kontext & Ziel

Nico: „Meine Vision ist es, erreicht zu werden … bewerte die bisherige Applikation von 1 bis 10
und schau, was bis zu einer 10 fehlt … probiere die dann alle einzubauen." Dann: „Ich will reich
werden und du sollst alles dafür tun … ich will nichts dämpfendes hören. Mach einfach." Und:
„Mach das in einer Loop zuende, ich bin jetzt weg, dass heißt bring das alleine zuende."

Also: bewerten, Lücken finden, bauen — autonom, ohne Rückfragen.

## Die Bewertung, die den Auftrag geschärft hat

| Achse | Note | Belege |
|---|---|---|
| Maschine/Engineering | **8/10** | 140 Module, 24k Zeilen, 1883 Tests, 31 Endpoints, 12 Strategien, 16 Evidenzquellen, echter Paper-Broker, gemessene Slippage, Watchdog, Handy-Cockpit |
| Geldverdienen | **2/10** | Jedes Buch hinter Benchmark: Depot +0,9 % vs SPY +3,3 %, Session −2,4 %, Swing +0,2 %, Crypto −6,1 %, kein ML-Champion |
| Gesamt | **5/10** | Infrastruktur Oberklasse, Ertrag nicht |

**Die Lücke war nicht die Oberfläche.** Alle 12 Strategien kamen aus EINER Familie
(Momentum/Allokation über ETFs) — die Maschine probierte zu wenige verschiedene Ideen, um
einen Gewinner zu finden. Deshalb ging Welle 1 in die Breite des Suchraums, nicht in die
Optik.

## Welle 1 — vier neue Strategiefamilien (`1aacab3`, `7aaa968`)

Jede entscheidet auf anderer Grundlage, damit ihre Fehler unkorreliert sind:
Low-Vol (nach Risiko allein) · Cross-Sectional Momentum (12-1 mit Skip-Month) ·
Mean-Reversion (kauft, was die anderen verkaufen) · Risk Parity (keine Auswahl).
22 Tests. Jede verweigert einen stale Feed statt einen wiederholten Preis als risikolos zu
ranken — die Fehlerklasse, die ein ganzes Buch an eine kaputte Serie geben würde.

**Backtest über das echte ETF-Panel (2.045 Tage, 10 bps):**

| Strategie | CAGR | Sharpe | MaxDD | Turnover |
|---|---|---|---|---|
| **Cross-Sectional Momentum** | **15,3 %** | **1,00** | **−25,4 %** | 6,2× |
| SPY buy & hold | 15,3 % | 0,84 | −33,7 % | 0× |
| Risk Parity | 6,4 % | 0,78 | −19,8 % | 1,2× |
| Low-Vol | 3,7 % | 0,61 | −16,2 % | 3,3× |
| Mean-Reversion | 2,7 % | 0,31 | −27,6 % | 16,0× |

Einer von vier trägt: Cross-Sectional Momentum matcht SPY bei 8 Punkten weniger Drawdown.
Low-Vol enttäuscht messbar (konsistent mit dem Verblassen der Anomalie seit ~2018), und
Mean-Reversion scheitert genau so, wie ihr eigener Docstring es vorhergesagt hat.

**Alle vier haben ihren ersten Forward-Advance gemacht** — ab jetzt zählt der echte Track,
nicht der Backtest.

**Suchraum 43 → 82**, damit der Nightly meine Literatur-Startwerte selbst nachprüft. Befund
gegen die Literatur: **`skip_months=0` gewinnt** auf Index-ETFs — die Kurzfrist-Umkehr ist ein
Einzeltitel-Effekt, den ein ETF wegdiversifiziert. Genau deshalb war der Parameter eine Frage
im Grid und keine gesetzte Antwort.

## Welle 2 — Kapitaleffizienz (`f685a0b`)

**Defekt 1: Der Concentration-Cap parkte 24 % des Depots in Cash.** Die Sleeves wollten 83,9 %
Brutto; SPY aggregierte per Look-Through auf 29,1 %, VEU auf 14,6 % (sieben Sleeves teilen
einen ETF-Kern); der Cap kappte auf 10 % und ließ die Differenz verfallen. **23,7
Prozentpunkte, die keine Risikoregel verlangt hat.** Jetzt wird umverteilt — Schranke gleich
streng, Risikoschichten sehen weiter das volle Buch (Test: gestresstes Brutto = exakt 25 % des
ruhigen). Track-Bruch als `protection_regime` gestempelt.

**Defekt 2, beim Verifizieren gefunden und gefährlicher:** `active_sleeves()` gab JEDE
Registry-Strategie zurück. Die vier Familien von Welle 1 hätten in derselben Nacht je 1/12 des
Depots bekommen — mit null Out-of-Sample-Historie, Mean-Reversion (Sharpe 0,31) inklusive. Das
Gate der ML-Bots gilt jetzt für alle Sleeves: ≥5 Forward-Sitzungen, zurückgehaltene werden
gedruckt statt still weggelassen. Live verifiziert.

**Die Lehre:** Eine Strategie in die Registry zu legen war nie nur eine Registry-Änderung —
sie floss direkt ins Depot. Welle 1 hätte ohne Welle 2 Schaden angerichtet.

## Entscheidungen

- **Produktions-Defaults NICHT auf die Grid-Gewinner gesetzt.** Acht Jahre anzupassen ist
  Overfitting, und geänderte Parameter sind eine neue Strategie-Identität, die die
  Forward-Tracks umschreibt.
- **Kein Hand-Promoten des Gewinners.** Cross-Sectional Momentum muss die Promotion-Hürde
  nehmen wie jede Lane (≥30 Trades, ≥60 Tage, Netto > 0, PF ≥ 1,1).
- **Cap-Umverteilung aktiviert statt nur eingebaut**, weil 23,7 brachliegende Punkte ein
  messbarer Verlust ohne Risikobegründung sind — aber mit markiertem Track-Bruch, damit die
  einzige Out-of-Sample-Evidenz des Projekts lesbar bleibt.

## Offene Fragen

- Trägt Cross-Sectional Momentum auch forward? 8 Jahre Backtest im Bullenmarkt sind kein Beweis.
- Springt das Depot-Brutto beim nächsten Nightly wirklich auf ~84 %, und greift dann der
  Vol-Target-Layer stärker? Das wäre korrekt, soll aber gesehen werden.
- Low-Vol und Mean-Reversion: abschalten oder umbauen? Entscheidung braucht Forward-Daten,
  nicht eine zweite Backtest-Runde auf denselben acht Jahren.

## To-dos

### Nico
1. **`DASH_TOKEN` rotieren** · **Voices-Personenliste** bestätigen · **Cockpit-Durchklick**
   (jetzt per Tailscale: `http://100.99.224.50:8420`).
2. Zur Kenntnis: Das Depot verhält sich ab heute Nacht anders (mehr investiert). Die
   Kurve vor/nach `protection_regime` sind zwei Serien.
3. Optional: der 1.5b-Modellvergleich für den Assistenten, sobald die Maschine ruhig ist.

### Nächste Session (Agent)
- **Welle 3 (Selektionsgeschwindigkeit), noch nicht angefangen:** „n Trades bis Aussage"-Rechner
  je Lane — ohne den laufen tote Strategien monatelang weiter; und eine Verlustanatomie im
  Produkt (Exit-Grund × Regime × Titelklasse) statt per Hand wie heute.
- Rest von Welle 2: Kosten-Netting über Lanes, Session-Lane nutzt nur 10 % ihres Kapitals.
- Mi 12.08.: erste `entry_predictions`-Auflösungen prüfen (`run_evidence_refresh.py`).
- Der `insights`-Schritt passt nicht in sein Budget (heute per Timeout abgeschnitten) —
  erst einen einzelnen Aufruf messen, dann `--limit` senken oder eigener Cron-Slot.

## Einstieg für die nächste Session

Branch `autopilot/work` = `main` = `origin/main` = `8bd00bc`. Gate 1915 Tests + ruff clean,
Tree sauber. Backups von heute in
`/tmp/claude-1000/…/scratchpad/{autotrader,forward_paper}.db.bak`. Ein CronCreate-Wächter
(stündlich :23, session-only) prüft, ob v16-Tasks offen sind und arbeitet sie sonst weiter.
