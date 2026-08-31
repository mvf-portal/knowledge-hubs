# Anmelde-Endpunkt für die Knowledge-Hubs

Ein PHP-Skript auf dem MVF-Server, das Newsletter- und Gewinnspielanmeldungen von den Hub-Seiten entgegennimmt und über die **Mailchimp-API** einträgt. Zwei Dateien und ein Verzeichnis — kein Composer, keine Bibliothek, kein fremder Dienst. Der API-Schlüssel bleibt auf dem Server.

Aufbau und Ablage wie beim Zähler unter `/zaehler/`, der seit August 2026 dort läuft.

## Warum es das gibt

Bis zum 31.08.2026 sendeten die Hub-Seiten unmittelbar an Mailchimps Formularadresse `/subscribe/post`. **Das funktioniert nicht mehr.** Diese Adresse ist inzwischen mit Googles reCAPTCHA und Akamais Bot Manager geschützt. Eine Einsendung von einer fremden Domain bringt weder ein reCAPTCHA-Zeichen noch die Akamai-Telemetrie mit — Mailchimp nimmt sie mit HTTP 200 an und verwirft sie. Keine Anmeldung, keine Bestätigungsmail, kein Hinweis.

Belegt am 31.08.2026: zwei echte Adressen über die Seite angemeldet, keine Bestätigungsmail erhalten, der zugehörige Tag zählte danach null Kontakte. Der Endpunkt selbst antwortet dabei einwandfrei — auf eine ungültige Adresse kommt die richtige Fehlermeldung. Es liegt am Botschutz, nicht an der Abfrage.

Der Weg über die API ist der von Mailchimp dafür vorgesehene. Er heilt zwei weitere Dinge mit:

- **Bestehende Kontakte.** Die Formularadresse verwarf bei einer bereits eingetragenen Adresse alles Mitgeschickte. Wer schon Abonnent war, konnte über eine Hub-Seite nie einen weiteren Newsletter dazunehmen. Die API kann das.
- **Ehrliche Rückmeldung.** Das Formular sendete in einen unsichtbaren Rahmen, dessen Inhalt es aus Sicherheitsgründen nicht lesen darf, und meldete deshalb nach vier Sekunden in *jedem* Fall Erfolg. Hier kommt eine echte Antwort zurück.

## Was gespeichert wird

Nichts, was auf eine Person zeigt. Keine E-Mail-Adresse, kein Name, keine IP-Adresse. In `daten/` liegen nur:

| Datei | Inhalt |
|---|---|
| `salz.json.php` | die Zufallszahl des Tages |
| `takt-JJJJ-MM-TT.json.php` | Hashwerte für die Taktbremse, täglich neu, ältere werden gelöscht |
| `liste.json.php` | die Kennung der Mailchimp-Zielgruppe |
| `fehler.json.php` | die letzten 200 Fehlermeldungen von Mailchimp, ohne Adressen |

Die Endung `.php` ist kein Versehen: **MVF läuft auf nginx, und nginx liest keine `.htaccess`.** Eine `.json` wäre im Web abrufbar. Jede dieser Dateien beginnt mit `<?php exit; ?>` und wird deshalb nicht ausgeliefert, sondern ausgeführt — und bricht sofort ab. Dahinter steht reines JSON. Wer die erste Zeile entfernt, öffnet das Verzeichnis.

## Einbau

**1. Zugangsdatei anlegen.** `anmeldung-zugang-muster.php` umbenennen in `anmeldung-zugang.php` und ausfüllen — der API-Schlüssel und ein selbst gewähltes Kennwort für den Bericht. Die Kommentare in der Datei führen Schritt für Schritt.

**2. Per FTP hochladen** nach `/anmeldung/` im Web-Verzeichnis von `monitor-versorgungsforschung.de` — dorthin, wo auch `wp-content` und `zaehler` liegen:

```
/anmeldung/anmeldung.php
/anmeldung/anmeldung-zugang.php
/anmeldung/daten/            (leeres Verzeichnis)
```

**3. Rechte setzen.** `daten/` muss für PHP beschreibbar sein — meist `755`, bei manchen Hostern `775`. Legt das Skript das Verzeichnis selbst an, ist nichts zu tun.

**4. Syntax prüfen**, falls die Kommandozeile zur Hand ist:

```bash
php -l anmeldung.php
```

Erwartet: `No syntax errors detected`. Diese Prüfung ist auf dem Redaktionsrechner nicht gelaufen — dort ist kein PHP installiert.

**5. Den Bericht aufrufen.** Er zeigt, ob der Schlüssel stimmt und Mailchimp antwortet:

```
https://www.monitor-versorgungsforschung.de/anmeldung/anmeldung.php?bericht=1&schluessel=DAS_KENNWORT
```

Erwartet: die Kennung der Zielgruppe und darunter alle Gruppen mit Namen und Kennung. Kommt stattdessen `{"ok":false,"grund":"schluessel"}`, stimmt das Kennwort nicht; `nicht-eingerichtet` heißt, die Zugangsdatei fehlt oder ist nicht lesbar.

**6. Die Kennungen eintragen.** Aus der Liste aus Schritt 5 die Kennungen in `INTERESSEN` in der Zugangsdatei übernehmen. Solange sie leer sind, weist der Endpunkt jede Bestellung mit `unbekannter-hub` ab — das ist Absicht: Ein Endpunkt im offenen Netz darf nur in Gruppen eintragen, die ausdrücklich benannt sind.

**7. Gegenprobe, dass die Daten nicht öffentlich sind:**

```bash
curl -s "https://www.monitor-versorgungsforschung.de/anmeldung/daten/salz.json.php"
```

Erwartet: **eine leere Antwort**. Steht dort eine Zeichenfolge hinter `"salz"`, wird PHP in diesem Verzeichnis nicht ausgeführt — dann darf der Endpunkt nicht in Betrieb gehen, bevor das geklärt ist.

**8. Eine Probeanmeldung**, mit einer Adresse, die noch nie in der Liste stand:

```bash
curl -s -X POST "https://www.monitor-versorgungsforschung.de/anmeldung/anmeldung.php" \
  -H "Content-Type: application/json" \
  -H "Origin: https://knowledge-hubs.m-vf.de" \
  -d '{"email":"probe@example.org","hubs":["wissen"]}'
```

Erwartet: `{"ok":true,"zustand":"bestaetigung-noetig"}` und kurz darauf eine Bestätigungsmail an diese Adresse. In Mailchimp muss der Kontakt dann als **„Ausstehend"** stehen — genau das, was über die alte Formularadresse nie ankam.

## Die Schnittstelle

`POST` mit JSON, Herkunft muss eine der Hub-Domains sein (die Liste steht oben in `anmeldung.php`).

```json
{
  "email":    "name@einrichtung.de",
  "vorname":  "",
  "nachname": "",
  "hubs":     ["wissen", "impfen"],
  "tags":     ["Gewinnspiel DKVF 2026"],
  "falle":    ""
}
```

`vorname`, `nachname`, `tags` und `falle` sind freiwillig. `falle` ist der Honigtopf: Menschen sehen das Feld nicht, Formularroboter füllen es — ist es gefüllt, passiert nichts, die Antwort sieht aber freundlich aus.

Antwort:

| | |
|---|---|
| `{"ok":true,"zustand":"bestaetigung-noetig"}` | neu angelegt, Bestätigungsmail unterwegs |
| `{"ok":true,"zustand":"eingetragen"}` | war schon Abonnent, Auswahl wurde ergänzt |
| `{"ok":false,"grund":"email"}` | Adresse fehlt oder ist ungültig |
| `{"ok":false,"grund":"abgemeldet"}` | hat sich abgemeldet — nur die Person selbst darf sich wieder eintragen |
| `{"ok":false,"grund":"unbekannter-hub"}` | `INTERESSEN` ist nicht gefüllt oder der Schlüssel ist falsch |
| `{"ok":false,"grund":"zu-oft"}` | Taktbremse |
| `{"ok":false,"grund":"mailchimp"}` | Mailchimp hat abgelehnt — Grund steht im Bericht |

## Was danach noch fehlt

Die Hub-Seiten senden noch nicht hierher. Solange steht auf allen zwölf `newsletter.html` und auf der Gewinnspielseite ein Störungshinweis, der auf Mailchimps eigene Anmeldeseite führt — die trägt den Botschutz selbst und funktioniert. Die Umstellung der Seiten erfolgt, sobald dieser Endpunkt Schritt 8 besteht.
