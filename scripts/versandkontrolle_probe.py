#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unterscheidet die Versandkontrolle einen angehaltenen Hub von einem Ausfall?

Am 24.11.2026 meldete die Kontrolle abends "1 Hub(s) nicht versendet" fuer
genau den Hub, den der Torwaechter morgens selbst angehalten hatte, und am
25.11.2026 wieder. Seitdem fragt sie die versand-status.json des Portals.

Diese Probe laeuft ohne Mailchimp-Schluessel: Die Kampagnenliste wird
nachgestellt, die Statusdateien kommen echt aus den Repos. Geprueft wird
also genau das Stueck, das neu ist, die Entscheidung.

Die wichtigste der sechs Faelle ist nicht der stillgelegte Fehlalarm,
sondern Fall 3: Ein Hub, den niemand angehalten hat und der trotzdem nicht
hinausging, MUSS weiter Alarm ausloesen. Ein Patch, der den Fehlalarm
abstellt und dabei den echten Alarm mit abraeumt, waere die schlechtere
Fassung, und ohne diesen Fall wuerde die Probe ihn durchwinken.

Aufruf:
    py scripts/versandkontrolle_probe.py
"""
from __future__ import annotations

import io
import os
import sys
import contextlib
import pathlib

HIER = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

import versandkontrolle as vk  # noqa: E402

# Echte Repos, damit angehalten() echte Statusdateien liest. muskel steht
# heute auf "gestoppt", die Versorgungsforschung auf "terminiert".
MUSKEL = "mvf-portal/muskel-portal"
WISSEN = "mvf-portal/versorgungsforschung-portal"
KLIMA = "mvf-portal/klima-gesundheit-portal"
TAG = "2026-11-25"
STEMPEL = "25.11.2026"


def kampagne(pre: str, status: str, gesendet: int = 0) -> dict:
    return {"settings": {"title": f"{pre} {STEMPEL}"},
            "status": status, "emails_sent": gesendet,
            "send_time": "2026-11-25T09:00:00+00:00" if status == "sent" else ""}


def lauf(portale: list[tuple[str, str]], staende: dict[str, str]) -> str:
    """Die Kontrolle einmal durchspielen und ihre Ausgabe zurueckgeben."""
    alt_portale, alt_kampagnen = vk.PORTALE, vk.kampagnen
    alt_argv = sys.argv
    # Ohne Token legt main() keine Issue an. Eine Probe, die Meldungen in ein
    # oeffentliches Repo schreibt, waere schlimmer als keine Probe.
    alt_umgebung = {k: os.environ.pop(k, None)
                    for k in ("GH_TOKEN", "GITHUB_TOKEN")}
    os.environ["KNOWLEDGEHUBSMC"] = "probe-us6"
    try:
        vk.PORTALE = portale
        vk.kampagnen = lambda _s: [
            kampagne(vk.praefix(repo), stand[0], stand[1])
            for repo, stand in staende.items()]
        sys.argv = ["versandkontrolle.py", "--tag", TAG]
        fang = io.StringIO()
        with contextlib.redirect_stdout(fang):
            vk.main()
        return fang.getvalue()
    finally:
        vk.PORTALE, vk.kampagnen = alt_portale, alt_kampagnen
        sys.argv = alt_argv
        os.environ.pop("KNOWLEDGEHUBSMC", None)
        for k, v in alt_umgebung.items():
            if v is not None:
                os.environ[k] = v


def main() -> int:
    abweichungen: list[str] = []

    def pruefen(nr: int, was: str, text: str,
                muss: list[str], darf_nie: list[str]) -> None:
        for m in muss:
            if m not in text:
                abweichungen.append(f"Fall {nr} ({was}): fehlt {m!r}")
        for d in darf_nie:
            if d in text:
                abweichungen.append(f"Fall {nr} ({was}): steht da, darf nicht: {d!r}")

    beide = [("Muskuloskelettal", MUSKEL), ("Versorgungsforschung", WISSEN)]

    # 1 Der Fall vom 24.11.2026: angehalten, Entwurf liegt da. Kein Alarm.
    t = lauf(beide, {MUSKEL: ("save", 0), WISSEN: ("sent", 47)})
    pruefen(1, "angehalten, nicht versendet", t,
            ["-- Muskuloskelettal", "angehalten: das Empfaengersegment ist leer",
             "1 von 1 versendet.", "1 vom Torwächter angehalten"],
            ["!! Muskuloskelettal", "NICHT versendet"])

    # 2 Angehalten und trotzdem hinausgegangen. Das ist Alarm.
    t = lauf(beide, {MUSKEL: ("sent", 3), WISSEN: ("sent", 47)})
    pruefen(2, "angehalten, aber versendet", t,
            ["!! Muskuloskelettal", "war gestoppt, ist aber versendet worden"],
            ["-- Muskuloskelettal"])

    # 3 Die Gegenprobe. Niemand hat angehalten, es ging trotzdem nicht raus.
    #   Ohne diesen Fall koennte der Patch jeden Alarm verschlucken.
    t = lauf(beide, {MUSKEL: ("sent", 3), WISSEN: ("save", 0)})
    pruefen(3, "echter Ausfall bleibt Alarm", t,
            ["!! Versorgungsforschung", "NICHT versendet"],
            ["-- Versorgungsforschung"])

    # 4 Alles sauber: keine Sonderzeile, kein Nachsatz. Hier stehen zwei
    #   Hubs, die heute BEIDE nicht angehalten sind. Mit muskel ginge es
    #   nicht: Der ist heute echt gestoppt, und ein gestoppter Hub mit
    #   Status 'sent' ist Fall 2. Die erste Fassung dieser Probe hatte ihn
    #   trotzdem hier stehen und schlug fehl, obwohl das Werk richtig lag.
    sauber = [("Versorgungsforschung", WISSEN), ("Klima", KLIMA)]
    assert not vk.angehalten(KLIMA, TAG), "Vorbedingung: klima laeuft heute"
    t = lauf(sauber, {WISSEN: ("sent", 47), KLIMA: ("sent", 9)})
    pruefen(4, "alles versendet", t,
            ["2 von 2 versendet."],
            ["angehalten", "!!", "--"])

    # 5 Die Datumswache. Dieselbe Statusdatei, anderer Tag: Der Hub gilt
    #   NICHT als angehalten, denn ueber diesen Tag sagt sie nichts.
    assert vk.angehalten(MUSKEL, TAG), "Vorbedingung: muskel ist heute gestoppt"
    if vk.angehalten(MUSKEL, "2026-11-24") is not None:
        abweichungen.append("Fall 5 (Datumswache): Statusdatei von heute "
                            "wurde fuer gestern anerkannt")

    # 6 Steht die Regel auch wirklich im Werk, oder nur hier in der Probe?
    quelle = (HIER / "versandkontrolle.py").read_text(encoding="utf-8")
    if "halt = angehalten(repo, a.tag)" not in quelle:
        abweichungen.append("Fall 6: versandkontrolle.py fragt den "
                            "Torwaechter gar nicht")
    if "von {zahl} versendet" in quelle:
        abweichungen.append("Fall 6: die alte Soll-Rechnung steht noch da")

    for z in abweichungen:
        print(f"  ABWEICHUNG {z}")
    print(f"\n{len(abweichungen)} Abweichung(en).")
    return 1 if abweichungen else 0


if __name__ == "__main__":
    raise SystemExit(main())
