#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Erzeugt die Rasterfassungen des Hub-Zeichens aus logo/hub-icon.svg.

Warum nicht nur SVG: Safari und die Kachelansichten von Windows und Android
nehmen PNG, und manche Feedreader und Suchmaschinen fragen bis heute
/favicon.ico ab. Die Geometrie steht hier NOCH EINMAL, statt das SVG zu
rastern - das spart eine Abhaengigkeit (cairosvg) und ist bei sechs Rechtecken
ehrlicher als ein halb funktionierender Konverter. Wer das SVG aendert, aendert
diese Zahlen mit; der Vergleich steht in `bild/icon-probe.png`.

Aufruf:
    python scripts/icon_bauen.py
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WURZEL = pathlib.Path(__file__).resolve().parent.parent
BLAU = (0, 81, 161)
GOLD = (190, 158, 83)
WEISS = (255, 255, 255)
KANTE = 512


def zeichen(groesse: int = KANTE) -> Image.Image:
    """Dieselben Formen wie in logo/hub-icon.svg, auf 512 gerechnet.

    Kacheln in Gold - das Zeichen der Vorschaltseite. Die zwoelf Portale
    tragen dieselbe Form mit weissen Kacheln; ihre Fassung liegt in der
    Portal-Vorlage.
    """
    m = groesse / 512
    b = Image.new("RGBA", (groesse, groesse), (0, 0, 0, 0))
    d = ImageDraw.Draw(b)
    d.rounded_rectangle([0, 0, groesse - 1, groesse - 1], radius=113 * m, fill=BLAU)
    d.rounded_rectangle([66.6 * m, 81.9 * m, (66.6 + 76.8) * m, (81.9 + 348.2) * m],
                        radius=17.9 * m, fill=GOLD)
    for x in (184.3, 332.7):
        for y in (125.5, 273.9):
            d.rounded_rectangle([x * m, y * m, (x + 112.6) * m, (y + 112.6) * m],
                                radius=24.8 * m, fill=GOLD)
    return b


def main() -> int:
    gross = zeichen(KANTE)
    logo = WURZEL / "logo"
    # 512 fuer Kachelansichten, 180 fuer Apple, 32 als Rueckfall im <link>.
    for g in (512, 180, 32):
        gross.resize((g, g), Image.LANCZOS).save(logo / f"hub-icon-{g}.png")
    # .ico traegt mehrere Groessen in einer Datei; 16 ist die Tableiste.
    gross.resize((48, 48), Image.LANCZOS).save(
        WURZEL / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    # Probestreifen: so sieht es dort aus, wo es wirklich gesehen wird.
    streifen = Image.new("RGBA", (16 + 32 + 64 + 128 + 40, 128), (245, 245, 245, 255))
    x = 0
    for g in (16, 32, 64, 128):
        r = gross.resize((g, g), Image.LANCZOS)
        streifen.paste(r, (x, (128 - g) // 2), r)
        x += g + 10
    (WURZEL / "bild").mkdir(exist_ok=True)
    streifen.save(WURZEL / "bild" / "icon-probe.png")
    print("logo/hub-icon-{512,180,32}.png, favicon.ico und bild/icon-probe.png geschrieben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
