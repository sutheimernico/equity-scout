# VolTarget nutzt den schwächeren Schätzer (2026-08-12)

Nicos Richtungsentscheidung: „mach mal dein Ding" auf meine Empfehlung, die **Risiko-Schiene** vor
den Fundamentaldaten anzugehen. Begründung war der W0-Befund vom Vortag: an diesen Daten ist die
Renditefrage nicht entscheidbar, **die Risikofrage schon**. Nur nutzt das Depot das noch nicht.

## Ergebnis in drei Sätzen

1. **`VolTarget` drosselt anhand der TRAILING 20-Tage-Vola — also erst, nachdem die Volatilität
   gestiegen ist.** Der VIX sagt dieselben 20 Tage im Voraus besser vorher: **rho 0,642 gegen
   0,539** auf 233 nicht überlappenden Fenstern über 19 Jahre.
2. **Inkrementell ist der Abstand noch deutlicher.** Nach Abzug der trailing Vola trägt der VIX
   **rho 0,390** bei; umgekehrt bleibt von der trailing Vola nach Abzug des VIX nur **rho 0,099**.
   Der VIX enthält also fast alles, was die trailing Vola weiß, plus deutlich mehr.
3. **Out of sample bestätigt:** ein auf 2007–2016 gefitteter Divisor für die Varianzrisikoprämie
   (1,341) hält 2017–2026 — dort **rho 0,678 gegen 0,565**, Kalibrierung 1,07.

**Das ist der erste positive Befund dieser Serie.** Alle vorherigen Runden (Evidenz, Volumen,
Zielgröße, Universum) waren Nullbefunde.

## Warum das eine Messung und keine Meinung ist

Methodisch identisch zum W0-Gate, weil die Fehlerquelle dieselbe ist:

- **Nur nicht überlappende Fenster.** Eine Tagesreihe von 20-Tage-Vorwärtsfenstern teilt 19 von 20
  Tagen; als unabhängig behandelt bläht das jede Statistik um ~√20 auf. Aus 4.910 Tagesbeobachtungen
  werden so 234 unabhängige — und die Aussage steht auf diesen 234.
- **Inkrementell entscheidet, nicht roh.** Dass zwei Volatilitätsmaße korrelieren, ist keine
  Nachricht. Die Frage ist, was der eine über den anderen hinaus trägt.
- **Rangfolge und Kalibrierung getrennt gemessen.** Das ist die eigentliche Falle hier, siehe unten.

## Die Falle: roher VIX rankt am besten und wäre trotzdem falsch

`VolTarget` skaliert mit `ziel / schätzer`. Ein Schätzer, der systematisch 36 % zu hoch liest,
drosselt also **jeden Tag** 36 % zu stark — dauerhaft zu wenig investiert, ohne dass jemand einen
Defekt sieht. Genau das ist roher VIX: implizite Vola enthält die Varianzrisikoprämie.

| Kandidat | rho (voll) | Kalibrierung |
|---|---|---|
| A: trailing (Status quo) | +0,539 | **1,00** |
| B: VIX unskaliert | **+0,642** | **1,36** ✗ |
| C: trailing × (VIX / VIX-Mittel), parameterfrei | +0,587 | 1,02 |
| D: max(trailing, VIX) | +0,632 | 1,41 ✗ |

Deshalb wurde der Divisor nicht einfach angepasst, sondern **out of sample geprüft**: auf der
ersten Hälfte gefittet (1,341), auf der zweiten beurteilt.

| Zweite Hälfte, ab 2017 | rho | Kalibrierung |
|---|---|---|
| A: trailing | +0,565 | 1,01 |
| **B: VIX / 1,341** | **+0,678** | **1,07** |
| C: parameterfrei | +0,630 | 1,04 |

B hält beides und gewinnt. C bleibt der Rückfall für den Fall, dass man keinen gefitteten
Parameter in einer Schutzschicht haben will — es ist immer noch besser als der Status quo.

## Was daraus gebaut werden soll — und was nicht

**Nicht** die SPY-Vola-Prognose direkt in `VolTarget` schreiben. Das Depot ist Multi-Asset, seine
Vola liegt unter der von SPY; ein SPY-Niveau würde die Drosselung dauerhaft verschärfen. Die
Studie misst auf SPY nur, weil die Depot-Historie mit ~10 Bewertungen für eine Vola-Studie viel zu
kurz ist — das ist eine Proxy-Annahme und hier ausdrücklich benannt.

**Sondern** ein dimensionsloser Erwartungs-Multiplikator: `VIX-Prognose / SPY-trailing-Vola`,
angewendet auf die **eigene** trailing Depot-Vola. Damit bleibt das Niveau das des Depots
(Kalibrierung gelöst) und die Information kommt vom VIX (Rangfolge verbessert). Auf SPY angewendet
reduziert sich diese Formel genau auf Kandidat B — also auf das, was hier gemessen wurde.

Pflicht beim Einbau: **fällt der VIX aus, muss die Schicht auf die trailing Vola zurückfallen, nicht
den Schutz abschalten.** Eine Datenlücke darf niemals als „kein Risiko" gelesen werden.

## Bewusst noch nicht eingebaut

Der Einbau greift in eine **live laufende Risikoschicht** des Depots ein, und in derselben Nacht
wirkt zum ersten Mal die Entthronung (Sleeve fällt weg, einmalige Umschichtung von ~32 %). Zwei
Eingriffe in einer Nacht würden die Ursachenzuordnung zerstören, falls morgen etwas auffällt. Die
Messung ist gesichert und reproduzierbar (`scripts/run_vol_forecast_study.py`, sechs Tests auf
synthetischen Regimewechseln); der Einbau ist der nächste Schritt, nach der Verifikation der
Nightly.

## Reproduzieren

```
uv run python scripts/run_vol_forecast_study.py
```

Läuft aus den Snapshots (`behaviour_sleeve_closes.csv`, `vix_term.csv`), kein Netzwerk.
