# -*- coding: utf-8 -*-
"""Baut den QR-Code fuer die Gewinnspielseite und setzt ihn ins Standplakat.

    py scripts/gewinnspiel_qr.py

Erzeugt `gewinnspiel/qr.svg` (blanker Code zur Weiterverwendung in Anzeige,
Roll-up, Programmheft) und schreibt denselben Code als eingebettetes SVG in
`gewinnspiel/plakat.html`.

Zwei Entscheidungen, die man dem Ergebnis nicht ansieht:

* **Fehlerkorrektur H**, nicht das uebliche M. Ein Plakat am Messestand wird
  schraeg fotografiert, steht im Gegenlicht und bekommt Fingerabdruecke ab;
  H vertraegt bis zu 30 Prozent Schaden. Der Code wird dadurch feiner, bei
  Plakatgroesse kostet das nichts.
* **Vier Module Ruhezone** (`border=4`), wie die Norm es verlangt. Auf
  weissem Papier ist die Versuchung gross, sie zu kuerzen und den Code
  groesser zu setzen - manche Lesegeraete finden ihn dann nicht mehr.
* **Der Code traegt genau die Adresse, die darunter gedruckt steht.** Kein
  UTM-Anhaengsel, kein Kuerzungsdienst. Wer misstrauisch ist, tippt die
  Adresse ab, und dann muss sie dieselbe Seite oeffnen; ausserdem zaehlt der
  eigene Zaehler ohnehin nur den Pfad, nicht die Abfrage - ein utm_source
  waere hier reine Zierde.

Braucht `segno` (py -m pip install segno).
"""

import pathlib
import re

import segno

HIER = pathlib.Path(__file__).resolve().parent.parent
ADRESSE = "https://knowledge-hubs.m-vf.de/gewinnspiel/"
FARBE = "#0051A1"          # das Blau der Hubs

# Zwischen diesen Marken steht im Plakat das SVG - so bleibt der Rest der
# Datei von Hand bearbeitbar, ohne dass das Skript ihn ueberschreibt.
ANFANG = "<!-- QR-START -->"
ENDE = "<!-- QR-ENDE -->"


def qr_svg() -> str:
    """Der Code als SVG-Schnipsel ohne eigene Groessenangabe.

    Die Groesse bestimmt das Plakat ueber CSS; ein festes width/height im SVG
    wuerde dort dagegenhalten. `svginline` liefert genau das: ein <svg> mit
    viewBox und ohne XML-Kopf, einbettbar in HTML.
    """
    qr = segno.make(ADRESSE, error="h")
    return qr.svg_inline(dark=FARBE, border=4, svgclass=None,
                         lineclass=None, omitsize=True)


def main() -> None:
    schnipsel = qr_svg()

    # 1. Der blanke Code als eigene Datei - fuer alles ausserhalb dieser Seite.
    eigen = segno.make(ADRESSE, error="h")
    ziel_svg = HIER / "gewinnspiel" / "qr.svg"
    eigen.save(str(ziel_svg), scale=10, border=4, dark=FARBE)
    print(f"geschrieben: {ziel_svg.relative_to(HIER)}")

    # 2. Derselbe Code in jedem Druckstueck, das ihn traegt. Zwei Formate,
    #    ein Code: Wer eines davon von Hand nachtruege, haette irgendwann
    #    zwei Adressen im Umlauf.
    for datei in ("plakat.html", "rollup.html"):
        einsetzen(HIER / "gewinnspiel" / datei, schnipsel)
    print(f"Adresse im Code: {ADRESSE}")
    return


def einsetzen(plakat: pathlib.Path, schnipsel: str) -> None:
    text = plakat.read_text(encoding="utf-8")
    neu, anzahl = re.subn(
        re.escape(ANFANG) + r".*?" + re.escape(ENDE),
        ANFANG + "\n" + schnipsel + "\n" + ENDE,
        text,
        flags=re.S,
    )
    if not anzahl:
        raise SystemExit(f"Marken {ANFANG} / {ENDE} fehlen in {plakat}")
    plakat.write_text(neu, encoding="utf-8")
    print(f"geschrieben: {plakat.relative_to(HIER)}")


if __name__ == "__main__":
    main()
