# Zusendung einer Projektidee (Ideencheck, Innofonds-Wissen)

Nimmt entgegen, was jemand im Ideencheck des Portals `innofonds.m-vf.de`
ausdrücklich abschickt: eine Projektbeschreibung mit Kontaktadresse.
Legt sie ab und verschickt zwei Mails, eine an die Redaktion und eine
Bestätigung an den Absender.

## Das Versprechen, das dieser Endpunkt nicht brechen darf

Über dem Eingabefeld des Ideenchecks steht: **„Ihre Beschreibung verlässt
Ihren Rechner nicht."** Der Check rechnet vollständig im Browser, und das
bleibt so. Dieser Endpunkt bekommt nur, was jemand in einem eigenen
Kasten, mit eigenem Häkchen und eigenem Klick abschickt. Ohne
`einverstanden: true` antwortet er mit `keine-einwilligung` und speichert
nichts.

Wer das ändert, macht aus einem Vertrauensmerkmal eine Falschaussage.

## Einrichten

1. Ordner `ideen/` nach `monitor-versorgungsforschung.de/ideen/` legen,
   mit `ideen.php` darin.
2. `ideen-zugang-muster.php` daneben als **`ideen-zugang.php`** ablegen.
   Ohne diese Datei antwortet der Endpunkt mit `nicht-eingerichtet`.
3. Unterordner `daten/` muss für PHP beschreibbar sein; er wird sonst beim
   ersten Aufruf selbst angelegt.

Erreichbar ist der Endpunkt dann unter
`https://www.monitor-versorgungsforschung.de/ideen/ideen.php`.
Genau diese Adresse steht im Portal.

## Prüfen, ohne etwas anzulegen

```
curl -i https://www.monitor-versorgungsforschung.de/ideen/ideen.php
```

Erwartet: `405 {"ok":false,"grund":"nur-post"}`. Kommt stattdessen
`500 nicht-eingerichtet`, fehlt die Zugangsdatei.

```
curl -i -X POST -H "Origin: https://example.com" \
  -H "Content-Type: application/json" -d '{}' \
  https://www.monitor-versorgungsforschung.de/ideen/ideen.php
```

Erwartet: `403 herkunft`.

```
curl -i -X POST -H "Origin: https://innofonds.m-vf.de" \
  -H "Content-Type: application/json" -d '{"beschreibung":"kurz"}' \
  https://www.monitor-versorgungsforschung.de/ideen/ideen.php
```

Erwartet: `400 keine-einwilligung`. Das ist die wichtigste Prüfung: Ohne
Häkchen darf nichts durchgehen.

## Was zu beachten ist

**`daten/` darf nicht im Web lesbar sein.** Dort stehen unveröffentlichte
Projektideen. Alle Dateien beginnen deshalb mit `<?php exit; ?>` und
heißen `.json.php`, nicht `.json`. MVF läuft auf nginx, und nginx liest
keine `.htaccess`. Wer die erste Zeile entfernt oder die Endung ändert,
stellt fremdes geistiges Eigentum ins Netz.

**Keine IP-Adressen.** Die Taktbremse speichert einen Hashwert mit täglich
wechselndem Salz, wie `anmeldung.php`. Drei Zusendungen je Rechner und Tag.

**Löschen muss einfach sein.** In der Bestätigungsmail steht, dass eine
Zeile an die Redaktion genügt. Gelöscht wird von Hand in
`daten/ideen-JJJJ-MM.json.php`.

## Dateien

| Datei | Zweck |
|---|---|
| `ideen.php` | Endpunkt |
| `ideen-zugang-muster.php` | Muster für die Konfiguration |
| `daten/` | Zuschriften, Salz, Taktbremse — nicht im Web lesbar |
