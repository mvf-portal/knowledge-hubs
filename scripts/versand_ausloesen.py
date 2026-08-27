#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verschickt die terminierten Ausgaben eines Tages SOFORT - von Hand ausgeloest.

Fuer den Fall, dass Mailchimp eine terminierte Kampagne nicht abarbeitet. Am
27.08.2026 standen alle zwoelf Ausgaben eine Viertelstunde nach der Sendezeit
noch auf `schedule`; die Kontrolle sah es, aendern konnte sie nichts.

Der Ablauf je Kampagne: Termin aufheben, dann senden. Mailchimp nimmt `send`
nur fuer Entwuerfe an - eine terminierte Kampagne muss vorher zurueck in den
Entwurfsstand.

**Dieses Skript verschickt an die Leserschaft.** Es laeuft deshalb nur mit
`--ja-wirklich`, es faehrt nur Kampagnen an, die bereits TERMINIERT waren (also
den Torwaechter passiert haben), und es ruehrt nichts an, was schon versendet
ist. Ein Tippfehler im Datum trifft ins Leere statt eine alte Ausgabe erneut
hinauszuschicken.

Aufruf:
    python scripts/versand_ausloesen.py                 # zeigt nur, was es taete
    python scripts/versand_ausloesen.py --ja-wirklich   # verschickt
    python scripts/versand_ausloesen.py --tag 2026-08-27 --ja-wirklich
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from versandkontrolle import kampagnen, praefix  # noqa: E402  - dieselbe Quelle
from versand_bericht import PORTALE  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")


def ruf(schluessel: str, methode: str, pfad: str) -> None:
    dc = schluessel.rsplit("-", 1)[-1]
    req = urllib.request.Request(f"https://{dc}.api.mailchimp.com/3.0{pfad}",
                                 method=methode, data=b"{}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "mvf-versand-ausloesen")
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(f"anystring:{schluessel}".encode()).decode())
    with urllib.request.urlopen(req, timeout=60):
        return


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tag", default=dt.datetime.now(TZ).date().isoformat())
    p.add_argument("--ja-wirklich", action="store_true",
                   help="wirklich verschicken; ohne diesen Schalter wird nur gezeigt")
    a = p.parse_args()

    schluessel = os.environ.get("KNOWLEDGEHUBSMC", "").strip()
    if not schluessel:
        print("KNOWLEDGEHUBSMC fehlt.")
        return 1

    stempel = dt.date.fromisoformat(a.tag).strftime("%d.%m.%Y")
    alle = kampagnen(schluessel)
    getan = 0

    print(f"Versand ausloesen fuer {stempel}"
          + ("" if a.ja_wirklich else "  (Probe - es wird nichts verschickt)") + "\n")
    for name, repo in PORTALE:
        if repo.endswith("knowledge-hubs"):
            continue
        pre = praefix(repo)
        if not pre:
            print(f"?  {name:<34} portal.json nicht lesbar")
            continue
        titel = f"{pre} {stempel}"
        treffer = [k for k in alle if k["settings"]["title"] == titel]
        if not treffer:
            print(f"?  {name:<34} keine Kampagne '{titel}'")
            continue
        k = treffer[0]
        if k["status"] == "sent":
            print(f"OK {name:<34} war schon versendet - nichts zu tun")
            continue
        if k["status"] != "schedule":
            # Ein Entwurf hat den Torwaechter NICHT passiert. Wer ihn trotzdem
            # verschicken will, tut das in Mailchimp und sieht dabei hin.
            print(f"!! {name:<34} Status '{k['status']}' - nicht terminiert, uebersprungen")
            continue
        if not a.ja_wirklich:
            print(f"→  {name:<34} wuerde jetzt verschickt")
            continue
        try:
            ruf(schluessel, "POST", f"/campaigns/{k['id']}/actions/unschedule")
            ruf(schluessel, "POST", f"/campaigns/{k['id']}/actions/send")
            getan += 1
            print(f"OK {name:<34} verschickt")
        except urllib.error.HTTPError as e:
            print(f"!! {name:<34} Mailchimp: {e.code} {e.read()[:160].decode(errors='replace')}")
    if a.ja_wirklich:
        print(f"\n{getan} Ausgabe(n) verschickt. Kontrolle: "
              f"python scripts/versandkontrolle.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
