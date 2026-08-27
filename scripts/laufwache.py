#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Taeglicher Blick um 09:00: Sind die naechtlichen Laeufe wirklich gelaufen?

Am 27.08.2026 hat GitHub die geplanten Laeufe ALLER dreizehn Repos nicht
gestartet - zeitgleich mit einer Stoerung der Billing-Dienste, waehrend die
Statusseite fuer Actions "operational" meldete. Manuelles Starten funktionierte
die ganze Zeit; nur der Scheduler schwieg. Es kam kein einziger Newsletter, und
gemerkt hat es niemand, weil ein AUSGEBLIEBENER Lauf nichts meldet: keine
fehlgeschlagene Aktion, keine Mail, kein Eintrag - nur Stille.

Diese Wache laeuft deshalb ausserhalb von GitHub, auf diesem Rechner. Sie sieht
nach, ob es fuer heute einen erfolgreichen Lauf gibt, stoesst fehlende an und
meldet sich per Outlook. Um 09:00 bleibt eine Stunde bis zum Versand um 10:00 -
genug fuer den Lauf (ein bis zwei Minuten) und fuer einen Blick von Hand.

Innerhalb von GitHub greift bereits ein zweiter Zeitplan um 05:30 UTC. Diese
Wache ist die Stufe darunter: Sie faengt den Fall, dass GitHub ueberhaupt keinen
Zeitplan ausfuehrt.

Aufruf:
    py scripts/laufwache.py                # pruefen, fehlende anstossen, melden
    py scripts/laufwache.py --trocken      # nur pruefen und berichten
    py scripts/laufwache.py --ohne-mail    # ohne Outlook, nur Protokoll
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TZ = ZoneInfo("Europe/Berlin")
WURZEL = pathlib.Path(__file__).resolve().parent.parent
PROTOKOLL = WURZEL / "laufwache.log"
MELDEADRESSE = "stegmaier@m-vf.de"

# Dieselbe Pflegestelle wie PORTALE in versand_bericht.py, studien_sammeln.py
# und abfrage_wache.py. Der Sammelbericht steht mit in der Liste: Faellt er aus,
# faellt die einzige taegliche Rueckmeldung ueber alle Hubs aus.
LAEUFE = [
    ("Versorgungsforschung", "mvf-portal/versorgungsforschung-portal", "update-studies.yml"),
    ("Hitze, Klima & Gesundheit", "mvf-portal/klima-gesundheit-portal", "update-studies.yml"),
    ("Digitalisierung, KI & Gesundheit", "mvf-portal/ki-gesundheit-portal", "update-studies.yml"),
    ("Pflege & Langzeitversorgung", "mvf-portal/pflege-portal", "update-studies.yml"),
    ("Gesundes Altern & Longevity", "mvf-portal/longevity-portal", "update-studies.yml"),
    ("Gesundheitskompetenz", "mvf-portal/healthliteracy-portal", "update-studies.yml"),
    ("Impfen & Impfpraevention", "mvf-portal/impfen-portal", "update-studies.yml"),
    ("Nicht uebertragbare Krankheiten", "mvf-portal/ncd-portal", "update-studies.yml"),
    ("Geschlechtersensible Medizin", "mvf-portal/gender-portal", "update-studies.yml"),
    ("Adipositas", "mvf-portal/adipositas-portal", "update-studies.yml"),
    ("Patientensicherheit", "mvf-portal/safety-portal", "update-studies.yml"),
    ("Psychische Gesundheit", "mvf-portal/mental-portal", "update-studies.yml"),
    ("Sammelbericht", "mvf-portal/knowledge-hubs", "versand-bericht.yml"),
]

GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def gh_ruf(*args: str) -> subprocess.CompletedProcess:
    """gh mit abgeschaltetem Pager - sonst wartet die Aufgabe auf eine Taste."""
    return subprocess.run([GH, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120,
                          env={**__import__("os").environ, "GH_PAGER": "cat", "PAGER": "cat"})


def laeufe_von_heute(repo: str, workflow: str, heute: str) -> list[dict]:
    """Die heutigen Laeufe dieses Workflows, neueste zuerst.

    Gefiltert wird in Python und nicht ueber --created: Die Suchsyntax von gh
    rechnet in UTC, und ein Lauf um 05:30 UTC gehoert zum deutschen Heute.
    """
    r = gh_ruf("run", "list", "-R", repo, "--workflow", workflow, "--limit", "20",
               "--json", "status,conclusion,createdAt,databaseId,event")
    if r.returncode != 0:
        raise RuntimeError(f"gh run list fehlgeschlagen: {r.stderr.strip()[:200]}")
    aus = []
    for j in json.loads(r.stdout or "[]"):
        wann = dt.datetime.fromisoformat(j["createdAt"].replace("Z", "+00:00")).astimezone(TZ)
        if wann.date().isoformat() == heute:
            aus.append({**j, "wann": wann})
    return aus


def anstossen(repo: str, workflow: str) -> str:
    r = gh_ruf("workflow", "run", workflow, "-R", repo)
    return "angestossen" if r.returncode == 0 else f"START FEHLGESCHLAGEN: {r.stderr.strip()[:120]}"


def melden(betreff: str, text: str) -> bool:
    """Meldung ueber das laufende Outlook - derselbe Weg wie bei den Pressemeldungen."""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = MELDEADRESSE
        mail.Subject = betreff
        mail.Body = text
        mail.Send()
        return True
    except Exception as e:  # noqa: BLE001 - eine fehlende Meldung darf den Lauf nicht kippen
        print(f"Outlook-Meldung nicht moeglich ({e})")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trocken", action="store_true", help="nichts anstossen, nur berichten")
    p.add_argument("--ohne-mail", action="store_true", help="keine Outlook-Meldung")
    a = p.parse_args()

    jetzt = dt.datetime.now(TZ)
    heute = jetzt.date().isoformat()
    zeilen, auffaellig = [], []

    for name, repo, workflow in LAEUFE:
        try:
            heutige = laeufe_von_heute(repo, workflow, heute)
        except Exception as e:  # noqa: BLE001
            zeilen.append(f"?  {name}: nicht abfragbar ({e})")
            auffaellig.append(name)
            continue
        erfolgreich = [j for j in heutige if j["conclusion"] == "success"]
        laufend = [j for j in heutige if j["status"] != "completed"]
        if erfolgreich:
            zeilen.append(f"OK {name}: {erfolgreich[0]['wann']:%H:%M} Uhr gelaufen.")
        elif laufend:
            zeilen.append(f"…  {name}: laeuft gerade ({laufend[0]['wann']:%H:%M} Uhr).")
        else:
            grund = "fehlgeschlagen" if heutige else "KEIN Lauf heute"
            tat = "nicht angestossen (--trocken)" if a.trocken else anstossen(repo, workflow)
            zeilen.append(f"!! {name}: {grund} - {tat}")
            auffaellig.append(name)

    kopf = f"Laufwache {jetzt:%d.%m.%Y %H:%M}"
    text = kopf + "\n" + "\n".join(zeilen)
    print(text)
    with open(PROTOKOLL, "a", encoding="utf-8") as f:
        f.write(text + "\n\n")

    if auffaellig and not a.ohne_mail:
        melden(f"Knowledge-Hubs: {len(auffaellig)} Lauf/Laeufe fehlten heute früh",
               text + "\n\nDie fehlenden Läufe sind angestoßen worden, sofern GitHub "
                      "erreichbar war. Bis zum Versand um 10:00 Uhr bleibt Zeit, das "
                      "Ergebnis anzusehen:\nhttps://github.com/mvf-portal\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
