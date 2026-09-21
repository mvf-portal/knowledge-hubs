#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Taeglicher Blick um 09:00: Sind die naechtlichen Laeufe wirklich gelaufen?

Am 27.08.2026 hat GitHub die geplanten Laeufe ALLER dreizehn Repos nicht
gestartet - zeitgleich mit einer Stoerung der Billing-Dienste, waehrend die
Statusseite fuer Actions "operational" meldete. Manuelles Starten funktionierte
die ganze Zeit; nur der Scheduler schwieg. Es kam kein einziger Newsletter, und
gemerkt hat es niemand, weil ein AUSGEBLIEBENER Lauf nichts meldet: keine
fehlgeschlagene Aktion, keine Mail, kein Eintrag - nur Stille.

Diese Wache laeuft deshalb ausserhalb von GitHub, auf diesem Rechner. Sie sieht
nach, ob es fuer heute einen erfolgreichen Lauf gibt, stoesst fehlende an und
meldet sich per Outlook. Um 09:00 bleibt eine Stunde bis zum Versand um 10:00 -
genug fuer den Lauf (ein bis zwei Minuten) und fuer einen Blick von Hand.

Innerhalb von GitHub greift bereits ein zweiter Zeitplan um 05:30 UTC. Diese
Wache ist die Stufe darunter: Sie faengt den Fall, dass GitHub ueberhaupt keinen
Zeitplan ausfuehrt.

Aufruf:
    py scripts/laufwache.py                # pruefen, fehlende anstossen, melden
    py scripts/laufwache.py --trocken      # nur pruefen und berichten
    py scripts/laufwache.py --ohne-mail    # ohne Outlook, nur Protokoll
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TZ = ZoneInfo("Europe/Berlin")
WURZEL = pathlib.Path(__file__).resolve().parent.parent
PROTOKOLL = WURZEL / "laufwache.log"
MELDEADRESSE = "stegmaier@m-vf.de"

# ACHTUNG: Diese Liste wird NICHT von portale_pflegen.py erzeugt, anders als
# PORTALE in versand_bericht.py, studien_sammeln.py und abfrage_wache.py. Sie
# steht bewusst daneben - die Wache prueft nur, was der Dirigent auch weckt,
# und der weckt nur, was versenden soll. Ein neuer Hub gehoert deshalb von Hand
# hierher UND in dirigent.yml; portale.json allein genuegt nicht.
#
LAEUFE = [
    ("Versorgungsforschung", "mvf-portal/versorgungsforschung-portal", "update-studies.yml"),
    ("Hitze, Klima & Gesundheit", "mvf-portal/klima-gesundheit-portal", "update-studies.yml"),
    ("Digitalisierung, KI & Gesundheit", "mvf-portal/ki-gesundheit-portal", "update-studies.yml"),
    ("Pflege & Langzeitversorgung", "mvf-portal/pflege-portal", "update-studies.yml"),
    ("Gesundes Altern & Longevity", "mvf-portal/longevity-portal", "update-studies.yml"),
    ("Gesundheitskompetenz", "mvf-portal/healthliteracy-portal", "update-studies.yml"),
    ("Impfen & Impfpraevention", "mvf-portal/impfen-portal", "update-studies.yml"),
    ("Nicht uebertragbare Krankheiten", "mvf-portal/ncd-portal", "update-studies.yml"),
    ("Geschlechtersensible Medizin", "mvf-portal/gender-portal", "update-studies.yml"),
    ("Adipositas", "mvf-portal/adipositas-portal", "update-studies.yml"),
    ("Patientensicherheit", "mvf-portal/safety-portal", "update-studies.yml"),
    ("Psychische Gesundheit", "mvf-portal/mental-portal", "update-studies.yml"),
    ("Onkologie", "mvf-portal/onkologie-portal", "update-studies.yml"),
    ("Kardiologie", "mvf-portal/kardio-portal", "update-studies.yml"),
    ("Diabetes", "mvf-portal/diabetes-portal", "update-studies.yml"),
]

# Der Sammelbericht wird mitgeprueft - faellt er aus, faellt die einzige
# taegliche Rueckmeldung ueber alle Hubs aus -, aber NICHT in derselben Runde
# wie die Hubs. Er steht deshalb hier und nicht in LAEUFE.
#
# Bis zum 21.09.2026 war er der sechzehnte Eintrag der Liste, und die Schleife
# stiess ihn im selben Durchgang an wie die fuenfzehn Hubs. An jedem Morgen, an
# dem GitHubs Cron ausfiel, weckte die Wache also den Berichterstatter
# gleichzeitig mit denen, ueber die er berichten sollte: Er las den Stand von
# vorgestern und meldete "Heute ist keine Ausgabe terminiert" - waehrend die
# Hubs nebenan gerade terminierten. Am 21.09.2026 (Montag, Versandtag) stand
# das fuer alle fuenfzehn Hubs in der Mail, obwohl alle fuenfzehn Ausgaben
# sauber fuer 10:00 Uhr standen.
#
# Eine falsche Entwarnung ist schlimmer als gar keine Meldung: Beim naechsten
# Mal haelt man eine echte Stoerung fuer denselben Fehlalarm.
SAMMELBERICHT = ("Sammelbericht", "mvf-portal/knowledge-hubs", "versand-bericht.yml")

GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def gh_ruf(*args: str) -> subprocess.CompletedProcess:
    """gh mit abgeschaltetem Pager - sonst wartet die Aufgabe auf eine Taste."""
    return subprocess.run([GH, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120,
                          env={**__import__("os").environ, "GH_PAGER": "cat", "PAGER": "cat"})


# Ein einzelner Fehlschlag der Abfrage ist kein Befund, sondern meist ein
# Aussetzer. Am 11.09.2026 um 09:00 kam `gh run list` fuer das Safety-Portal
# mit einem Fehlercode zurueck - 23 Minuten zuvor und unmittelbar danach lief
# dieselbe Abfrage einwandfrei. Nachgestellt werden konnte nichts: kein Rate
# Limit (4997 von 5000 frei), keine Zeitueberschreitung, dreimal sauber
# wiederholt.
#
# Das Wiederholen ist hier unbedenklich, weil nur GELESEN wird. Fuer
# anstossen() gilt das ausdruecklich NICHT - ein zweiter Versuch waere dort ein
# zweiter Lauf und damit womoeglich ein zweiter Newsletter.
ABFRAGE_VERSUCHE = 3
ABFRAGE_PAUSE = 5


def laeufe_von_heute(repo: str, workflow: str, heute: str) -> list[dict]:
    """Die heutigen Laeufe dieses Workflows, neueste zuerst.

    Gefiltert wird in Python und nicht ueber --created: Die Suchsyntax von gh
    rechnet in UTC, und ein Lauf um 05:30 UTC gehoert zum deutschen Heute.
    """
    for versuch in range(1, ABFRAGE_VERSUCHE + 1):
        r = gh_ruf("run", "list", "-R", repo, "--workflow", workflow, "--limit", "20",
                   "--json", "status,conclusion,createdAt,databaseId,event")
        if r.returncode == 0:
            break
        if versuch < ABFRAGE_VERSUCHE:
            time.sleep(ABFRAGE_PAUSE)
    else:
        # Alles protokollieren, was der Prozess hergibt. Bis zum 11.09.2026
        # stand hier nur stderr - und weil gh an diesem Morgen mit leerer
        # Fehlerausgabe zurueckkam, lautete die Meldung "gh run list
        # fehlgeschlagen: " und sagte nichts. Ein Fehler, der sich nicht
        # beschreiben laesst, ist beim naechsten Mal nicht zu finden.
        raise RuntimeError(
            f"gh run list fehlgeschlagen nach {ABFRAGE_VERSUCHE} Versuchen: "
            f"Rueckgabewert {r.returncode}, "
            f"Fehlerausgabe {r.stderr.strip()[:200] or '(leer)'}, "
            f"Ausgabe {r.stdout.strip()[:200] or '(leer)'}")
    aus = []
    for j in json.loads(r.stdout or "[]"):
        wann = dt.datetime.fromisoformat(j["createdAt"].replace("Z", "+00:00")).astimezone(TZ)
        if wann.date().isoformat() == heute:
            aus.append({**j, "wann": wann})
    return aus


# Der Dirigent weckt dieselben Repos wie diese Wache. Laeuft er noch, ist er
# zustaendig - und die Wache haelt still.
#
# Am 13.09.2026 tat sie es nicht: GitHub liess den um 04:20 Uhr angelegten
# Dirigenten-Lauf zwei Stunden und zehn Minuten auf einen Runner warten. Um
# 08:30 Uhr sah die Wache fuer die ersten drei Portale "KEIN Lauf heute" und
# stiess sie an - fuenf Sekunden bevor der Dirigent dasselbe tat. Beide Laeufe
# holten die Studien, beide wollten pushen, der zweite bekam
# "! [rejected] main -> main". Ab dem vierten Portal waren die Anstoesse des
# Dirigenten sichtbar, deshalb traf es genau die ersten drei.
DIRIGENT_REPO = "mvf-portal/knowledge-hubs"
DIRIGENT_WORKFLOW = "dirigent.yml"


def dirigent_unterwegs(heute: str) -> dict | None:
    """Ein Dirigenten-Lauf von heute, der noch nicht durch ist - oder nichts.

    Ohne Altersgrenze: Ein Lauf, der seit Stunden auf einen Runner wartet,
    weckt die Hubs trotzdem, sobald er einen bekommt. Genau daran ist der
    13.09.2026 gescheitert.

    Laesst sich die Frage nicht beantworten, gilt der Dirigent als nicht
    unterwegs: Eine Wache, die bei jeder Stoerung der Abfrage schweigt, ist
    keine.
    """
    try:
        for lauf in laeufe_von_heute(DIRIGENT_REPO, DIRIGENT_WORKFLOW, heute):
            if lauf["status"] != "completed":
                return lauf
    except Exception:  # noqa: BLE001
        return None
    return None


def anstossen(repo: str, workflow: str) -> str:
    r = gh_ruf("workflow", "run", workflow, "-R", repo)
    return "angestossen" if r.returncode == 0 else f"START FEHLGESCHLAGEN: {r.stderr.strip()[:120]}"


# Wie lange die Wache auf die Hub-Laeufe wartet, bevor sie den Sammelbericht
# trotzdem anstoesst. Ein Hub-Lauf braucht ein bis zwei Minuten; zwanzig
# Minuten decken auch den Fall ab, dass GitHub die Runner nur zoegerlich
# zuteilt. Laenger zu warten hilft nicht: Um 06:00 liegen vier Stunden bis zum
# Versand, aber ein Bericht, der erst um 06:40 kommt, wird nicht mehr gelesen.
# Reicht es nicht, geht der Bericht trotzdem raus - mit einem Hinweis, dass er
# unvollstaendig sein kann.
WARTEFRIST = 20 * 60
WARTETAKT = 45


def warten_bis_durch(offen: list[tuple[str, str, str]], heute: str) -> tuple[list[str], int]:
    """Wartet, bis die geweckten Hub-Laeufe durch sind.

    Zurueck kommen die Namen, die nach Ablauf der Frist immer noch nicht fertig
    waren, und die verstrichenen Sekunden.

    Gefragt wird nur nach den Repos, auf die tatsaechlich gewartet wird, und
    ein fertiges faellt sofort aus der Runde - sonst summierten sich bei
    fuenfzehn Hubs ueber zwanzig Minuten mehrere hundert Abfragen.

    Ein frisch angestossener Lauf taucht in der Abfrage nicht sofort auf.
    Solange von einem Repo noch gar kein heutiger Lauf zu sehen ist, gilt er
    deshalb als ausstehend und nicht als fertig - sonst waere das Warten genau
    in dem Moment vorbei, in dem es anfangen muesste.
    """
    beginn = time.monotonic()
    wartend = list(offen)
    while wartend and time.monotonic() - beginn < WARTEFRIST:
        time.sleep(WARTETAKT)
        noch = []
        for eintrag in wartend:
            name, repo, workflow = eintrag
            try:
                heutige = laeufe_von_heute(repo, workflow, heute)
            except Exception:  # noqa: BLE001 - eine stockende Abfrage ist kein Grund,
                noch.append(eintrag)  # den Lauf fuer fertig zu erklaeren
                continue
            if heutige and all(j["status"] == "completed" for j in heutige):
                continue
            noch.append(eintrag)
        wartend = noch
    return [n for n, _, _ in wartend], int(time.monotonic() - beginn)


def pruefen(name: str, repo: str, workflow: str, heute: str,
            trocken: bool, wartend: dict | None) -> tuple[str, bool, bool]:
    """Ein Eintrag: Zeile fuers Protokoll, auffaellig?, laeuft jetzt?

    "laeuft jetzt" meint beides - eben angestossen oder schon unterwegs. Auf
    beides muss der Sammelbericht warten.
    """
    try:
        heutige = laeufe_von_heute(repo, workflow, heute)
    except Exception as e:  # noqa: BLE001
        return f"?  {name}: nicht abfragbar ({e})", True, False
    erfolgreich = [j for j in heutige if j["conclusion"] == "success"]
    laufend = [j for j in heutige if j["status"] != "completed"]
    if erfolgreich:
        return f"OK {name}: {erfolgreich[0]['wann']:%H:%M} Uhr gelaufen.", False, False
    if laufend:
        return f"…  {name}: laeuft gerade ({laufend[0]['wann']:%H:%M} Uhr).", False, True
    grund = "fehlgeschlagen" if heutige else "KEIN Lauf heute"
    if trocken:
        tat = "nicht angestossen (--trocken)"
    elif wartend:
        tat = "nicht angestossen (Dirigent ist noch unterwegs)"
    else:
        tat = anstossen(repo, workflow)
    return f"!! {name}: {grund} - {tat}", True, tat == "angestossen"


def melden(betreff: str, text: str) -> bool:
    """Meldung ueber das laufende Outlook - derselbe Weg wie bei den Pressemeldungen."""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = MELDEADRESSE
        mail.Subject = betreff
        mail.Body = text
        mail.Send()
        return True
    except Exception as e:  # noqa: BLE001 - eine fehlende Meldung darf den Lauf nicht kippen
        print(f"Outlook-Meldung nicht moeglich ({e})")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trocken", action="store_true", help="nichts anstossen, nur berichten")
    p.add_argument("--ohne-mail", action="store_true", help="keine Outlook-Meldung")
    a = p.parse_args()

    jetzt = dt.datetime.now(TZ)
    heute = jetzt.date().isoformat()
    zeilen, auffaellig = [], []

    # Erst den Dirigenten fragen, dann die Hubs: Sonst wecken beide.
    wartend = dirigent_unterwegs(heute)
    if wartend:
        zeilen.append(f"!! Dirigent: seit {wartend['wann']:%H:%M} Uhr noch nicht "
                      f"durch ({wartend['status']}) - diese Runde stoesst "
                      f"nichts an, er ist zustaendig.")
        # Trotzdem melden: Haengt der Dirigent wirklich fest, darf die Wache
        # nicht auch noch schweigen.
        auffaellig.append("Dirigent")

    # Erst die Hubs, dann der Sammelbericht - und dazwischen wird gewartet.
    offen: list[tuple[str, str, str]] = []
    for name, repo, workflow in LAEUFE:
        zeile, ist_auffaellig, laeuft = pruefen(name, repo, workflow, heute,
                                                a.trocken, wartend)
        zeilen.append(zeile)
        if ist_auffaellig:
            auffaellig.append(name)
        if laeuft:
            offen.append((name, repo, workflow))

    # Gewartet wird nur, wenn danach auch etwas passiert. Im Trockenlauf und
    # solange der Dirigent zustaendig ist, wird der Bericht ohnehin nicht
    # angestossen - dann waeren zwanzig Minuten Warten reine Verzoegerung.
    if offen and (a.trocken or wartend):
        zeilen.append(f"-- {len(offen)} Hub-Lauf/Laeufe noch offen; nicht "
                      f"abgewartet, es wird nichts angestossen.")
    elif offen:
        zeilen.append(f"-- Warte auf {len(offen)} Hub-Lauf/Laeufe, bevor der "
                      f"Sammelbericht angestossen wird.")
        haengen, dauer = warten_bis_durch(offen, heute)
        if haengen:
            zeilen.append(f"-- Nach {dauer // 60} Minuten noch nicht durch: "
                          f"{', '.join(haengen)}. Der Sammelbericht geht "
                          f"trotzdem raus und kann diese Hubs zu alt zeigen.")
            auffaellig.extend(haengen)
        else:
            zeilen.append(f"-- Alle Hub-Laeufe durch nach {dauer // 60}:"
                          f"{dauer % 60:02d} Minuten.")

    name, repo, workflow = SAMMELBERICHT
    if offen and not a.trocken and not wartend:
        # Hier wird ohne Ruecksicht darauf angestossen, ob heute schon ein
        # Bericht lief: Lief er, dann VOR den Hub-Laeufen, die diese Runde
        # eben geweckt hat - und damit auf dem Stand von gestern. Der
        # GitHub-eigene Zeitplan um 03:45 UTC ist genau dieser Fall, wenn die
        # Hub-Zeitplaene ausfallen und seiner nicht.
        #
        # Der Preis ist an solchen Morgen ein zweiter Bericht. Der zweite ist
        # der richtige, und zwei Berichte sind besser als ein falscher.
        tat = anstossen(repo, workflow)
        zeilen.append(f"!! {name}: nach den Hub-Laeufen neu {tat}")
        auffaellig.append(name)
    else:
        zeile, ist_auffaellig, _ = pruefen(name, repo, workflow, heute,
                                           a.trocken, wartend)
        zeilen.append(zeile)
        if ist_auffaellig:
            auffaellig.append(name)

    kopf = f"Laufwache {jetzt:%d.%m.%Y %H:%M}"
    text = kopf + "\n" + "\n".join(zeilen)
    print(text)
    with open(PROTOKOLL, "a", encoding="utf-8") as f:
        f.write(text + "\n\n")

    if auffaellig and not a.ohne_mail:
        if wartend:
            nachsatz = ("\n\nAngestoßen wurde nichts: Der Dirigent steht noch aus "
                        "und weckt die Hubs selbst, sobald GitHub ihm einen Runner "
                        "gibt. Zwei Wecker zugleich hatten am 13.09.2026 zu "
                        "abgelehnten Pushes geführt. Die nächste Runde dieser Wache "
                        "sieht nach, ob es gereicht hat:"
                        "\nhttps://github.com/mvf-portal\n")
        else:
            nachsatz = ("\n\nDie fehlenden Läufe sind angestoßen worden, sofern "
                        "GitHub erreichbar war. Bis zum Versand um 10:00 Uhr bleibt "
                        "Zeit, das Ergebnis anzusehen:"
                        "\nhttps://github.com/mvf-portal\n")
        melden(f"Knowledge-Hubs: {len(auffaellig)} Lauf/Laeufe fehlten heute früh",
               text + nachsatz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
