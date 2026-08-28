# Der Wecker: ein Weckruf von außen, dreizehn Läufe

## Warum es das gibt

GitHubs Cron ist ausdrücklich *best effort*. Am 24.08.2026 kam der nächtliche
Lauf zwei Stunden zu spät, am 26.08. wieder — und am **27. und 28.08. gar
nicht**, zwei Nächte hintereinander, in allen dreizehn Repos. Kein
fehlgeschlagener Lauf, sondern gar keiner: Die Workflows waren aktiv, die
Dateien gültig, GitHub meldete „All Systems Operational", und jeder Start von
Hand lief sofort.

Die **Ausführung** bei GitHub ist also verlässlich, die **Auslösung** nicht.
Genau dort setzt der Wecker an.

Die Aufgabenplanung auf dem Redaktionsrechner („MVF Laufwache", 06:00 und
09:00) tut dasselbe — aber nur, solange der Rechner läuft. Auf Reisen tut er
das nicht. Der Wecker bei Cloudflare läuft immer.

## Die Kette

```
Cloudflare-Cron  --repository_dispatch-->  knowledge-hubs
                                                │  Workflow "Dirigent"
                                                └--workflow_dispatch--> 12 Portale
                                                                        └-> Sammelbericht
```

## Ein Token für beide Stellen

Entschieden am 28.08.2026: **ein** fein granuliertes Token, das an beiden
Stellen liegt.

| | |
|---|---|
| **Repository access** | alle **dreizehn**: die zwölf Portale **und** `knowledge-hubs` |
| **Contents** | Read and write — für `repository_dispatch` in knowledge-hubs |
| **Actions** | Read and write — zum Starten der Workflows in den zwölf Portalen |
| **Liegt** | als Worker-Secret `GITHUB_TOKEN` **und** als GitHub-Secret `DIRIGENT_TOKEN` |

Beide Berechtigungen sind nötig, weil es zwei verschiedene Aufrufe sind:
`repository_dispatch` verlangt **Contents**, `workflow_dispatch` verlangt
**Actions**. Fehlt eine, bricht die Kette an genau der Stelle ab — und GitHub
antwortet auf fehlende Rechte mit **403** oder **404**, nicht mit einer
sprechenden Meldung.

Der Preis gegenüber zwei getrennten Token: Das Token auf dem Webserver kann
mehr, als es dort bräuchte — es könnte in allen zwölf Portalen Läufe starten.
Wer das später enger ziehen will, legt ein zweites Token an (Contents: Read and
write, nur `knowledge-hubs`), trägt es in `wecker-zugang.php` ein und nimmt dem
ersten die Contents-Berechtigung. Das ist eine Minute Arbeit und ändert an der
Kette nichts.

## Einrichten

### 1. Beide Token anlegen (nur Sie, nicht Claude)

GitHub → Settings → Developer settings → **Fine-grained personal access tokens**

* **Wecker-Token**: Repository access nur `mvf-portal/knowledge-hubs`,
  Permission **Contents: Read and write**. Ablaufdatum setzen (ein Jahr).
* **Dirigent-Token**: Repository access die zwölf Portal-Repos,
  Permission **Actions: Read and write**.

Das Dirigent-Token in knowledge-hubs hinterlegen:
Settings → Secrets and variables → Actions → New repository secret,
Name **`DIRIGENT_TOKEN`**.

### 2. Worker veröffentlichen

```
npm install -g wrangler
cd cloudflare
wrangler login
wrangler secret put GITHUB_TOKEN        # das Wecker-Token
wrangler secret put PROBE_GEHEIMNIS     # frei gewählt, für den Aufruf von Hand
wrangler deploy
```

### 3. Prüfen, ohne auf den Morgen zu warten

```
curl "https://mvf-hubs-wecker.<konto>.workers.dev/?probe=<PROBE_GEHEIMNIS>"
```

Erwartet: `Weckruf abgesetzt.` — danach läuft in knowledge-hubs der Dirigent,
und in den zwölf Portalen startet „Studien-Update". Ohne das Geheimnis
antwortet der Worker mit 404; sonst könnte jeder, der die Adresse kennt,
dreizehn Läufe auslösen.

Den Dirigenten allein prüfen, ganz ohne Cloudflare:

```
gh workflow run dirigent.yml -R mvf-portal/knowledge-hubs -f nur_studien=true
```

## Zeiten

| | |
|---|---|
| GitHub-Cron je Portal | 03:03 bis 03:47 UTC, zweiter Versuch 05:03 bis 05:47 |
| **Cloudflare-Wecker** | **04:20 UTC** (06:20 Ortszeit im Sommer) |
| Laufwache auf dem Rechner | 06:00 und 09:00 Ortszeit |
| Versand | 10:00 Ortszeit |

Vier Ebenen, die einander nicht brauchen. Doppelte Läufe kosten nichts:
`update_studies.py` bricht ab, sobald für heute Studien im Archiv stehen.

## Wenn das Token abläuft

Fein granulierte Token laufen ab — das ist ihr Zweck. Merken lässt sich das
schwer, deshalb: Der Wecker meldet einen Fehlschlag im Cloudflare-Log
(`wrangler tail`), und spätestens fällt es in der 09-Uhr-Meldung der Laufwache
auf, weil dann kein Lauf vorliegt. Ein abgelaufenes Token ist also kein
stiller Ausfall — aber ein vermeidbarer: Ablaufdatum in den Kalender.
