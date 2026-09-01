#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Liest die Mailchimp-Gruppen aus und gibt die Tabelle INTERESSEN fertig aus.

    set MAILCHIMP_API_KEY=xxxxxxxxxxxxxxxx-us6
    py scripts/anmeldung_gruppen.py

Das Skript LIEST nur. Es aendert in Mailchimp nichts.

WOZU
----
`mvf-server/anmeldung/anmeldung.php` traegt Newsletter ueber die Mailchimp-API
ein. Die API kennt Gruppen aber nicht unter den Nummern des alten Formulars
(`group[16135][512]`), sondern unter einer eigenen Kennung wie `a1b2c3d4e5` -
und **die steht nirgends in der Mailchimp-Oberflaeche.** Sie ist nur ueber die
API zu bekommen. Genau das tut dieses Skript.

Ausgegeben werden zwei Dinge:

1. die vollstaendige Liste aller Kategorien und Gruppen mit Kennung,
2. ein Vorschlag fuer den Block `INTERESSEN` aus `anmeldung-zugang.php`,
   fertig zum Hineinkopieren.

Der Vorschlag ist ein **Vorschlag**: Zugeordnet wird ueber Stichworte im
Gruppennamen. Wo das Skript nicht eindeutig zuordnen kann, bleibt die Zeile
leer und traegt einen Hinweis - lieber eine Luecke, die auffaellt, als eine
falsche Kennung, die still den falschen Newsletter bestellt. Die Liste unter
Punkt 1 steht daneben, um solche Zeilen von Hand zu fuellen.

Braucht nichts ausser der Standardbibliothek.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

# Kurzname -> Stichworte, die im Gruppennamen vorkommen muessen. Alle Stichworte
# einer Zeile muessen passen; das Kuerzel wird als ganzes Wort gesucht, damit
# "vf" nicht in "MVF" trifft.
HINWEISE: dict[str, tuple[str, ...]] = {
    "wissen":         ("studien", "vf"),
    "klima":          ("studien", "klima"),
    "ki":             ("studien", "ki"),
    "pflege":         ("studien", "pflege"),
    "longevity":      ("studien", "longevity"),
    "healthliteracy": ("studien", "healthliteracy"),
    "impfen":         ("studien", "impfen"),
    "ncd":            ("studien", "ncd"),
    "gender":         ("studien", "gender"),
    "adipositas":     ("studien", "adipositas"),
    "safety":         ("studien", "safety"),
    "mental":         ("studien", "mentalhealth"),
    # Der redaktionelle MVF-Newsletter. "newsletter" allein genuegt nicht:
    # In der Gruppenmenge 5629 stehen die Newsletter alter Titel daneben
    # (Pharma Relations, MarketAccess, Monitor Pflege) - Relikte, die es nicht
    # mehr gibt, die aber genauso heissen.
    "mvf":            ("monitor", "versorgungsforschung", "newsletter"),
    "datenschutz":    ("datenschutz",),
}
# Zeilen, bei denen ein Stichwort NICHT vorkommen darf.
VERBOTEN: dict[str, tuple[str, ...]] = {
    "mvf": ("studien", "einladung"),
}

ERLAEUTERUNG = {
    "wissen": "Versorgungsforschung", "klima": "Hitze, Klima & Gesundheit",
    "ki": "Digitalisierung, KI & Gesundheit", "pflege": "Pflege & Langzeitversorgung",
    "longevity": "Gesundes Altern & Longevity", "healthliteracy": "Gesundheitskompetenz",
    "impfen": "Impfen & Impfpraevention", "ncd": "Nicht uebertragbare Krankheiten",
    "gender": "Geschlechtersensible Medizin", "adipositas": "Adipositas",
    "safety": "Patientensicherheit", "mental": "Psychische Gesundheit",
    "mvf": "MVF-Newsletter (redaktionell)",
    "datenschutz": "Datenschutzerklaerung gelesen - wird immer mitgesetzt",
}


def hole(schluessel: str, pfad: str) -> dict:
    dc = schluessel.rsplit("-", 1)[-1]
    if not re.fullmatch(r"[a-z]{2}\d+", dc):
        raise SystemExit("Der Schluessel endet nicht auf ein Rechenzentrum wie '-us6'.")
    anfrage = urllib.request.Request(
        f"https://{dc}.api.mailchimp.com/3.0{pfad}",
        headers={
            "Authorization": "Basic " + base64.b64encode(f"mvf:{schluessel}".encode()).decode(),
            "User-Agent": "mvf-anmeldung-gruppen",
        },
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=30) as antwort:
            return json.load(antwort)
    except urllib.error.HTTPError as fehler:
        raise SystemExit(f"Mailchimp antwortet mit HTTP {fehler.code} auf {pfad}\n"
                         f"{fehler.read().decode('utf-8', 'replace')[:400]}")


def passt(name: str, stichworte: tuple[str, ...], verboten: tuple[str, ...]) -> bool:
    klein = name.lower()
    for wort in verboten:
        if wort in klein:
            return False
    for wort in stichworte:
        # Kurze Kuerzel als ganzes Wort suchen, laengere als Teilzeichenkette:
        # "vf" darf nicht in "MVF" treffen, "psych" soll aber "Psychische" finden.
        muster = rf"\b{re.escape(wort)}\b" if len(wort) <= 3 else re.escape(wort)
        if not re.search(muster, klein):
            return False
    return True


def main() -> int:
    schluessel = (os.environ.get("MAILCHIMP_API_KEY") or "").strip()
    if not schluessel:
        raise SystemExit(
            "MAILCHIMP_API_KEY ist nicht gesetzt.\n"
            "  In der Eingabeaufforderung:  set MAILCHIMP_API_KEY=xxxx-us6\n"
            "  In PowerShell:               $env:MAILCHIMP_API_KEY = 'xxxx-us6'")

    listen = hole(schluessel, "/lists?count=200&fields=lists.id,lists.name")["lists"]
    if not listen:
        raise SystemExit("Das Konto hat keine Zielgruppe.")

    # Das Konto fuehrt rund zwanzig Zielgruppen - Altlasten aus Kongressen und
    # Preisausschreiben von 2015 an. Der Hausverteiler ist EINE davon, und
    # einfach die erste zu nehmen waere der sichere Weg in die falsche Liste.
    # Die Kennung ist bekannt: Sie stand schon als `id` in der Adresse des
    # alten Anmeldeformulars.
    HAUSLISTE = "1c8fc10ec7"      # eRelation GESAMT
    gewaehlt = (sys.argv[sys.argv.index("--liste") + 1]
                if "--liste" in sys.argv[:-1] else "")
    treffer = [l for l in listen if l["id"] == (gewaehlt or HAUSLISTE)]

    if not treffer:
        print(f"{len(listen)} Zielgruppen im Konto, keine mit der Kennung "
              f"'{gewaehlt or HAUSLISTE}':")
        for l in sorted(listen, key=lambda x: x["name"].lower()):
            print(f"  {l['id']}  {l['name']}")
        print()
        print("Mit  --liste <KENNUNG>  die richtige waehlen.")
        return 1

    liste = treffer[0]
    print(f"Zielgruppe: {liste['name']}  (LISTE = '{liste['id']}')")
    if len(listen) > 1:
        print(f"({len(listen)} Zielgruppen im Konto - die uebrigen sind Altlasten "
              f"aus Kongressen und Preisausschreiben.)")
    print()

    gefunden: list[tuple[str, str, str]] = []   # Kategorie, Name, Kennung
    kats = hole(schluessel, f"/lists/{liste['id']}/interest-categories?count=60")
    for kat in kats.get("categories", []):
        titel = kat.get("title", "?")
        ints = hole(schluessel,
                    f"/lists/{liste['id']}/interest-categories/{kat['id']}/interests?count=100")
        print(f"== {titel} ==")
        for i in ints.get("interests", []):
            print(f"  {i.get('name','?'):<44} {i.get('id','?')}")
            gefunden.append((titel, i.get("name", ""), i.get("id", "")))
        print()

    print("=" * 72)
    print("Vorschlag fuer INTERESSEN in anmeldung-zugang.php")
    print("Bitte gegen die Liste oben pruefen, bevor Sie ihn uebernehmen.")
    print("=" * 72)
    print("const INTERESSEN = [")
    offen = 0
    for kurz, stichworte in HINWEISE.items():
        treffer = [(n, k) for _, n, k in gefunden
                   if passt(n, stichworte, VERBOTEN.get(kurz, ()))]
        erklaerung = ERLAEUTERUNG.get(kurz, "")
        if len(treffer) == 1:
            name, kennung = treffer[0]
            print(f"    {kurz!r:<18} => {kennung!r},   // {name}")
        else:
            offen += 1
            warum = "nichts gefunden" if not treffer else \
                    "mehrdeutig: " + ", ".join(n for n, _ in treffer)
            print(f"    {kurz!r:<18} => '',   // {erklaerung} -- {warum}")
    print("];")

    if offen:
        print(f"\n{offen} Zeile(n) offen. Kennung aus der Liste oben eintragen.")
    else:
        print("\nAlle Zeilen zugeordnet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
