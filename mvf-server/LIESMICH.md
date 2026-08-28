# Der Wecker auf dem MVF-Server

Ein PHP-Skript, das jeden Morgen einen einzigen Aufruf an GitHub schickt. Der
löst dort den Workflow „Dirigent" aus, und der stößt die zwölf Portale und den
Sammelbericht an.

Kein Node, kein wrangler, kein fremder Dienst — der Schlüssel bleibt auf Ihrem
Server.

## Warum es das gibt

GitHubs Cron ist ausdrücklich *best effort*. Am 24.08.2026 kam der nächtliche
Lauf zwei Stunden zu spät, am 26.08. wieder — und am **27. und 28.08. gar
nicht**, zwei Nächte hintereinander, in allen dreizehn Repositories. Kein
fehlgeschlagener Lauf, sondern gar keiner. Die **Ausführung** bei GitHub ist
verlässlich, die **Auslösung** nicht.

Die Aufgabenplanung auf dem Redaktionsrechner („MVF Laufwache") deckt das ab,
solange dieser Rechner läuft. Auf Reisen tut er das nicht. Der Server läuft
durch.

## Die Kette

```
MVF-Server (Cron)  --repository_dispatch-->  knowledge-hubs
                                                  │  Workflow "Dirigent"
                                                  └--workflow_dispatch--> 12 Portale
                                                                          └-> Sammelbericht
```

Zwei Schlüssel, klein geschnitten:

| Token | Rechte | gilt für | liegt |
|---|---|---|---|
| **Wecker** | Contents: Read and write | nur `mvf-portal/knowledge-hubs` | auf dem MVF-Server, in `wecker-zugang.php` |
| **Dirigent** | Actions: Read and write | die zwölf Portal-Repos | GitHub-Secret `DIRIGENT_TOKEN`, verlässt GitHub nie |

## Einrichten

### 1. Dateien hochladen

Per FTP nach `/wecker/` im Web-Verzeichnis (dieselbe Ebene wie `/zaehler/`):

* `wecker.php`
* `wecker-zugang.php` — aus `wecker-zugang-muster.php` erzeugt und ausgefüllt

**`wecker-zugang.php` muss `.php` heißen.** MVF läuft auf nginx, `.htaccess`
wird dort nicht gelesen; eine `.json` oder `.txt` wäre unter ihrer Adresse
abrufbar — mitsamt Token. Dieselbe Lehre wie beim Zähler.

### 2. Token eintragen

In `wecker-zugang.php` das fein granulierte GitHub-Token einsetzen
(Contents: *Read and write*, nur `knowledge-hubs`).

`schluessel` bleibt leer, wenn der Hoster Cron kann — dann ist der Aufruf über
das Netz gesperrt und das Skript nur von der Kommandozeile erreichbar.

### 3. Cron einrichten

Im Panel des Hosters ein täglicher Auftrag, 06:20 Uhr:

```
php /pfad/zum/webverzeichnis/wecker/wecker.php
```

Den genauen PHP-Pfad nennt das Panel; bei manchen Hostern heißt er
`/usr/bin/php8.2` oder ähnlich. Die Zeit ist bewusst gewählt: GitHub hätte bis
dahin seinen eigenen Zeitplan gehabt (03:03–03:47 UTC), und bis zum Versand um
10:00 bleiben über drei Stunden.

### 3b. Falls der Hoster keinen Cron kann

Dann `schluessel` in `wecker-zugang.php` auf 24 Zufallszeichen setzen und das
Skript von außen aufrufen lassen — etwa durch einen kostenlosen Ping-Dienst
oder einen anderen Rechner, der ohnehin läuft:

```
https://www.monitor-versorgungsforschung.de/wecker/wecker.php?schluessel=…
```

Ohne den richtigen Schlüssel antwortet das Skript mit 404 und tut nichts.

### 4. Prüfen

Auf der Kommandozeile des Servers:

```
php /pfad/.../wecker/wecker.php
```

Erwartet: `Weckruf abgesetzt.` — und danach läuft in knowledge-hubs der
Dirigent. Protokoll: `wecker.log` neben dem Skript, eine Zeile je Lauf.

Den Dirigenten allein prüfen, ganz ohne Server:

```
gh workflow run dirigent.yml -R mvf-portal/knowledge-hubs -f nur_studien=true
```

## Wenn etwas klemmt

| Bild | Ursache und Abhilfe |
|---|---|
| `GitHub antwortete 401` | Token falsch kopiert oder abgelaufen — neu erzeugen, in `wecker-zugang.php` eintragen. |
| `GitHub antwortete 404` | Das Token sieht das Repo nicht. Repository-Auswahl prüfen: `knowledge-hubs` ausgewählt, Contents auf *Read and write*. GitHub antwortet auf fehlende Rechte bewusst mit 404. |
| `GitHub antwortete 422` | `ereignis` passt nicht zu `types: [morgenlauf]` in `dirigent.yml`. |
| `Netzfehler: …` | Der Server darf nicht nach außen. Beim Hoster ausgehende HTTPS-Verbindungen freischalten lassen. |
| Dirigent läuft, Portale nicht | `DIRIGENT_TOKEN` fehlt oder hat kein *Actions: write*. Das Protokoll des Workflows nennt jedes Repo einzeln. |

## Im Betrieb

Doppelte Weckrufe kosten nichts: `update_studies.py` bricht ab, sobald für den
Tag Studien im Archiv stehen — ohne PubMed-Abruf, ohne Modellanfrage. Es ist
also gleichgültig, ob an einem Morgen GitHubs Cron, der Server und die
Laufwache alle drei anspringen.

Das Token hat ein Ablaufdatum. Der Ausfall wäre nicht still — er steht in
`wecker.log` und fällt spätestens in der 09-Uhr-Meldung der Laufwache auf —,
aber das Datum gehört trotzdem in den Kalender.
