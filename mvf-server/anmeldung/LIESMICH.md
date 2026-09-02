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

## Stand 01.09.2026, abends

**Der Endpunkt läuft.** Die Zugangsdatei liegt auf dem Server, der Bericht
antwortet, und die vierzehn Kennungen in `INTERESSEN` stimmen mit dem überein,
was die API meldet — am 01.09.2026 Zeile für Zeile verglichen, keine
Abweichung.

Geprüft ist damit:

| Schritt | Ergebnis |
|---|---|
| 2 hochgeladen | `POST` ohne Rumpf antwortet `{"ok":false,"grund":"methode"}` auf `GET`, also 405 — die Datei ist da und läuft |
| 5 Bericht | Zielgruppe `1c8fc10ec7` und alle Gruppen mit Namen und Kennung |
| 6 Kennungen | vollständig, gegen die API gegengelesen |
| 7 Abrufsperre | `daten/salz.json.php` antwortet mit **null Byte** — PHP wird ausgeführt, das Verzeichnis ist zu |
| Herkunft | von `https://wissen.m-vf.de` kommt `access-control-allow-origin` zurueck, von einer fremden Domain nicht |
| Honigtopf | gefülltes `falle` gibt freundlich `{"ok":true,"zustand":"neu"}` und trägt nichts ein |
| ungültige Adresse | `{"ok":false,"grund":"email"}` |

**Schritt 8 ist bestanden.** Am 01.09.2026 um 22:05 Uhr mit einer Adresse
geprüft, die noch nie in der Liste stand: Der Endpunkt antwortete
`{"ok":true,"zustand":"bestaetigung-noetig"}`, und die Bestätigungsmail kam an.
Sie landete im **Posteingang**, nicht im Spam, mit deutschem Betreff „Bitte
Anmeldung bestätigen" — der englische Betreff, an dem die Zustellung im August
noch hängen blieb, ist damit erledigt.

Der Zustand `bestaetigung-noetig` sagt mehr als ein HTTP 200: Er entsteht nur,
weil Mailchimp den Kontakt als „pending" zurückgemeldet hat und der Endpunkt
diesen Status **liest** statt ihn anzunehmen. Genau das kam über die alte
Formularadresse nie an.

**Alle drei Zustände sind belegt.** Am 01.09.2026 nacheinander an einer echten
Adresse durchgespielt:

| Ausgangslage | Antwort |
|---|---|
| Adresse unbekannt | `{"ok":true,"zustand":"bestaetigung-noetig"}` + Bestätigungsmail |
| Adresse bekannt und bestätigt | `{"ok":true,"zustand":"eingetragen"}`, Auswahl ergänzt, keine zweite Mail |
| Adresse abgemeldet | `{"ok":false,"grund":"abgemeldet"}` |

Der dritte Fall ist zugleich die einzige Probe, die die **Fassung** der Datei auf
dem Server verrät: Alt und neu unterscheiden sich ausschließlich in den Pfaden
`cleaned` und `unsubscribed`, alle anderen Antworten sind identisch. Wer nach
einem Austausch wissen will, welche Fassung oben liegt, meldet eine Testadresse
ab und sendet einmal dagegen. Kommt `eingetragen` statt `abgemeldet`, liegt die
alte dort.

Nach dem Austausch durch den Admin am 01.09.2026 abends geprüft: richtige
Fassung, dazu Bericht, Herkunftsprüfung, Honigtopf, alle Ablehnungsgründe,
`daten/` und `anmeldung-zugang.php` mit null Byte, keine Verzeichnisauflistung.

Ein Schönheitsfehler in der Bestätigungsmail: Unter „Bei Fragen zu dieser Liste
wenden Sie sich bitte an:" steht ein leerer Doppelpunkt über der Adresse
`heiser@erelation.org`. Das ist der fehlende Ansprechpartner-Name in den
Zielgruppen-Einstellungen von Mailchimp — dort zu pflegen, nicht hier.

> `php -l` ist weiterhin nicht gelaufen — auf dem Redaktionsrechner ist kein
> PHP. Dass die Datei fehlerfrei ist, zeigt inzwischen aber der Betrieb: Ein
> Syntaxfehler hätte den Bericht gar nicht erst antworten lassen.

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

Bequemer geht es **vor** dem Hochladen, ohne dass der Endpunkt schon stehen muss: `scripts/anmeldung_gruppen.py` im Repo `knowledge-hubs` liest dieselben Angaben unmittelbar aus der API und gibt den fertigen Block aus.

```bash
py scripts/anmeldung_gruppen.py
```

Der API-Schlüssel muss dafür in der Umgebungsvariablen `MAILCHIMP_API_KEY` stehen — dieselbe, die auch `mailchimp_entwurf.py` benutzt. Das Skript liest nur und ändert in Mailchimp nichts.

**Wichtig zu wissen:** Diese Kennungen stehen **nirgends in der Mailchimp-Oberfläche**. Sie sind ausschließlich über die API zu bekommen, und sie haben mit den Zahlen aus `group[16135][512]` nichts zu tun — die gehörten zum alten Formular. Wer in Mailchimp danach sucht, sucht vergebens.

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

## Dankesmail an bereits bekannte Abonnenten

Wer schon Abonnent ist und einen weiteren Newsletter dazunimmt, bekommt von
Mailchimp **nichts** — es gibt kein Double-Opt-in, weil nichts zu bestätigen
ist. Auf dem Bildschirm steht „Ihre Auswahl ist eingetragen", im Postfach
kommt nichts an.

Der Endpunkt setzt in diesem Fall einen Tag, an dem in Mailchimp eine Customer
Journey hängt:

| Schritt | Einstellung |
|---|---|
| Auslöser | Tag hinzugefügt → der Name aus `TAG_NACHBESTELLUNG` |
| Aktion 1 | E-Mail senden |
| Aktion 2 | **Tag entfernen** → derselbe Name |
| Journey | Wiedereintritt erlauben |

**Aktion 2 ist keine Kür.** „Tag hinzugefügt" feuert nur beim Übergang. Bliebe
der Tag am Kontakt kleben, liefe die Journey bei dessen nächster
Nachbestellung nicht mehr an.

Aus demselben Grund steht `TAG_NACHBESTELLUNG` in der Zugangsdatei
**standardmäßig leer**: Solange die Journey nicht existiert, darf der Tag nicht
gesetzt werden — wer ihn schon trägt, löst sie nie aus. Einschalten heißt: den
Namen eintragen, genau so wie er in Mailchimp heißt, und die Datei hochladen.

Warum der Endpunkt das entscheidet und nicht Mailchimp: Nur hier ist bekannt,
ob es eine Erst- oder eine Nachbestellung war. Ein Auslöser auf
Gruppenänderung würde auch bei Neuanmeldungen feuern — die bekämen dann zwei
Mails.

Die Mail selbst liegt als `dankesmail.html` daneben. In Mailchimp einzusetzen
über *Vorlage auswählen → Eigene Vorlage erstellen → In eigene Vorlage
einfügen*; die Basis-Layouts helfen nicht, ein reines Einspalten-Layout gibt es
dort nicht. Tabellenlayout mit Inline-Styles wie bei der Newsletter-Vorlage —
Outlook rendert mit der Word-Engine. Die drei Platzhalter `*|UPDATE_PROFILE|*`,
`*|UNSUB|*` und `*|LIST:ADDRESSLINE|*` sind Pflicht; ohne Abmeldelink und
Anschrift nimmt Mailchimp die Vorlage nicht an.

**Nicht abgedeckt:** Nachbestellungen über die Landingpage. Die läuft nicht
über diesen Endpunkt, setzt also keinen Tag.

## Wer hierher sendet

Seit dem 01.09.2026 alle dreizehn Seiten mit Formular:

- die `newsletter.html` der zwölf Portale — sie schickt `hubs` mit dem
  Schlüssel des eigenen Hubs, dazu die angekreuzten Schwesterportale und
  `mvf` für den redaktionellen Newsletter. Der eigene Schlüssel steht dort
  als `const HUB` und kommt aus dem Platzhalter `{{HUB}}` der Vorlage.
- die Gewinnspielseite `gewinnspiel/index.html` — sie schickt zusaetzlich
  `tags` mit `Gewinnspiel DKVF 2026`, aber nur innerhalb des
  Teilnahmezeitraums aus Nummer 3 der Teilnahmebedingungen; außerhalb sperrt
  sie das Häkchen selbst, die Newsletter-Bestellung bleibt offen.

Der Störungshinweis, der vom 31.08. bis 01.09.2026 an ihrer Stelle stand, ist
damit überall verschwunden.

Fällt der Endpunkt aus, melden die Seiten das und verweisen auf Mailchimps
eigene Anmeldeseite. Sie erfinden keinen Erfolg mehr — genau das war der
Grund, das alte Formular abzuschalten.
