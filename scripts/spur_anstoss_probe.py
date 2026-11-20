#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueft, welchen Befehl die Wache zum Anstossen einer Spur baut.

    py scripts/spur_anstoss_probe.py

WARUM NICHT EINFACH ANSTOSSEN
-----------------------------
Der Anstoss einer Spur legt eine Mailchimp-Kampagne an und terminiert sie.
Ein Probelauf „zur Sicherheit" waere eine zweite Wochenausgabe an echte
Empfaenger. Deshalb wird hier nur der BEFEHL gemessen: `gh_ruf` wird durch
einen Mitschreiber ersetzt, `anstossen()` laeuft ganz normal, und was es an
gh uebergeben haette, wird mit der Zeile verglichen, die der Dirigent am
20.11.2026 zwanzigmal erfolgreich benutzt hat.

Das ist der Punkt, an dem `--f spur=` falsch sein koennte, ohne dass es
jemals auffiele: Die Wache stoesst nur an, was fehlt, und es fehlte noch
nie etwas. Eine Vorkehrung, die nie zuendet, ist nicht geprueft.
"""
from __future__ import annotations

import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import laufwache as L  # noqa: E402

# So ruft der Dirigent an (dirigent.yml, Schritt "Die faellige Ausgabe in
# allen Hubs anstossen"), zwanzigmal erfolgreich am 20.11.2026:
VORBILD = ["workflow", "run", "newsletter-spur.yml",
           "-R", "mvf-portal/pflege-portal", "-f", "spur=woche"]

mitschrift: list[list[str]] = []


def mitschreiber(*args: str):
    mitschrift.append(list(args))
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def main() -> int:
    L.gh_ruf = mitschreiber
    fehler = 0

    ergebnis = L.anstossen("mvf-portal/pflege-portal", L.SPUR_WORKFLOW,
                           ("-f", "spur=woche"))
    gebaut = mitschrift[-1]
    print("gebaut  :", " ".join(gebaut))
    print("Vorbild :", " ".join(VORBILD))
    if gebaut != VORBILD:
        print("  ABWEICHUNG: der Befehl ist nicht der des Dirigenten.")
        fehler += 1
    if ergebnis != "angestossen":
        print(f"  ABWEICHUNG: Rueckmeldung {ergebnis!r} statt 'angestossen'.")
        fehler += 1

    # Der Tagesanstoss darf sich dabei NICHT veraendert haben: dieselbe
    # Funktion, aber ohne Zusatz.
    L.anstossen("mvf-portal/pflege-portal", "update-studies.yml")
    taeglich = mitschrift[-1]
    print("täglich :", " ".join(taeglich))
    if taeglich != ["workflow", "run", "update-studies.yml",
                    "-R", "mvf-portal/pflege-portal"]:
        print("  ABWEICHUNG: der tägliche Anstoß hat sich geändert.")
        fehler += 1

    # Gegenprobe: Ein falsch gebauter Zusatz muss auffallen.
    L.anstossen("mvf-portal/pflege-portal", L.SPUR_WORKFLOW, ("--spur", "woche"))
    if mitschrift[-1] == VORBILD:
        print("  DIE PROBE MISST NICHTS: auch ein falscher Zusatz gilt als gleich.")
        fehler += 1
    else:
        print("Gegenprobe: ein falscher Zusatz fällt auf.")

    print(f"\n{fehler} Abweichung(en).")
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
