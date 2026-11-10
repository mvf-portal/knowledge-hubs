#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zieht genannte Newsletter-Entwuerfe auf einen bestimmten Titelkopf.

Fuer den Nachtrag von Hand gedacht, wenn Entwuerfe mit einem veralteten Kopf
stehengeblieben sind. Der Regelfall laeuft ueber newsletter_kopf.py.

WARUM MIT SICHERUNG UND ZWEITER MESSUNG
  Am 10.11.2026 meldete Mailchimp nach dem PUT beim sofortigen Lesen den neuen
  Kopf, und spaeter stand wieder der alte da. Ein PUT mit HTTP 200 und einem
  Gegenlesen in derselben Sekunde ist hier kein Nachweis. Deshalb: vorher
  sichern, setzen, und in einem ZWEITEN Lauf messen, was wirklich drinsteht.

    py titelkopf_ziehen.py 05-2026 <id> [<id> ...]            zeigt nur
    py titelkopf_ziehen.py 05-2026 <id> [<id> ...] --machen   setzt
"""

import datetime
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from newsletter_kopf import mc, titelkoepfe          # noqa: E402

SICHERUNG = pathlib.Path(__file__).resolve().parent / "sicherung"


def main() -> int:
    machen = "--machen" in sys.argv
    reste = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(reste) < 2:
        print(__doc__)
        return 2
    ausgabe, ids = reste[0], reste[1:]

    koepfe = titelkoepfe()
    name = f"NL_Header_{ausgabe}-620px.jpg"
    ziel = koepfe.get(name)
    if not ziel:
        print(f"Kein Titelkopf namens {name}. Vorhanden sind unter anderem:")
        for n in sorted(koepfe)[-6:]:
            print(f"   {n}")
        return 2
    print(f"Ziel: {name}\n")

    SICHERUNG.mkdir(exist_ok=True)
    stempel = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    andere = {a: n for n, a in koepfe.items() if a != ziel}

    geaendert = 0
    for kid in ids:
        c = mc(f"/campaigns/{kid}?fields=settings.title")
        titel = c.get("settings", {}).get("title", kid)
        html_text = mc(f"/campaigns/{kid}/content").get("html", "")
        if ziel in html_text:
            print(f"  {titel}: hat {name} schon.")
            continue
        treffer = [a for a in andere if a in html_text]
        if len(treffer) != 1:
            print(f"  {titel}: {len(treffer)} Titelkoepfe gefunden, erwartet 1 "
                  f"- nicht angefasst.")
            continue
        alt = andere[treffer[0]]
        if not machen:
            print(f"  {titel}: wuerde {alt} ersetzen.")
            geaendert += 1
            continue
        p = SICHERUNG / f"{kid}-vorher-{stempel}.html"
        p.write_text(html_text, encoding="utf-8")
        mc(f"/campaigns/{kid}/content", method="PUT",
           body={"html": html_text.replace(treffer[0], ziel)})
        print(f"  {titel}: {alt} ersetzt, Stand gesichert in {p.name}")
        geaendert += 1

    if not machen:
        print(f"\n{geaendert} Entwuerfe waeren zu aendern. Geschrieben wurde nichts.")
        return 0

    print(f"\n{geaendert} PUTs abgesetzt. JETZT die Gegenprobe - erneut gelesen:")
    offen = []
    for kid in ids:
        c = mc(f"/campaigns/{kid}?fields=settings.title")
        titel = c.get("settings", {}).get("title", kid)
        html_text = mc(f"/campaigns/{kid}/content").get("html", "")
        drin = [n for a, n in andere.items() if a in html_text]
        if ziel in html_text:
            print(f"  {titel}: {name} steht drin.")
        else:
            print(f"  {titel}: NICHT gesetzt, drin steht "
                  f"{', '.join(drin) or '(nichts erkannt)'}")
            offen.append(titel)
    if offen:
        print(f"\n{len(offen)} Entwuerfe haben den Kopf nicht uebernommen.")
        print("Das ist kein Netzfehler - Mailchimp rendert diese Kampagnen beim "
              "Lesen neu. Sie muessen in der Oberflaeche geaendert werden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
