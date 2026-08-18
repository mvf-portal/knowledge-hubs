#!/usr/bin/env python3
"""Eine Meldung statt fuenf: Was heute frueh in allen Hubs beschlossen wurde.

Jedes Portal schreibt beim naechtlichen Lauf eine `versand-status.json` in sein
Repo - terminiert oder gestoppt, mit Grund. Dieses Skript liest sie alle ein
und legt daraus **eine** GitHub-Issue an. GitHub verschickt sie als E-Mail an
alle, die das Repo beobachten; ein zusaetzliches Postfach-Geheimnis braucht es
dafuer nicht.

Der Sinn ist das Veto-Fenster: Die Kampagnen sind zu diesem Zeitpunkt
terminiert, aber noch nicht versendet. Wer die Meldung liest und etwas
absagen will, klickt den Kampagnenlink und drueckt in Mailchimp auf
"Unschedule". Wer nichts tut, laesst den Versand laufen.

Aufruf im Workflow:
    python scripts/versand_bericht.py            # legt die Issue an
    python scripts/versand_bericht.py --trocken  # nur ausgeben, nichts anlegen
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Die Portale der Reihe. Kommt einer hinzu, hier eine Zeile ergaenzen - dieselbe
# Pflegestelle wie REIHE in der Newsletter-Seite und ZUSATZ in vorschaltseite.py.
PORTALE = [
    ("Versorgungsforschung", "mvf-portal/versorgungsforschung-portal"),
    ("Hitze, Klima & Gesundheit", "mvf-portal/klima-gesundheit-portal"),
    ("Digitalisierung, KI & Gesundheit", "mvf-portal/ki-gesundheit-portal"),
    ("Pflege & Langzeitversorgung", "mvf-portal/pflege-portal"),
    ("Gesundes Altern & Longevity", "mvf-portal/longevity-portal"),
]
ROH = "https://raw.githubusercontent.com/{repo}/main/versand-status.json"
BERICHT_REPO = "mvf-portal/knowledge-hubs"


def hole(repo: str) -> dict | None:
    """Statusdatei eines Portals - None, wenn es heute keine gibt."""
    try:
        req = urllib.request.Request(ROH.format(repo=repo),
                                     headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def ortszeit(utc_iso: str | None) -> str:
    """Versandzeitpunkt in deutscher Ortszeit - danach richtet sich der Leser."""
    if not utc_iso:
        return "?"
    try:
        z = dt.datetime.fromisoformat(utc_iso).astimezone(ZoneInfo("Europe/Berlin"))
        return z.strftime("%H:%M Uhr")
    except ValueError:
        return utc_iso


def zeile(name: str, repo: str, s: dict | None, heute: str) -> str:
    if s is None:
        return (f"- **{name}** — keine Statusdatei. Der Lauf ist entweder noch nicht "
                f"durch oder abgebrochen. [Actions ansehen](https://github.com/{repo}/actions)")
    if s.get("datum") != heute:
        return (f"- **{name}** — Status ist vom {s.get('datum')}, nicht von heute. "
                f"Der nächtliche Lauf hat vermutlich nichts Neues gefunden.")
    if s.get("stand") == "terminiert":
        uhr = ortszeit(s.get("termin_utc"))
        return (f"- ✅ **{name}** — {s['anzahl']} Studien, geht um {uhr} raus. "
                f"[Ansehen oder absagen]({s['kampagne']})  \n"
                f"  <sub>{s.get('betreff', '')}</sub>")
    gruende = "; ".join(s.get("beanstandungen", [])) or "unbekannt"
    return (f"- ⛔ **{name}** — **gestoppt**, nichts wird versendet. "
            f"[Entwurf ansehen]({s['kampagne']})  \n"
            f"  <sub>Grund: {gruende}</sub>")


def main() -> int:
    trocken = "--trocken" in sys.argv
    heute = dt.date.today().isoformat()
    zeilen, terminiert, gestoppt, offen = [], 0, 0, 0
    for name, repo in PORTALE:
        s = hole(repo)
        zeilen.append(zeile(name, repo, s, heute))
        if s is None or s.get("datum") != heute:
            offen += 1
        elif s.get("stand") == "terminiert":
            terminiert += 1
        else:
            gestoppt += 1

    teile = [f"{terminiert} terminiert"]
    if gestoppt:
        teile.append(f"{gestoppt} gestoppt")
    if offen:
        teile.append(f"{offen} ohne Meldung")
    titel = (f"Newsletter {dt.date.fromisoformat(heute).strftime('%d.%m.%Y')} — "
             + ", ".join(teile))

    rumpf = "\n".join([
        "Die terminierten Ausgaben gehen **automatisch** raus. Sie müssen nichts tun.",
        "",
        "Wollen Sie eine verhindern: Kampagnenlink öffnen und in Mailchimp auf "
        "*Unschedule* drücken — das geht bis zur letzten Minute vor dem Versand.",
        "",
        *zeilen,
        "",
        "---",
        "<sub>Erzeugt von `scripts/versand_bericht.py`. Geprüft wurde jede Ausgabe "
        "vom Torwächter (`scripts/torwaechter.py` im jeweiligen Portal): fehlende "
        "Felder, Platzhalter, Zeitschrift und Jahr gegen PubMed, deutsche Sprache, "
        "Dubletten, leeres Empfängersegment. **Nicht** geprüft werden kann, ob eine "
        "Zusammenfassung die Studie inhaltlich richtig wiedergibt — dafür ist dieses "
        "Zeitfenster da.</sub>",
    ])

    print(titel + "\n\n" + rumpf)
    if trocken:
        return 0
    if not os.environ.get("GH_TOKEN") and not os.environ.get("GITHUB_TOKEN"):
        print("\nKein Token - keine Issue angelegt.")
        return 0
    subprocess.run(["gh", "issue", "create", "-R", BERICHT_REPO,
                    "--title", titel, "--body", rumpf], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
