#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sammelt die Studien aller Hubs der letzten Tage in eine Datei.

Wer wissen will, was in der ganzen Reihe passiert ist, muesste sonst acht
Seiten oeffnen. Dieses Skript holt die Archive aller Portale, schneidet die
letzten TAGE heraus und schreibt sie als `studien.json` in dieses Repo. Die
Uebersichtsseite laedt sie von dort - gleiche Herkunft, ein Abruf.

**Warum nicht einfach im Browser alle acht Archive laden?** Das ginge heute:
GitHub Pages liefert sie mit `Access-Control-Allow-Origin: *` aus, zusammen
sind es 114 KB. Aber acht Hubs zu je rund sechs Studien am Tag sind 17.500
Studien im Jahr, gut 17 MB - der naive Weg waere in zwoelf Monaten unzumutbar.
Die Sammeldatei bleibt dagegen gleich gross, weil sie nur ein Fenster zeigt.

Das Vollarchiv bleibt, wo es hingehoert: im jeweiligen Hub, wo der
`<details>`-Ordner es ohnehin nachlaedt.

Aufruf:
    python scripts/studien_sammeln.py            # schreibt studien.json
    python scripts/studien_sammeln.py --tage 30
    python scripts/studien_sammeln.py --trocken  # nur zaehlen, nichts schreiben
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Dieselbe Pflegestelle wie PORTALE in versand_bericht.py. Kommt ein Hub hinzu,
# gehoert er in beide Listen - sonst faellt er hier still heraus.
#
# Die Reihenfolge ist die Reihenfolge der Karten auf der Uebersichtsseite und
# deshalb alphabetisch nach dem sichtbaren Namen. Sie folgt bewusst NICHT der
# Kachelreihenfolge weiter oben (REIHENFOLGE in vorschaltseite.py): Die Kacheln
# sind gestaltet, diese Liste soll auffindbar sein. Wer einen Hub ergaenzt,
# setzt ihn an die alphabetisch richtige Stelle.
PORTALE = [
    ("Adipositas", "adipositas.m-vf.de", "mvf-portal/adipositas-portal"),
    ("Digitalisierung, KI & Gesundheit", "ki.m-vf.de", "mvf-portal/ki-gesundheit-portal"),
    ("Geschlechtersensible Medizin", "gender.m-vf.de", "mvf-portal/gender-portal"),
    ("Gesundes Altern & Longevity", "longevity.m-vf.de", "mvf-portal/longevity-portal"),
    ("Gesundheitskompetenz", "healthliteracy.m-vf.de", "mvf-portal/healthliteracy-portal"),
    ("Hitze, Klima & Gesundheit", "klima.m-vf.de", "mvf-portal/klima-gesundheit-portal"),
    ("Impfen & Impfprävention", "impfen.m-vf.de", "mvf-portal/impfen-portal"),
    ("Nicht übertragbare Krankheiten", "ncd.m-vf.de", "mvf-portal/ncd-portal"),
    ("Patientensicherheit", "safety.m-vf.de", "mvf-portal/safety-portal"),
    ("Pflege & Langzeitversorgung", "pflege.m-vf.de", "mvf-portal/pflege-portal"),
    ("Psychische Gesundheit", "mental.m-vf.de", "mvf-portal/mental-portal"),
    ("Versorgungsforschung", "wissen.m-vf.de", "mvf-portal/versorgungsforschung-portal"),
]
ROH = "https://raw.githubusercontent.com/{repo}/main/studien-archiv.json"
TAGE = 14

# Die Felder, die in die Sammeldatei wandern. Bewusst nicht alle: Je Studie
# zaehlt hier jedes Byte, weil 14 Tage mal acht Hubs schnell 600 Kilobyte sind.
FELDER = ("pmid", "journal", "year", "author", "pubdate", "title", "sum", "result",
          "transfer", "aufgenommen")


def hole(repo: str) -> list[dict]:
    """Das Archiv eines Portals - leere Liste, wenn es keines gibt."""
    req = urllib.request.Request(ROH.format(repo=repo),
                                 headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            daten = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    if isinstance(daten, dict):
        daten = daten.get("studien") or daten.get("eintraege") or []
    return daten


def main() -> int:
    p = argparse.ArgumentParser(description="Studien aller Hubs einsammeln")
    p.add_argument("--tage", type=int, default=TAGE)
    p.add_argument("--datei", default="studien.json")
    p.add_argument("--trocken", action="store_true")
    a = p.parse_args()

    grenze = (dt.date.today() - dt.timedelta(days=a.tage - 1)).isoformat()
    alle: list[dict] = []
    je_hub: dict[str, int] = {}

    for name, domain, repo in PORTALE:
        archiv = hole(repo)
        neu = [e for e in archiv if (e.get("aufgenommen") or "") >= grenze]
        for e in neu:
            eintrag = {k: e[k] for k in FELDER if e.get(k)}
            eintrag["hub"] = name
            eintrag["domain"] = domain
            alle.append(eintrag)
        je_hub[name] = len(neu)
        print(f"  {domain:<24} {len(neu):>4} von {len(archiv):>5} Studien im Fenster")

    # Neueste zuerst; bei gleichem Tag nach Hub, damit die Reihenfolge stabil
    # bleibt und die Datei sich nicht ohne inhaltlichen Grund aendert.
    alle.sort(key=lambda e: (e.get("aufgenommen", ""), e.get("hub", ""),
                             e.get("pmid", "")), reverse=True)

    tage = sorted({e.get("aufgenommen", "") for e in alle}, reverse=True)
    ergebnis = {
        "stand": grenze,
        "fenster_tage": a.tage,
        "erzeugt": dt.date.today().isoformat(),
        "hubs": [{"name": n, "domain": d, "anzahl": je_hub.get(n, 0)}
                 for n, d, _ in PORTALE],
        "tage": tage,
        "studien": alle,
    }

    print(f"\n{len(alle)} Studien aus {len(tage)} Tagen, {len(PORTALE)} Hubs.")
    if a.trocken:
        print("Trockenlauf - nichts geschrieben.")
        return 0

    ziel = pathlib.Path(a.datei)
    ziel.write_text(json.dumps(ergebnis, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"{ziel} geschrieben: {ziel.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
