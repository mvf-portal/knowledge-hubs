#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Woechentlicher Blick auf die zwoelf PubMed-Abfragen: Bricht eine ein?

Die taegliche Ausgabe kann aus zwei Gruenden duenn werden. Der eine ist
harmlos - ein ruhiger Tag in PubMed. Der andere ist es nicht: Eine Abfrage
liefert plotzlich weniger, weil ein MeSH-Begriff umbenannt oder abgeschafft
wurde, weil ein Tippfehler eingebaut wurde oder weil ein NOT-Block zu weit
greift. Der erste Fall gleicht sich in Tagen aus, der zweite nie.

Der Unterschied zeigt sich nur im Vergleich ueber Wochen. Dieses Skript
zaehlt deshalb jede Abfrage ueber die letzten 365 Tage, schreibt das Ergebnis
nach `abfrage-stand.json` und meldet, wenn ein Hub gegenueber dem letzten
Stand deutlich verliert.

**Die Abfrage wird dort gelesen, wo sie taeglich laeuft**: in der
`scripts/thema.py` des jeweiligen Portals, direkt von GitHub. Nicht in den
Themenprofilen der Vorlage - die erzeugen ein Portal einmal, weiterentwickelt
wird danach in thema.py.

Aufruf:
    python scripts/abfrage_wache.py            # zaehlen, vergleichen, Stand fortschreiben
    python scripts/abfrage_wache.py --trocken  # nur zaehlen und melden
    python scripts/abfrage_wache.py --schwelle 30   # ab wie viel Prozent Verlust gewarnt wird
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIER = pathlib.Path(__file__).resolve().parent.parent
STAND = HIER / "abfrage-stand.json"
ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ROH_THEMA = "https://raw.githubusercontent.com/{repo}/main/scripts/thema.py"
BERICHT_REPO = "mvf-portal/knowledge-hubs"

# Dieselbe Pflegestelle wie PORTALE in versand_bericht.py und studien_sammeln.py.
PORTALE = [
    # erzeugt aus portale.json von portale_pflegen.py - nicht von Hand aendern
    ("Versorgungsforschung", "mvf-portal/versorgungsforschung-portal"),
    ("Hitze, Klima & Gesundheit", "mvf-portal/klima-gesundheit-portal"),
    ("Digitalisierung, KI & Gesundheit", "mvf-portal/ki-gesundheit-portal"),
    ("Pflege & Langzeitversorgung", "mvf-portal/pflege-portal"),
    ("Gesundes Altern & Longevity", "mvf-portal/longevity-portal"),
    ("Gesundheitskompetenz", "mvf-portal/healthliteracy-portal"),
    ("Impfen & Impfprävention", "mvf-portal/impfen-portal"),
    ("Nicht übertragbare Krankheiten", "mvf-portal/ncd-portal"),
    ("Geschlechtersensible Medizin", "mvf-portal/gender-portal"),
    ("Adipositas", "mvf-portal/adipositas-portal"),
    ("Patientensicherheit", "mvf-portal/safety-portal"),
    ("Psychische Gesundheit", "mvf-portal/mental-portal"),
]


def abfrage(repo: str) -> str | None:
    """TERM aus der thema.py des Portals - ausgefuehrt, nicht per Regex geschnitten.

    thema.py ist eine reine Datei mit Zuweisungen und importiert nur `os`.
    Sie auszufuehren ist ehrlicher als der Versuch, eine ueber zwanzig Zeilen
    verteilte Zeichenkette mit einem Muster herauszuloesen.
    """
    try:
        req = urllib.request.Request(ROH_THEMA.format(repo=repo),
                                     headers={"User-Agent": "mvf-abfragewache"})
        with urllib.request.urlopen(req, timeout=30) as r:
            quelle = r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"  thema.py nicht erreichbar ({e})")
        return None
    raum: dict = {}
    try:
        exec(compile(quelle, f"{repo}/thema.py", "exec"), raum)  # noqa: S102
    except Exception as e:  # noqa: BLE001
        print(f"  thema.py nicht ausfuehrbar ({e})")
        return None
    return raum.get("TERM")


def zaehle(term: str, tage: int = 365) -> int | None:
    """POST, nicht GET - eine lange Abfrage sprengt sonst die Adresse (HTTP 414)."""
    p = {"db": "pubmed", "term": term, "rettype": "count", "datetype": "pdat",
         "reldate": str(tage), "tool": "mvf-abfragewache", "email": "stegmaier@m-vf.de"}
    daten = urllib.parse.urlencode(p).encode()
    for versuch in range(4):
        try:
            with urllib.request.urlopen(ESEARCH, data=daten, timeout=60) as r:
                return int(ET.fromstring(r.read()).findtext("Count") or 0)
        except Exception as e:  # noqa: BLE001
            if versuch == 3:
                print(f"  PubMed nicht erreichbar ({e})")
                return None
            time.sleep(3 * (versuch + 1))
    return None


def lade_stand() -> dict:
    try:
        return json.loads(STAND.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"_": ("Trefferzahl jeder Hub-Abfrage ueber die letzten 365 Tage, "
                      "woechentlich von abfrage_wache.py fortgeschrieben."),
                "hubs": {}}


def issue(titel: str, text: str) -> None:
    """Meldung als GitHub-Issue. Ohne Token wird sie nur gedruckt."""
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print("\n(kein Token - die Meldung wird nur angezeigt)\n" + text)
        return
    subprocess.run(["gh", "issue", "create", "-R", BERICHT_REPO,
                    "-t", titel, "-b", text], check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trocken", action="store_true", help="Stand nicht fortschreiben")
    ap.add_argument("--schwelle", type=int, default=25,
                    help="Verlust in Prozent, ab dem gewarnt wird (Standard 25)")
    a = ap.parse_args()

    stand = lade_stand()
    heute = dt.date.today().isoformat()
    zeilen, warnungen = [], []

    for name, repo in PORTALE:
        print(f"{name} ...")
        term = abfrage(repo)
        n = zaehle(term) if term else None
        if n is None:
            zeilen.append(f"- ❓ **{name}** — nicht messbar (siehe Lauf-Protokoll).")
            warnungen.append(name)
            continue
        vorher = stand["hubs"].get(repo, {})
        alt = vorher.get("treffer")
        pro_tag = n / 365
        if alt:
            diff = (n - alt) / alt * 100
            pfeil = "▲" if diff > 0 else ("▼" if diff < 0 else "—")
            zusatz = f" ({pfeil} {abs(diff):.1f} % gegenüber {vorher.get('datum')})"
            if diff <= -a.schwelle:
                zeilen.append(f"- ⚠️ **{name}** — {n} Arbeiten, {pro_tag:.1f} pro Tag{zusatz}. "
                              f"**Das ist ein Einbruch.** Abfrage nachsehen: "
                              f"`scripts/thema.py` in `{repo}`.")
                warnungen.append(name)
                continue
        else:
            zusatz = " (erster Stand)"
        zeilen.append(f"- **{name}** — {n} Arbeiten, {pro_tag:.1f} pro Tag{zusatz}.")
        stand["hubs"][repo] = {"datum": heute, "treffer": n, "pro_tag": round(pro_tag, 1)}
        time.sleep(0.5)

    kopf = (f"Wöchentlicher Stand der zwölf Hub-Abfragen, gemessen am "
            f"{dt.date.fromisoformat(heute).strftime('%d.%m.%Y')} über die letzten "
            f"365 Tage.\n\n")
    fuss = ("\n\nGezählt wird die Abfrage, die täglich läuft (`scripts/thema.py` des "
            "Portals), nicht das Themenprofil. Ein Rückgang von einigen Prozent ist "
            "normal — PubMed indexiert nach. Ein Einbruch ist es, wenn ein MeSH-Begriff "
            "umbenannt oder abgeschafft wurde; dann liefert die Abfrage dauerhaft "
            "weniger, und das gleicht sich nie wieder aus.")
    text = kopf + "\n".join(zeilen) + fuss
    print("\n" + text)

    if not a.trocken:
        STAND.write_text(json.dumps(stand, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
        print(f"\n{STAND.name} fortgeschrieben.")
    if warnungen:
        issue(f"Abfrage-Wache: {len(warnungen)} Hub(s) auffällig", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
