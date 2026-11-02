#!/usr/bin/env python3
"""Studie des Tages fuer die neue MVF-Startseite (goldenes Feld).

Liest das Studienarchiv des Knowledge-Hubs Versorgungsforschung, nimmt die
Studien des juengsten Aufnahmetags und waehlt daraus EINE: die, deren
Systemkontext am naechsten am deutschen liegt. Schreibt

    mvf-startseite/studie-des-tages.json
    mvf-startseite/hub-logo.png          (Logo des Hubs, im JSON verlinkt)

Abrufbar unter https://knowledge-hubs.m-vf.de/mvf-startseite/... - GitHub
Pages liefert mit `Access-Control-Allow-Origin: *`, die Startseite von m-vf.de
darf die Datei also auch per JavaScript holen.

WIE GEWAEHLT WIRD
-----------------
Kein Sprachmodell. Jede Studie traegt im Archiv das Feld `transfer`, einen
Halbsatz, den die taegliche Auswahl schreibt: Land bzw. Datengrundlage und
warum das Ergebnis fuer Deutschland taugt. Das Skript liest daraus nur, WELCHES
LAND VORN steht, und ordnet nach den Stufen, die auch der Auswahl-Prompt des
Hubs nennt (scripts/thema.py im versorgungsforschung-portal):

    1  Deutschland, Oesterreich, Schweiz
    2  Niederlande, Belgien, Frankreich, Luxemburg
    3  Skandinavien, Grossbritannien, uebriges Europa, Kanada, Australien
    4  alles andere
    +1 Stufe schlechter, wenn der Halbsatz "nur bedingt" oder "begrenzt" sagt

Bei gleicher Stufe gewinnt "direkt uebertragbar", danach die hoehere PMID
(die juengere Studie). Die Wertung stammt damit aus dem Hub selbst, nicht aus
diesem Skript; hier wird nur sortiert.

Nur das ERSTE Glied des Halbsatzes zaehlt (bis zum ersten Komma, Semikolon,
Doppelpunkt oder Gedankenstrich). Sonst gewaenne "Iran, Sozialversicherungs-
system aehnlich deutschem" gegen eine niederlaendische Studie, nur weil das
Wort "deutsch" darin vorkommt.

Hat der Hub heute nichts aufgenommen (Lauf ausgefallen), bleibt die Studie des
letzten Aufnahmetags stehen; `aufgenommen` im JSON sagt, von wann sie ist.

Nur Standardbibliothek.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.request

HUB = "https://wissen.m-vf.de"
ARCHIV_URL = f"{HUB}/studien-archiv.json"
LOGO_URL = f"{HUB}/logo/hub-icon-512.png"
ZIEL_URL = "https://knowledge-hubs.m-vf.de/mvf-startseite"

ORDNER = pathlib.Path(__file__).resolve().parent.parent / "mvf-startseite"
JSON_DATEI = ORDNER / "studie-des-tages.json"
LOGO_DATEI = ORDNER / "hub-logo.png"

STUFEN = [
    (1, r"deutsch|österreich|schweiz|dach"),
    (2, r"niederl|belgi|frankreich|französ|luxemburg"),
    (3, r"dän|schwed|norw|finn|skandinav|nordeuropa|großbritann|vereinigtes königreich|"
        r"\buk\b|nhs|engl|schott|irland|italien|spanien|portugal|europ|kanad|australi|neuseeland"),
]
EINSCHRAENKUNG = re.compile(r"nur bedingt|begrenzt", re.I)
DIREKT = re.compile(r"direkt (übertragbar|anwendbar|relevant|für)", re.I)


def holen(url: str) -> bytes:
    anfrage = urllib.request.Request(url, headers={"User-Agent": "knowledge-hubs/studie-des-tages"})
    with urllib.request.urlopen(anfrage, timeout=60) as antwort:
        return antwort.read()


def stufe(transfer: str) -> int:
    erstes = re.split(r"[,;:–—]| - ", transfer, maxsplit=1)[0].lower()
    s = next((n for n, muster in STUFEN if re.search(muster, erstes)), 4)
    if EINSCHRAENKUNG.search(transfer):
        s += 1
    return s


def auswaehlen(archiv: list[dict]) -> dict:
    kandidaten = [e for e in archiv if e.get("transfer") and not e.get("nachtrag")]
    if not kandidaten:
        raise SystemExit("Archiv enthaelt keine Studie mit Transfer-Angabe.")
    tag = max(e["aufgenommen"] for e in kandidaten)
    heute = [e for e in kandidaten if e["aufgenommen"] == tag]
    heute.sort(key=lambda e: (stufe(e["transfer"]),
                              0 if DIREKT.search(e["transfer"]) else 1,
                              -int(e["pmid"])))
    return heute[0]


def main() -> int:
    archiv = json.loads(holen(ARCHIV_URL))
    s = auswaehlen(archiv)

    ORDNER.mkdir(exist_ok=True)
    logo = holen(LOGO_URL)
    if not LOGO_DATEI.exists() or LOGO_DATEI.read_bytes() != logo:
        LOGO_DATEI.write_bytes(logo)

    daten = {
        "rubrik": "Studie des Tages",
        "aufgenommen": s["aufgenommen"],
        "portal": {
            "name": "Knowledge-Hub Versorgungsforschung",
            "url": f"{HUB}/",
            "logo": f"{ZIEL_URL}/{LOGO_DATEI.name}",
            "logo_alt": "Logo der Knowledge-Hubs von Monitor Versorgungsforschung",
        },
        "studie": {
            "titel": s["title"],
            "worum_es_geht": s["sum"],
            "ergebnis": s["result"],
            "uebertragbarkeit": s["transfer"],
            "autoren": s.get("author", ""),
            "zeitschrift": s["journal"],
            "jahr": s["year"],
            "pmid": s["pmid"],
            "pubmed": f"https://pubmed.ncbi.nlm.nih.gov/{s['pmid']}/",
            "im_hub": f"{HUB}/neue-studien.html#studie-{s['pmid']}",
        },
        "knopf": {"text": "Zur Studie", "url": f"{HUB}/neue-studien.html#studie-{s['pmid']}"},
    }
    neu = json.dumps(daten, ensure_ascii=False, indent=1) + "\n"
    # Kein Zeitstempel der Systemuhr: Unveraenderter Inhalt soll keinen Commit
    # und keinen Pages-Build ausloesen.
    if not JSON_DATEI.exists() or JSON_DATEI.read_text(encoding="utf-8") != neu:
        JSON_DATEI.write_text(neu, encoding="utf-8", newline="\n")
        print(f"Neu: PMID {s['pmid']} (Stufe {stufe(s['transfer'])}) - {s['title']}")
    else:
        print(f"Unveraendert: PMID {s['pmid']}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
