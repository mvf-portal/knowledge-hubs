# Bestellendpunkt für die Evidenzsynthesen (Innofonds-Wissen)

Nimmt Bestellungen aus dem Portal `innofonds.m-vf.de` entgegen,
rechnet den Preis, legt den Vorgang ab und verschickt zwei Mails:
Auftragsbestätigung an den Besteller, Bestellung an die Rechnungsstelle.

## Einrichten

1. Ordner `bestellung/` nach `monitor-versorgungsforschung.de/bestellung/`
   legen, mit `bestellung.php` darin.
2. `bestellung-zugang-muster.php` daneben als **`bestellung-zugang.php`**
   ablegen und ausfüllen (Empfänger, Steuersatz, Preise, Nachlässe).
   Ohne diese Datei antwortet der Endpunkt mit `nicht-eingerichtet`.
3. Unterordner `daten/` muss für PHP beschreibbar sein; er wird sonst beim
   ersten Aufruf selbst angelegt.

Erreichbar ist der Endpunkt dann unter
`https://monitor-versorgungsforschung.de/bestellung/bestellung.php`.
Genau diese Adresse steht im Portal.

## Prüfen

```
curl -i -X POST https://monitor-versorgungsforschung.de/bestellung/bestellung.php \
  -H "Content-Type: application/json" \
  -H "Origin: https://innofonds.m-vf.de" \
  -d '{"institution":"Testhaus","name":"Test","strasse":"Weg 1","plz":"53115",
       "ort":"Bonn","email":"IHRE-ADRESSE","kohorte":"Pflege","stufe":1,
       "umfang":"einzeln","nachlass":"keiner","einverstanden":true}'
```

Erwartet: `{"ok":true,"nummer":"ER-IW-2026-0001", ...}` und zwei Mails.
Eine Testbestellung steht danach in `daten/bestellungen-JJJJ-MM.json.php`
und muss von Hand gelöscht werden — die Nummer bleibt vergeben.

## Was zu beachten ist

**`daten/` darf nicht im Web lesbar sein.** Alle Dateien dort beginnen
deshalb mit `<?php exit; ?>` und heißen `.json.php`, nicht `.json`. MVF
läuft auf nginx, und nginx liest keine `.htaccess` — eine `.json` wäre
abrufbar, und dort stehen Anschriften. Wer die erste Zeile entfernt oder die
Endung ändert, öffnet das Verzeichnis.

**Der Preis wird hier gerechnet, nicht im Browser.** Die Seite sendet nur
`stufe`, `umfang` und `nachlass`. Ein mitgesendeter Betrag wäre ein
Vorschlag, kein Preis. Preisänderungen gehören deshalb ausschließlich in
`bestellung-zugang.php`, und die Anzeige im Portal ist danach nachzuziehen
(`PREIS` in `if_portal.py`).

**Die Auftragsnummer kommt aus `daten/zaehler.json.php`.** Sie läuft je Jahr
hoch und wird unter Dateisperre vergeben, damit zwei gleichzeitige
Bestellungen nicht dieselbe Nummer bekommen. Die Datei nicht löschen — sonst
beginnt die Zählung von vorn und es gibt zwei Vorgänge mit derselben Nummer.

**Herkunft.** Nur `innofonds.m-vf.de` und `knowledge-hubs.m-vf.de`
dürfen senden; die Liste steht ausgeschrieben in `bestellung.php`. Eine neue
Portaladresse braucht dort einen Eintrag.

**Steuersatz.** Voreingestellt sind 19 %. Ob für eine elektronische
Publikation der ermäßigte Satz nach § 12 Abs. 2 Nr. 14 UStG gilt, ist eine
Frage an den Steuerberater; die Zahl steht deshalb in der Zugangsdatei.

**Gezahlt wird auf Rechnung.** Absichtlich kein Bezahldienst: Institute,
Kliniken und Kassen zahlen über Beschaffung und Bestellnummer. Ein
Bezahlknopf im Browser hilft ihnen nicht, er schließt sie aus.

## Dateien

| Datei | Zweck |
|---|---|
| `bestellung.php` | Endpunkt |
| `bestellung-zugang-muster.php` | Muster für die Konfiguration |
| `beispiel-auftragsbestaetigung.html` | so sieht die Mail aus |
| `daten/` | Vorgänge, Zähler, Taktbremse — nicht im Web lesbar |
