# Handy-App: APK gebaut, HTTPS-Weg entstört (2026-08-28)

Ausgangsfrage von Nico: „Ist die App fürs Handy fertig, und kannst du darüber online
Updates machen?" Antwort nach Prüfung: fast — es fehlten zwei Dinge, von denen eines
nicht das war, wofür wir es gehalten hatten.

## Was der Stand wirklich war

| Angenommen | Tatsächlich |
| --- | --- |
| „Nur noch `sudo bash scripts/setup_https.sh`" | Das Skript wäre auch mit Root gescheitert: **Serve ist auf dem Tailnet nicht freigeschaltet** — ein Klick in der Admin-Konsole, kein Befehl. |
| APK per Actions baubar | Der Workflow lag nur lokal: 163 Commits waren nie gepusht, `workflow_dispatch` gab es auf GitHub nicht. |
| Tailscale-SSH tot | Falscher Indikator geprüft. `RunSSH: True` — der Zugang steht. |
| Dienst als loser Prozess | User-Unit `equity-scout-dash`, `enabled`, `Linger=yes` — kommt nach WSL-Neustart von allein hoch. |

## Der APK-Build: sechs Defekte, alle im Workflow

Der Workflow war nie gelaufen. Jeder Fehler verdeckte den nächsten:

1. **Bubblewrap fragte nach dem Android-SDK** → Exit 130 auf dem Runner. Jetzt zeigt
   `~/.bubblewrap/config.json` auf das SDK, das der Runner ohnehin mitbringt.
2. **„The provided androidSdk isn't correct."** — `validatePath` verlangt `tools/` oder
   `bin/` im SDK-Wurzelverzeichnis; moderne SDKs haben nur `cmdline-tools/`. Symlink.
3. **ENOTFOUND auf die Tailnet-Adresse** — `--skipPwaValidation` überspringt die
   PWA-Prüfung, nicht das Herunterladen von Icons und Web-Manifest. Beide liegen im Repo
   und werden jetzt lokal ausgeliefert. Ein `|| true` hatte das jahrelang verdeckt.
4. **Checksummen-Prompt** — das Manifest wurde NACH `bubblewrap update` zurückkopiert und
   machte `manifest-checksum.txt` ungültig. Reihenfolge umgedreht.
5. **Selbst gebautes Sicherheitsnetz war der Fehler** — `sha1sum` hängt ein `\n` an, das
   Bubblewrap nicht schreibt. Entfernt.
6. **Passwort-Prompt trotz Flags** — `--keystorePassword` kennt `build` gar nicht, es
   liest nur `BUBBLEWRAP_KEYSTORE_PASSWORD` / `BUBBLEWRAP_KEY_PASSWORD`.
7. **„stderr maxBuffer length exceeded"** — Bubblewrap ruft Gradle ohne `maxBuffer` auf,
   also gilt Nodes 1-MB-Default. Gradle leise gestellt und vorgewärmt.

Grün: Run 33165111175. Die APK liegt als `Downloads/equity-scout-v1.apk`.
Ihr Fingerprint stimmt mit `.state/android-fingerprint.txt` und dem überein, was das
Cockpit live unter `/.well-known/assetlinks.json` ausliefert.

## Befund, der Nico gehört

Tailnet-Adresse (`wsl-claude.tail7dff17.ts.net`) und Tailnet-IP stehen **seit Wochen im
öffentlichen Repo** — nicht erst seit heute, sie waren schon in `origin/main`. Keine
Credentials, und ohne Tailscale-Anmeldung erreicht die Adresse niemand. Sauber bekommt man
das nur mit einem History-Rewrite plus Force-Push, und beides ist bestätigungspflichtig.

## Offen (nur Nico)

1. Tailscale-Konsole: **HTTPS Certificates** und **Serve** freischalten.
2. `sudo bash scripts/setup_https.sh` — erledigt jetzt auch SSH, den Dienst-Neustart im
   richtigen (`--user`) Scope und eine Gegenprobe auf die HTTPS-Adresse.
3. APK öffnen, Benachrichtigungen einschalten.
