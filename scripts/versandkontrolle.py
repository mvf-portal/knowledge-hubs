#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ist die Ausgabe von heute in allen Hubs wirklich hinausgegangen?

`versand-status.json` sagt, was TERMINIERT wurde - nicht, was ankam. Zwischen
beidem liegt die Stunde bis 10:00 (und alles, was Mailchimp in dieser Stunde
tun oder lassen kann). Diese Kontrolle fragt Mailchimp selbst.

**Ein Aufruf reicht fuer alle zwoelf Hubs**: Kampagnen sind kontoweit, nicht je
Gruppe. Der Schluessel dieses Repos (KNOWLEDGEHUBSMC) sieht sie alle; die zwoelf
Portale muessen dafuer nicht angefasst werden.

Zugeordnet werden die Kampagnen ueber ihren Titel: Jedes Portal setzt ein
eigenes Praefix ("MVF Safety-Newsletter 27.08.2026"), das sich vollstaendig von
den anderen unterscheidet - genau dafuer ist die Regel da.

Am Wochenende wird planmaessig nichts versendet - dann schweigt die
Kontrolle, siehe WOCHENENDE_AUS weiter unten.

Aufruf:
    python scripts/versandkontrolle.py                # heute
    python scripts/versandkontrolle.py --tag 2026-08-27
    python scripts/versandkontrolle.py --auch-wochenende
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TZ = ZoneInfo("Europe/Berlin")

# Samstag und Sonntag terminiert kein Portal - `WOCHENENDE_AUS` in deren
# mailchimp_entwurf.py bricht vor dem Entwurf ab. Es gibt an diesen Tagen also
# fuer keinen Hub eine Kampagne, und ohne diese Pruefung meldete die Kontrolle
# jeden Samstag und Sonntag "12 Hub(s) nicht versendet" - zwoelf Fehlalarme je
# Wochenende (zuletzt #16 und #19). Wer das ein paar Wochen liest, liest
# irgendwann auch den echten Alarm nicht mehr.
#
# Der Wert muss zu dem in mailchimp_entwurf.py passen: Wird dort wieder am
# Wochenende versendet, gehoert er auch hier auf False.
WOCHENENDE_AUS = True

# Die Praefixe holt das Skript aus der portal.json der Hubs, statt sie hier
# noch einmal zu fuehren: Es gibt in diesem Repo schon drei solche Listen
# (versand_bericht, studien_sammeln, abfrage_wache), und eine vierte waere eine
# vierte Stelle, an der ein neuer Hub vergessen werden kann.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from versand_bericht import PORTALE  # noqa: E402

ROH_PORTAL = "https://raw.githubusercontent.com/{repo}/main/portal.json"


def praefix(repo: str) -> str | None:
    """Der Kampagnen-Praefix des Hubs - Mailchimp kennt die Ausgabe nur ueber
    ihren Titel, und der beginnt mit genau diesem Praefix."""
    try:
        req = urllib.request.Request(ROH_PORTAL.format(repo=repo),
                                     headers={"User-Agent": "mvf-versandkontrolle"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("MC_PRAEFIX")
    except Exception:  # noqa: BLE001
        return None


def kampagnen(schluessel: str) -> list[dict]:
    """Alle Kampagnen der letzten Tage, mit Status und Versandzahlen."""
    dc = schluessel.rsplit("-", 1)[-1]
    seit = (dt.datetime.now(TZ) - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S%z")
    url = (f"https://{dc}.api.mailchimp.com/3.0/campaigns"
           f"?count=200&sort_field=create_time&sort_dir=DESC&since_create_time={seit}")
    req = urllib.request.Request(url, headers={"User-Agent": "mvf-versandkontrolle"})
    import base64
    req.add_header("Authorization", "Basic " +
                   base64.b64encode(f"anystring:{schluessel}".encode()).decode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("campaigns", [])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tag", default=dt.datetime.now(TZ).date().isoformat())
    p.add_argument("--auch-wochenende", action="store_true",
                   help="auch an Samstagen und Sonntagen pruefen")
    a = p.parse_args()

    tag = dt.date.fromisoformat(a.tag)
    stempel = tag.strftime("%d.%m.%Y")          # so steht das Datum im Titel

    # Vor dem Schluessel geprueft: Am Wochenende gibt es nichts zu fragen, also
    # auch keinen Grund, an einem fehlenden Mailchimp-Schluessel zu scheitern.
    if WOCHENENDE_AUS and tag.weekday() >= 5 and not a.auch_wochenende:
        name = "Samstag" if tag.weekday() == 5 else "Sonntag"
        print(f"{name}, {stempel}: planmaessig kein Versand - nichts zu pruefen.")
        return 0

    schluessel = os.environ.get("KNOWLEDGEHUBSMC", "").strip()
    if not schluessel:
        print("KNOWLEDGEHUBSMC fehlt.")
        return 1
    alle = kampagnen(schluessel)

    zeilen = [f"Versandkontrolle {stempel}", ""]
    versendet, offen = 0, []
    for name, repo in PORTALE:
        if repo.endswith("knowledge-hubs"):
            continue
        pre = praefix(repo)
        if not pre:
            zeilen.append(f"?  {name:<34} portal.json nicht lesbar")
            offen.append(name)
            continue
        titel = f"{pre} {stempel}"
        treffer = [k for k in alle if k["settings"]["title"] == titel]
        if not treffer:
            zeilen.append(f"?  {name:<34} keine Kampagne '{titel}'")
            offen.append(name)
            continue
        k = treffer[0]
        stand = k["status"]
        anzahl = k.get("emails_sent", 0)
        wann = k.get("send_time") or ""
        if wann:
            wann = dt.datetime.fromisoformat(wann.replace("Z", "+00:00")).astimezone(TZ)
            wann = f"{wann:%H:%M}"
        if stand == "sent":
            versendet += 1
            zeilen.append(f"OK {name:<34} versendet {wann} Uhr an {anzahl} Empfänger")
        elif stand in ("schedule", "sending"):
            zeilen.append(f"…  {name:<34} {stand} (geplant {wann} Uhr)")
            offen.append(name)
        else:
            zeilen.append(f"!! {name:<34} Status '{stand}' - NICHT versendet")
            offen.append(name)

    zahl = len([x for x in PORTALE if not x[1].endswith("knowledge-hubs")])
    zeilen.append(f"\n{versendet} von {zahl} versendet.")
    text = "\n".join(zeilen)
    print(text)
    # Gemeldet wird nur, was auffaellt: Eine taegliche Bestaetigung, dass alles
    # gut ging, waere nach einer Woche eine Meldung, die niemand mehr liest.
    if offen and (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        import subprocess
        # Zugewiesen wie beim Sammelbericht: Die Issue legt
        # `github-actions[bot]` an, und fuer Bot-Aktivitaet verschickt GitHub
        # keine Watching-Benachrichtigung. Ohne Assignee bliebe der Alarm im
        # Repo liegen - siehe versand_bericht.py.
        subprocess.run(["gh", "issue", "create", "-R", "mvf-portal/knowledge-hubs",
                        "-t", f"Versand {stempel}: {len(offen)} Hub(s) nicht versendet",
                        "-b", text, "--assignee", "mvf-portal"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
