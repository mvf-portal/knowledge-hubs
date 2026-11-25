#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ein Lebenszeichen jeden Werktagmorgen, auch wenn alles in Ordnung ist.

Angelegt am 25.11.2026, weil Peter eine Woche nicht am Rechner ist und sich
darauf verlassen koennen muss, dass die Newsletter hinausgehen.

**Der Unterschied zu allem, was es schon gibt:** Laufwache, Sammelbericht und
Versandkontrolle melden sich nur, wenn etwas auffaellt. Das ist im Alltag
richtig, taugt aber nicht fuer eine Abwesenheit. Wer eine Woche lang nichts
hoert, weiss nicht, ob alles gut ging oder ob die Wache selbst still steht.
Diese Meldung kommt deshalb JEDEN Werktag, und ihr Ausbleiben ist dann selbst
das Alarmzeichen. Siehe das Gedaechtnis unter vermerk-bezeugt-anwesenheit.

Geprueft wird nichts Neues. Das Skript ruft die beiden vorhandenen Pruefungen
auf, beide im Trockenmodus, und fasst sie zusammen:

    laufwache.py --trocken --ohne-mail   Ist heute jeder der 20 Hubs gelaufen?
    versand_bericht.py --trocken         Was wurde terminiert, was gestoppt?

Die Kernaussage steht im BETREFF, nicht im Text. Peter liest sie unterwegs
am Telefon, und dort sieht er oft nur die Betreffzeile.

Aufruf:
    py scripts/morgenmeldung.py              # pruefen und melden
    py scripts/morgenmeldung.py --ohne-mail  # nur ausgeben, nichts senden

Geplante Aufgabe: "MVF Morgenmeldung", werktags 08:00 Ortszeit. Das ist nach
dem Lauf (05:20) und nach der Kontrolle (07:00), und es bleiben zwei Stunden
bis zum Versand um 10:00, um noch einzugreifen.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIER = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

TZ = ZoneInfo("Europe/Berlin")
# Dieselbe Adresse wie die Laufwache, aus ihr geholt statt hier wiederholt.
from laufwache import MELDEADRESSE, melden  # noqa: E402

GRENZE = 600  # Sekunden je Pruefung, danach gilt sie als haengend


def pruefung(name: str, befehl: list[str]) -> tuple[str, bool]:
    """Eine Pruefung laufen lassen. Rueckgabe: Ausgabe und ob sie durchkam.

    Eine Pruefung, die abstuerzt oder haengt, darf die Meldung nicht
    verhindern. Sonst faellt genau in dem Moment die Nachricht aus, in dem
    etwas nicht stimmt.
    """
    try:
        r = subprocess.run([sys.executable, *befehl], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           cwd=str(HIER.parent), timeout=GRENZE)
        text = (r.stdout or "") + (r.stderr or "")
        return text.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        return f"{name}: nach {GRENZE // 60} Minuten noch nicht fertig.", False
    except Exception as e:  # noqa: BLE001
        return f"{name}: liess sich nicht ausfuehren ({e}).", False


def zaehlen(bericht: str) -> tuple[int, int, int]:
    """Terminiert, gestoppt und ohne Statusdatei - aus dem Sammelbericht.

    Gezaehlt werden die Zeichen, die der Bericht selbst setzt. Die Zahlen aus
    seiner Kopfzeile noch einmal zu lesen waere eine zweite Stelle, an der sich
    dieselbe Angabe aendern kann.
    """
    return (len(re.findall(r"^- ✅ ", bericht, re.M)),
            len(re.findall(r"^- ⛔ ", bericht, re.M)),
            len(re.findall(r"^- \? ", bericht, re.M)))


def main() -> int:
    ohne_mail = "--ohne-mail" in sys.argv
    jetzt = dt.datetime.now(TZ)
    tag = jetzt.strftime("%d.%m.")

    wache, wache_ok = pruefung("Laufwache",
                               ["scripts/laufwache.py", "--trocken", "--ohne-mail"])
    bericht, bericht_ok = pruefung("Sammelbericht",
                                   ["scripts/versand_bericht.py", "--trocken"])

    terminiert, gestoppt, ohne = zaehlen(bericht)
    # Was die Laufwache als auffaellig markiert, steht in ihren Zeilen mit !!
    # oder mit "KEIN Lauf". Beide Formen stammen aus pruefen() in laufwache.py.
    fehlend = len(re.findall(r"^(!!|\?) ", wache, re.M))

    # Der Betreff traegt die Entscheidung. Alles, was nicht glatt ist, kommt
    # nach vorn, damit es auf einem Telefonbildschirm nicht abgeschnitten wird.
    warnungen = []
    if not wache_ok:
        warnungen.append("Laufwache gestoert")
    if not bericht_ok:
        warnungen.append("Sammelbericht gestoert")
    if fehlend:
        warnungen.append(f"{fehlend} Lauf/Laeufe fehlen")
    if ohne:
        warnungen.append(f"{ohne} ohne Statusdatei")
    if not terminiert and jetzt.weekday() < 5:
        warnungen.append("KEINE Ausgabe terminiert")

    if warnungen:
        betreff = f"ACHTUNG Hubs {tag}: " + ", ".join(warnungen)
    else:
        betreff = f"Hubs {tag}: {terminiert} terminiert, alles planmaessig"
        if gestoppt:
            betreff += f", {gestoppt} angehalten"

    kopf = [betreff, "",
            f"Stand {jetzt:%d.%m.%Y %H:%M} Uhr. Versand ist um 10:00 Uhr.", ""]
    if not warnungen:
        kopf += ["Es ist nichts zu tun. Diese Meldung kommt jeden Werktag,",
                 "auch wenn alles in Ordnung ist. Bleibt sie aus, stimmt",
                 "etwas nicht mit dem Rechner oder mit dieser Aufgabe.", ""]
    else:
        kopf += ["Absagen geht bis zur letzten Minute: Kampagnenlink oeffnen",
                 "und in Mailchimp auf Unschedule druecken.", ""]

    text = "\n".join(kopf + ["== Laufwache ==", wache, "",
                             "== Was heute terminiert ist ==", bericht])
    print(text)

    if ohne_mail:
        print("\n(--ohne-mail: nichts gesendet)")
        return 1 if warnungen else 0

    if melden(betreff, text):
        print(f"\nGemeldet an {MELDEADRESSE}.")
    else:
        # Ohne Outlook bleibt die Meldung liegen. Das ist der eine Fall, in
        # dem das Schweigen nicht am Betrieb liegt, sondern an dieser Aufgabe.
        print("\nMeldung NICHT gesendet, Outlook war nicht erreichbar.")
        return 2
    return 1 if warnungen else 0


if __name__ == "__main__":
    raise SystemExit(main())
