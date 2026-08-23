# Session 2026-08-19 22:55 – 2026-08-20 08:45 — WSL-OOM-Diagnose + drei Schutzebenen

## Kontext & Ziel

Einstiegsfrage von Nico: „Meine letzten Chats haben sich die ganze Zeit geschlossen, warum?"
Auftrag danach: vollständig abstellen, damit der Autotrader durchläuft.

Befund: **Claude ist nicht abgestürzt — die WSL-VM ist gestorben.** Claude Code lebt nur im
Terminal-Prozess der Distro, also nimmt jeder VM-/Distro-Neustart jede offene Session mit.
Drei Neustarts in fünf Minuten (22:50, 22:52, 22:55), davor lief die VM 1 Tag 3 Stunden.

Ursachenkette, belegt aus `/var/log/syslog` und `last reboot`:

1. `run_matrix_qualify.py` sammelte 13,8 Mio Zell-Dicts in einem `defaultdict(list)` — 9,7 GB.
2. Die VM war per WSL-Default auf 15,8 GiB gedeckelt (**keine `.wslconfig` vorhanden**).
3. 22:48:29 `Out of memory: Killed process 28334 (python3) anon-rss:10641348kB`, Load 13.
4. Distro-Neustarts → alle Sessions weg, Matrix-Auswertung mit 0-Byte-Log tot.

Zwei Fehlspuren ausgeschlossen (nicht nochmal verfolgen): **Der Rechner schläft nicht**
(`STANDBYIDLE` am Netz = 0, keine Kernel-Power-Events in 4 h). Und die vielen 75-Sekunden-
Sessions um 05:12/13:00/16:00–16:10 sind **keine Abbrüche**, sondern clip-scout-Headless-Aufrufe
(`claude -p`), die sauber mit ihrem JSON endeten.

## Ergebnis

Drei Commits auf `autopilot/work`, Gate grün (**2474 Tests, exit 0**), nicht gepusht:

| Commit | Inhalt |
|---|---|
| `b3f18c9` | `fix(matrix)`: Streaming-Akkumulatoren statt Zell-Dicts |
| `d746193` | `feat(ops)`: `scripts/mem_guard.sh` + Verdrahtung in 5 Ketten |
| `74347d3` | `docs(ops)`: Vorfall + Verteidigung in `docs/scheduling.md` |

**1. Der eigentliche Bug.** `pool_checkpoint` (ersetzt `stream_cells` + `pooled_from_groups`)
führt einen `PooledCells`-Akkumulator pro Gruppe. `pool_cells` ist jetzt ein dünner Wrapper
darüber — die Arithmetik existiert genau einmal. Gemessen an echten Checkpoints:

| Datei | Zellen | Gruppen | vorher | jetzt |
|---|---|---|---|---|
| `matrix_cells.jsonl` (4,2 GB) | 13,8 Mio | 939k | 9,7 GB → OOM | **1,21 GiB / 46 s** |
| `matrix_cells_d2.jsonl` (30,7 GB) | ~100 Mio | 7,08 Mio | ~70 GB → nie machbar | **5,95 GiB / 394 s** |

**2. `scripts/mem_guard.sh`** vor `run_{nightly,daily,weekly}_guarded.sh` und beiden
`night_matrix_chain*.sh`. `systemd-run --user --scope` mit `MemoryHigh`/`MemoryMax` bei
60 %/80 % des **tatsächlichen** VM-RAMs, plus `oom_score_adj=+500`. Root-frei.

**3. `%USERPROFILE%\.wslconfig`** (neu): `memory=20GB`, `swap=24GB`, `vmIdleTimeout=-1`,
`autoMemoryReclaim=gradual`. Liegt außerhalb jedes Repos — dokumentiert in `docs/scheduling.md`.

**Live verifiziert:**
- Echte nightly-Kette im Scope: `memory.high 9.3G`, `memory.max 13G`, `oom_score_adj 500`.
- **Nightly-Lauf 2026-08-20 02:30–02:43 komplett durch, `rc=0`**, alle Schritte OK, kein OOM.
  Die dreifache Trigger-Arbitrierung griff korrekt (cron hielt den Lock, systemd + windows
  sauber übersprungen).
- 13 neue Tests, u. a. Bit-Identität über 200 Zufallsgruppen inkl. der `None`-Zweige und ein
  `tracemalloc`-Regressionsschutz gegen das Wiedereinbauen der Per-Zell-Liste.

Nebenbei: `cc()` in `~/.bash_aliases` startet Claude in tmux. Memory-Eintrag
`wsl-host-memory-limits.md` angelegt.

## Entscheidungen

- **Deckel RAM-relativ statt fest** — ein fixer 16-GB-Deckel hätte über dem alten 15,8-GiB-Cap
  gelegen und nichts bewacht; der Cap hat sich an einem Tag geändert und wird es wieder.
- **`mem_guard` degradiert offen** (kein systemd-run / kein Bus / rc 237 → läuft ungedeckelt) —
  ein fehlender Deckel darf keine Trainingsnacht kosten.
- **`pool_cells` als Wrapper über den Akkumulator**, nicht zwei Implementierungen — Messcode
  unter Speicherdruck umzuschreiben ist genau der Weg, auf dem ein Artefakt entsteht.
- **Bit-Identität asserted, nicht angenommen** — `==` auf floats, nicht `approx`.
- **`swapfile`-Pfad wieder entfernt**: `C:\` ist für Nicht-Admins nicht beschreibbar, der
  WSL-Default-Pfad ist sicherer.
- **earlyoom verworfen** — hätte sudo gebraucht (Passwort), die drei Ebenen reichen ohne root.

## Offene Fragen

- Reichen Windows die restlichen ~11,6 GB? Falls es zäh wird, ist `memory=18GB` der Rückweg.
- `matrix_cells_d3.jsonl` (26,2 GB) wurde nicht gemessen, nur d1 und d2. Sollte zwischen den
  beiden liegen, ist aber unbelegt.

## To-dos

### Nico

1. **Nichts** für den WSL-Neustart — der lief automatisch am Ende dieser Session, das Ergebnis
   steht unten im Abschnitt „Verify nach `wsl --shutdown`". Falls der Abschnitt fehlt oder
   „FEHLGESCHLAGEN" sagt: `%USERPROFILE%\wsl-restart-verify.log` auf der Windows-Seite ansehen.
2. **Entscheiden, ob der volle Matrix-Qualify-Lauf startet.** Er ist jetzt möglich (vorher
   nicht), aber Gate 4 öffnet das 2023–2025-Hold-out, und das geht laut deinem eigenen Design
   genau einmal, mit vorher registrierter Hypothese. Deshalb bewusst nicht gestartet.
3. **clip-scout läuft auf Akku nicht** — die drei Windows-Tasks haben
   `StopIfGoingOnBatteries=True` und `DisallowStartIfOnBatteries=True`. Andere Fehlerklasse als
   diese Session, deshalb nur benannt. Sag Bescheid, wenn ich das angleichen soll.
4. Die 3 Commits sind **nicht gepusht** (dazu die älteren unpushed vom 11.08.).

### Nächste Session (Agent)

- `docs/sessions/` ist in diesem Repo **nicht** gitignored, die bestehenden Session-Docs sind
  versioniert. Repo-Konvention gewinnt gegen den Skill-Default — beim Committen mitnehmen.
- Fremde uncommittete Änderungen bewusst nicht angetastet: `scripts/run_train_entry.py`,
  `tests/test_run_train_entry.py`, `docs/research/2026-08-18-news-latency-decay.md`.
- Für neue Langläufer `scripts/mem_guard.sh` vorschalten, nicht nackt starten.
- Die Neustart-Verifikation lief aus zwei Dateien **außerhalb** der Repos, weil ein
  `wsl --shutdown` jeden Prozess in der VM tötet: `~/private/ops/verify_wsl_memory.sh`
  (unversioniert) und `%USERPROFILE%\wsl-restart-verify.ps1` als detachter Windows-Prozess.
  Beide sind wiederverwendbar, falls der Cap nochmal geändert wird.

## Einstieg für die nächste Session

Branch `autopilot/work`, Gate grün. Erst den Verify-Abschnitt unten lesen: steht dort
„BESTANDEN", ist die Speicherfrage abgeschlossen und die offene Entscheidung ist Nicos
Hold-out-Freigabe (To-do 2) — dafür `writing-plans` für die Hypothesen-Registrierung vor
Gate 4, nicht direkt `run_matrix_qualify.py` starten. Steht dort „FEHLGESCHLAGEN", zuerst
`%USERPROFILE%\wsl-restart-verify.log` und `%USERPROFILE%\.wslconfig` gegenprüfen.

---
## Verify nach `wsl --shutdown` — 2026-08-20T08:44:32+02:00

| Prüfung | Wert | Erwartet |
|---|---|---|
| VM-RAM | **19.5 GiB** | > 17 (vorher 15,4) |
| VM-Swap | **24.0 GiB** | ~24 (vorher 4,0) |
| Boot | 2026-08-20 08:44:29 | gerade jetzt |

**Ergebnis: BESTANDEN**

Abgeleitete mem_guard-Deckel (60 % / 80 % des VM-RAMs):

```
  MemoryHigh = 12000 MiB
  MemoryMax  = 16000 MiB
```

Cron-Flotte: 1 cron-Prozess(e), 15 aktive Jobs.
Letzter nightly-Marker: 2026-08-20
