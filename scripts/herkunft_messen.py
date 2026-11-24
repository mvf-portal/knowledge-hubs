#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Messt fuer JEDEN Hub, ob der Anmelde-Endpunkt seine Herkunft freigibt.

    py scripts/herkunft_messen.py
    py scripts/herkunft_messen.py --gegenprobe

WARUM
-----
Am 23.11.2026 im Browser gemessen: Auf ACHT von zwanzig Hubs war das
Anmeldeformular tot. Der Grund stand in `mvf-server/anmeldung/anmeldung.php`
in der Liste HERKUNFT_ERLAUBT - acht Hubs fehlten darin, weil sie nach der
Lieferung vom 13.11.2026 dazukamen.

DIE STELLE, AN DER ES LAUTLOS VERSAGT, ist der Vorabflug des Browsers. Ohne
Freigabe im Kopf schickt er die eigentliche Anfrage nie ab. Auf dem Server
kommt also NICHTS an: kein Fehler im Protokoll, kein Eintrag in Mailchimp,
keine Meldung irgendwo. Von innen ist dieser Zustand nicht zu sehen, nur von
aussen und nur je Herkunft einzeln.

Deshalb fragt diese Probe nicht die Datei, sondern den LAUFENDEN Endpunkt, und
zwar mit genau dem Vorabflug, den der Browser schickt.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

ENDPUNKT = "https://www.monitor-versorgungsforschung.de/anmeldung/anmeldung.php"
HIER = pathlib.Path(__file__).resolve().parent
PORTALE = HIER.parent.parent / "portal-vorlage" / "portale.json"

# Ohne Browserkennung antwortet der Server mit 403, und zwar auf JEDE
# Herkunft. Eine Probe ohne diese Zeile meldet alle zwanzig Hubs als tot,
# auch die zwoelf, die nachweislich gehen. Gemessen am 24.11.2026.
KENNUNG = "Mozilla/5.0 (kompatibel) MVF-Hub-Probe"

# Den Vorabflug beantwortet der Endpunkt mit 204. Jede andere Lage ist KEIN
# Befund ueber die Herkunft, sondern eine nicht zustande gekommene Messung.
ERWARTET = 204


def herkuenfte() -> list[str]:
    d = json.loads(PORTALE.read_text(encoding="utf-8"))
    ps = d["portale"] if isinstance(d, dict) else d
    return ["https://knowledge-hubs.m-vf.de"] + [f"https://{p['domain']}" for p in ps]


def freigegeben(herkunft: str):
    """True freigegeben, False gesperrt, None nicht gemessen."""
    anfrage = urllib.request.Request(ENDPUNKT, method="OPTIONS")
    anfrage.add_header("Origin", herkunft)
    anfrage.add_header("Access-Control-Request-Method", "POST")
    anfrage.add_header("User-Agent", KENNUNG)
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            lage = antwort.status
            kopf = antwort.headers.get("Access-Control-Allow-Origin") or ""
    except urllib.error.HTTPError as fehler:
        lage = fehler.code
        kopf = fehler.headers.get("Access-Control-Allow-Origin") or ""
    except Exception as fehler:                    # Netz, Namensaufloesung
        return None, f"nicht erreichbar: {fehler}"
    wie = f"{lage} {kopf or 'kein Kopf'}"
    if lage != ERWARTET:
        return None, wie
    return kopf == herkunft, wie


def urteil(ok) -> str:
    return "UNKLAR" if ok is None else ("OK " if ok else "TOT")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--gegenprobe", action="store_true",
                   help="fragt Herkuenfte, die NIE freigegeben sein duerfen")
    a = p.parse_args()

    if a.gegenprobe:
        # Misst die Probe ueberhaupt? Eine fremde Herkunft muss durchfallen,
        # UND die Messung muss zustande kommen. Ohne die zweite Haelfte
        # bestuende die Gegenprobe auch dann, wenn der Endpunkt gar nicht
        # antwortet - genau der Fall vom 24.11.2026, in dem die erste Fassung
        # dieser Probe alle Hubs als tot meldete und sich selbst bestaetigte.
        schlecht = 0
        for fremd in ["https://beispiel.de", "https://wissen.m-vf.de.beispiel.de"]:
            ok, wie = freigegeben(fremd)
            print(f"  {'FEHLER' if ok is not False else 'OK '} "
                  f"{fremd:<40}{wie}")
            schlecht += 1 if ok is not False else 0
        print(f"\n{schlecht} Abweichung(en).")
        return 1 if schlecht else 0

    offen, tot, unklar = [], [], []
    for h in herkuenfte():
        ok, wie = freigegeben(h)
        (unklar if ok is None else offen if ok else tot).append(h)
        print(f"  {urteil(ok)} {h:<40}{wie}")

    print(f"\n{len(offen)} freigegeben, {len(tot)} tot, "
          f"{len(unklar)} nicht gemessen.")
    if unklar:
        print(f"Nicht gemessen heisst nicht frei: erwartet war {ERWARTET}. "
              "Erst die Messung in Ordnung bringen, dann urteilen.")
    if tot:
        print("Tot heisst: Das Anmeldeformular dort schickt nichts ab.")
        print("Nachtragen in mvf-server/anmeldung/anmeldung.php, "
              "HERKUNFT_ERLAUBT, und an Levan liefern.")
    return 1 if (tot or unklar) else 0


if __name__ == "__main__":
    sys.exit(main())
