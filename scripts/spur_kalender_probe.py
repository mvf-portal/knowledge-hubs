#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Misst, ob der Spurkalender der Laufwache die Regel wirklich trifft.

    py scripts/spur_kalender_probe.py
    py scripts/spur_kalender_probe.py --bis 2028-12-31

WARUM ES DIESE PROBE GIBT
-------------------------
Der Kalender der Wochen- und Monatsausgabe steht an drei Stellen: als Shell
im Dirigenten (.github/workflows/dirigent.yml), als `spur_faellig()` in
mailchimp_entwurf.py und als `spuren_von_heute()` in laufwache.py. Die
Dopplung ist gewollt - die Wache soll nicht mit dem Ueberwachten zusammen
ausfallen -, aber sie kann auseinanderlaufen.

Beide, Dirigent und Wache, benutzen DIESELBE Abkuerzung: Monatsausgabe am
Ersten, oder am Zweiten bzw. Dritten, wenn das ein Montag ist. Diese Probe
prueft die Abkuerzung gegen die AUSSAGE, die sie treffen soll ("der erste
Werktag des Monats"), indem sie die Tage des Monats von vorn durchgeht. Eine
Abkuerzung, die nur gegen sich selbst geprueft wird, ist nicht geprueft.

Der Gegentest ist eingebaut: `--gegenprobe` verdreht die Regel absichtlich.
Meldet die Probe dann keine Abweichung, misst sie nichts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from laufwache import spuren_von_heute  # noqa: E402


def erster_werktag(jahr: int, monat: int) -> dt.date:
    """Der erste Tag des Monats, der kein Samstag und kein Sonntag ist."""
    d = dt.date(jahr, monat, 1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def erwartet(d: dt.date, gegenprobe: bool = False) -> list[str]:
    aus = []
    if d.weekday() == (3 if gegenprobe else 4):
        aus.append("woche")
    if d == erster_werktag(d.year, d.month):
        aus.append("monat")
    return aus


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--von", default=dt.date.today().isoformat())
    p.add_argument("--bis", default=(dt.date.today()
                                     + dt.timedelta(days=400)).isoformat())
    p.add_argument("--gegenprobe", action="store_true",
                   help="die Erwartung absichtlich verdrehen; muss Abweichungen zeigen")
    a = p.parse_args()

    d = dt.date.fromisoformat(a.von)
    ende = dt.date.fromisoformat(a.bis)
    tage = abweichungen = 0
    erste = {"woche": None, "monat": None}
    while d <= ende:
        tage += 1
        ist, soll = spuren_von_heute(d), erwartet(d, a.gegenprobe)
        if ist != soll:
            abweichungen += 1
            if abweichungen <= 10:
                print(f"  ABWEICHUNG {d} ({d:%a}): Wache {ist or '-'} "
                      f"gegen Regel {soll or '-'}")
        for s in ist:
            if erste[s] is None:
                erste[s] = d
        d += dt.timedelta(days=1)

    print(f"\n{tage} Tage geprüft ({a.von} bis {a.bis}).")
    print(f"Erste Wochenausgabe: {erste['woche']}")
    print(f"Erste Monatsausgabe: {erste['monat']}")
    if a.gegenprobe:
        print(f"Gegenprobe: {abweichungen} Abweichung(en) - "
              f"{'die Probe misst' if abweichungen else 'DIE PROBE MISST NICHTS'}.")
        return 0 if abweichungen else 1
    print(f"{abweichungen} Abweichung(en).")
    return 1 if abweichungen else 0


if __name__ == "__main__":
    raise SystemExit(main())
