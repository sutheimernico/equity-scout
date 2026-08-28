# Die App aufs Handy — in vier Schritten

Stand 2026-08-27. Alles kostenlos, nichts verlässt dein Tailnet außer den
Benachrichtigungen selbst.

## Warum das überhaupt Schritte braucht

Ein Handy zeigt eine Benachrichtigung nur dann als *App*-Nachricht an, wenn die Seite,
die sie schickt, über **HTTPS** läuft. `http://100.99.224.50:8420` reicht dafür nicht —
weder für Push noch für „App installieren". Tailscale kann genau das kostenlos: eine
echte HTTPS-Adresse `https://wsl-claude.tail7dff17.ts.net`, gültiges Zertifikat, nur
innerhalb deines Tailnets erreichbar. Das Internet kommt da nicht ran.

## Schritt 0 — zwei Schalter in der Tailscale-Konsole (einmalig, im Browser)

Beides ist ein Klick, kein Befehl, und **ohne beides scheitert Schritt 1**:

| Schalter | Wo | Wofür |
| --- | --- | --- |
| **HTTPS Certificates** | [login.tailscale.com/admin/dns](https://login.tailscale.com/admin/dns) | damit `tailscale cert` ein echtes Let's-Encrypt-Zertifikat ausstellen darf |
| **Serve** | Hinweis-Link, den `tailscale serve` selbst ausgibt (node-spezifisch) | damit Port 443 vor den Dienst darf |

Am 2026-08-28 hing genau hier der erste Anlauf: `tailscale serve` antwortete
`Serve is not enabled on your tailnet` — und zwar mit Exit-Code 0, also ohne dass ein
Skript das als Fehler bemerkt hätte. `scripts/setup_https.sh` prüft das inzwischen selbst
und nennt dir die Adresse, statt wortlos abzubrechen.

## Schritt 1 — HTTPS anschalten (einmalig, braucht Root)

```bash
cd ~/private/equity-scout
sudo bash scripts/setup_https.sh
```

Das Skript setzt den Tailscale-Operator (damit danach nichts mehr Root braucht), schaltet
Tailscale-SSH ein (der Weg, über den Claude vom Handy aus arbeitet), holt das Zertifikat,
hängt HTTPS vor den Dienst auf Port 8420 und trägt die Adresse als `PUBLIC_BASE_URL` in
die `.env` ein. Jeder dieser Schritte meldet sich einzeln, wenn er nicht durchkommt. Danach den Dienst einmal neu starten, damit er die
Variable sieht.

**Warum nicht automatisch erledigt:** `tailscale cert` verlangt Root, und in dieser Sitzung
gibt es kein Passwort. Es ist der einzige Schritt dieser Art.

## Schritt 2 — App installieren

Auf dem Handy (Tailscale an) `https://wsl-claude.tail7dff17.ts.net` öffnen, einmal den
Token eingeben (`?token=…`), dann Chrome-Menü → **App installieren**. Ab jetzt liegt das
Cockpit als Icon auf dem Startbildschirm und läuft im Vollbild.

## Schritt 3 — Benachrichtigungen einschalten

In der App: **Mehr → Benachrichtigungen → „Benachrichtigungen einschalten"**. Android
fragt einmal nach Erlaubnis, danach kommt sofort eine Testnachricht. Kommt sie nicht, sagt
die Karte, woran es liegt — sie rät nicht.

Ab dann meldet sich die App von selbst:

| Wann | Was |
| --- | --- |
| Täglich nach dem Update | Chancen, die die Qualitätsschwelle schaffen und handelbar sind |
| Ebenfalls täglich | „Bald": Titel kurz über ihrer Kaufzone, für die sich ein Limit lohnt |
| Wenn etwas ausfällt | Der Wächter, wenn eine Kette zu lange still war |

Jede Meldung trägt eine Begründung in Alltagssprache und ihre Gegenrede. Nichts davon ist
eine Kaufempfehlung.

## Schritt 4 (optional) — die echte APK

Die installierte Web-App reicht für alles, auch für Push. Wer trotzdem eine `.apk` will
(eigenes Icon im App-Drawer, kein Chrome-Branding beim Start):

1. Auf GitHub → **Actions → Android-APK → Run workflow**
2. `host` = `wsl-claude.tail7dff17.ts.net`, `version_code` bei jedem Update um 1 erhöhen
3. Nach dem Lauf das Artefakt `equity-scout-apk` herunterladen und auf dem Handy
   installieren (Android fragt einmal nach „Installation aus unbekannter Quelle")

Die App ist eine **Trusted Web Activity**: außen eine echte Android-App, innen Chrome auf
dieselbe Adresse. Genau deshalb funktioniert Web Push darin — eine klassische WebView-App
kann das nicht.

Signaturschlüssel: liegt als PKCS12 unter `.state/android-keystore.p12` (nicht im Git) und
zusätzlich als GitHub-Secret `ANDROID_KEYSTORE_B64` / `ANDROID_KEYSTORE_PASSWORD`, damit
ein Update dieselbe Signatur trägt — sonst müsste die App bei jedem Build neu installiert
werden. Sein Fingerabdruck steht in `.state/android-fingerprint.txt` und wird über
`/.well-known/assetlinks.json` ausgeliefert; **diese eine Datei liegt bewusst vor dem
Token-Gate**, weil Chrome sie ohne Anmeldung abruft. Sie enthält nichts Geheimes.

## Die drei Kanäle

| Kanal | Wofür | Braucht |
| --- | --- | --- |
| **App-Nachricht** (Web Push) | Der Hauptweg. Meldung kommt von dieser App. | HTTPS + installierte App |
| **ntfy** | Reserve. Funktioniert auch ohne installierte App. | ntfy-App + `NTFY_TOPIC` in `.env` |
| **Telegram** | Die lange Fassung mit Chart und Knöpfen. | wie bisher |

ntfy ist bereits eingerichtet: Topic steht in der `.env`, ein Test wurde am 2026-08-27
zugestellt. Auf dem Handy die App *ntfy* installieren (Play Store oder F-Droid, kostenlos),
Topic abonnieren — der Name des Topics ist das Passwort, also nirgends posten.

**Grenze, die du kennen solltest:** ntfy.sh ist ein öffentlicher Server. Der Inhalt der
Meldung (Firmenname, Kurs, Begründung) läuft unverschlüsselt darüber. Das sind
Screening-Ergebnisse, keine Depotdaten — aber es ist eine bewusste Entscheidung, keine
technische Notwendigkeit. Abschalten: `NTFY_TOPIC` aus der `.env` entfernen.

## Wenn nichts ankommt

1. Läuft der Rechner? Ohne ihn schickt niemand etwas — das ist der häufigste Fall.
2. In der App unter *Benachrichtigungen* auf **Testnachricht schicken**. Die Antwort nennt
   jeden Kanal einzeln.
3. Zeigt die Geräteliste „noch nichts zugestellt", ist das Abo tot: aus- und wieder
   einschalten (Android löscht Abos, wenn die App lange nicht offen war).
