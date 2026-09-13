#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Der MVF-Newsletter alle zwei Wochen: News holen, Entwurf in Mailchimp anlegen.

Bis heute entstand jede Ausgabe von Hand: In Mailchimp die letzte Kampagne
kopieren, auf der Newsseite nachsehen, was seit dem letzten Versand dazukam,
je Rubrik drei Meldungen aussuchen und Titel, Vorspann und Link einzeln in die
Vorlage tippen. Dieses Skript nimmt den mechanischen Teil ab. Es entscheidet
nichts, was die Redaktion entscheiden muss - es legt einen **Entwurf** an.
Versendet wird in Mailchimp, von Hand, wie bisher.

    python scripts/newsletter.py                  # Entwuerfe anlegen, wenn faellig
    python scripts/newsletter.py --trocken        # nur zeigen, nichts anlegen
    python scripts/newsletter.py --immer          # Torwaechter uebergehen
    python scripts/newsletter.py --pro-rubrik 3   # ein Entwurf, drei je Rubrik
    python scripts/newsletter.py --topthema 82129
    python scripts/newsletter.py --ohne-auszuege  # "Aus der aktuellen Ausgabe" lassen

**Zwei Entwuerfe, nicht einer.** `--pro-rubrik 0,6` - und so steht es im
Workflow - legt zwei Fassungen derselben Ausgabe nebeneinander: Vorschlag 1
mit allem, was seit der letzten Ausgabe nicht versandt wurde, Vorschlag 2 mit
hoechstens sechs Meldungen je Rubrik. Anke Heiser waehlt aus, welche sie
weiterbearbeitet, und loescht die andere. Verabredet am 13.09.2026 auf zwei
Monate Probe; danach faellt die Entscheidung fuer eine der beiden Zahlen.

**Woher das Skript weiss, was schon versandt wurde:** Es liest die letzten vier
versendeten Kampagnen und zieht die News-Adressen daraus. Keine Merkdatei, die
verrutschen kann - und mit einer nuetzlichen Nebenwirkung: Was die Redaktion
aus einem Entwurf herauswirft, gilt nicht als versandt und steht beim naechsten
Mal wieder zur Auswahl. Nur was wirklich hinausging, faellt weg.

Der Entwurf entsteht als **Kopie der letzten Ausgabe** (Mailchimps replicate).
Nur so bleiben zwei Dinge erhalten, die die API nicht setzen kann: die
ausgeblendeten Rubriken (eFirst, Innovation, Pandemie) und das Werbebanner.
Das Banner wandert damit unveraendert aus der Vorausgabe mit - Buchungen kennt
das Skript nicht, und ein falsches Banner faellt eher auf als ein fehlendes.
Der Bericht am Ende sagt es jedes Mal dazu.

Geheimnisse in der Umgebung:
    MAILCHIMP_API_KEY   bzw. KNOWLEDGEHUBSMC (im Workflow so benannt)

WordPress wird nur lesend und ohne Anmeldung angefragt - der Newsletter
enthaelt ausschliesslich veroeffentlichte Beitraege.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BERLIN = ZoneInfo("Europe/Berlin")
KENNUNG = "MVF-Newsletter/1.0 (Redaktion Monitor Versorgungsforschung)"
WP = "https://www.monitor-versorgungsforschung.de/wp-json/wp/v2"

# Die Zielgruppe des Verlags und die Vorlage der Ausgabe. Beides bringt
# replicate ohnehin mit; hier steht es zur Kontrolle und fuer den PUT.
LISTE = "1c8fc10ec7"
VORLAGE = 10000489

# Die Rubriken des Newsletters in der Reihenfolge, in der sie in der Vorlage
# stehen. Links der Bereich der Mailchimp-Vorlage, rechts das Schlagwort der
# Newsseite. Ermittelt am 13.09.2026 mit einer Sonde: ein Entwurf, in dem jeder
# Bereich seinen eigenen Merker trug. Die Ueberschriften stehen fest in der
# Vorlage - eine Rubrik umbenennen kann nur der Mailchimp-Baukasten.
#
# Drei weitere Rubriken hat die Vorlage, sie sind seit Langem ausgeblendet:
# repeat_2 eFirst, repeat_8 Innovation, repeat_9 Pandemie. Sie bleiben
# ausgeblendet, weil der Entwurf eine Kopie ist.
RUBRIKEN = [
    ("repeat_3",  "Gesundheitspolitik",             1041),
    ("repeat_4",  "Digitalisierung & Datennutzung", 1037),
    ("repeat_5",  "Versorgungsmanagement",          1046),
    ("repeat_6",  "Studien",                        1039),
    ("repeat_7",  "Indikationen",                   1044),
    ("repeat_10", "Pflege",                         2116),
    ("repeat_11", "Personalien",                    1040),
]

# Rubrik News. Die Tagesnews ueber die Knowledge-Hubs liegen in derselben
# Rubrik, tragen aber "Wissen" oder "Knowledge-Hubs" - sie gehoeren nicht in
# den Newsletter, der Hub-Newsletter meldet sie schon.
NEWS_RUBRIK = 1000
NICHT = {2924, 2923}

# Das Bild in einer Meldung ist kein Bild, sondern ein Zaehlpixel: die Adresse
# des Artikels mit ?iActionPost. Wer das weglaesst, nimmt der Redaktion die
# Reichweitenmessung - ohne dass im Newsletter etwas fehlte.
BILD = ('<img alt="" class="nofloat" src="{url}?iActionPost" style="outline: none;'
        'text-decoration: none;-ms-interpolation-mode: bicubic;width: 170px;'
        'max-width: none;float: none;clear: both;display: inline;padding: 15px 0;">')
BILD_TOP = ('<img alt="" class="nofloat" src="{url}?iActionPost" style="outline: none;'
            'text-decoration: none;-ms-interpolation-mode: bicubic;width: 170px;'
            'max-width: none;float: none;clear: both;display: inline;padding: 15px 0;" '
            'width="170">')
WEITER = ('<a href="{url}" style="color:#866726 !important;text-decoration:none;'
          'font-weight:bold;" target="_blank">Weiterlesen</a>')
WEITER_TOP = ('<a href="{url}" style="color:#fff !important;text-decoration:none;'
              'font-weight:bold;font-family:Helvetica, Arial, sans-serif;'
              'font-size:13px;" target="_blank">Weiterlesen</a>')

# Das Aufzaehlungszeichen der Auszuege - dieselbe Grafik wie bisher.
PUNKT = ("https://gallery.mailchimp.com/f4c91757bc7d8c740641acb50/images/"
         "caf23823-9617-4ed7-b5aa-69d5ddc4c0e7.jpg")

# Absichtlich ohne Zeilenende: Die Entwuerfe heissen "MVF Newsletter 2026-19
# (Vorschlag 1 - alles)". Wird einer davon ohne Umbenennen versendet, findet
# ihn die Zaehlung der naechsten Ausgabe trotzdem wieder.
AUSGABE_MUSTER = re.compile(r"^MVF Newsletter (\d{4})-(\d+)\b")


# --------------------------------------------------------------------------
# Mailchimp
# --------------------------------------------------------------------------

def mc_schluessel() -> str:
    for name in ("MAILCHIMP_API_KEY", "KNOWLEDGEHUBSMC"):
        wert = os.environ.get(name)
        if wert:
            return wert.strip()
    raise SystemExit("MAILCHIMP_API_KEY (oder KNOWLEDGEHUBSMC) fehlt in der Umgebung.")


def mc(pfad: str, params: dict | None = None, method: str = "GET",
       body: dict | None = None) -> dict:
    schluessel = mc_schluessel()
    rechenzentrum = schluessel.rsplit("-", 1)[-1]
    url = f"https://{rechenzentrum}.api.mailchimp.com/3.0{pfad}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    daten = json.dumps(body).encode("utf-8") if body is not None else None
    anfrage = urllib.request.Request(url, data=daten, method=method)
    anfrage.add_header("Authorization", "Basic " + base64.b64encode(
        f"any:{schluessel}".encode()).decode())
    anfrage.add_header("Content-Type", "application/json")
    anfrage.add_header("User-Agent", KENNUNG)
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as antwort:
            roh = antwort.read()
    except urllib.error.HTTPError as fehler:
        text_ = fehler.read().decode("utf-8", "replace")[:600]
        raise SystemExit(f"Mailchimp {fehler.code} bei {method} {pfad}: {text_}")
    return json.loads(roh) if roh else {}


def kampagnen(status: str, anzahl: int = 60) -> list[dict]:
    antwort = mc("/campaigns", {"count": anzahl, "status": status,
                                "sort_field": "create_time", "sort_dir": "DESC"})
    return antwort.get("campaigns", [])


def ausgaben() -> list[dict]:
    """Die versendeten MVF-Newsletter, neueste zuerst. Resends zaehlen nicht:
    Sie heissen "Resend: ..." und tragen denselben Inhalt."""
    treffer = []
    for kampagne in kampagnen("sent", 200):
        titel = (kampagne.get("settings") or {}).get("title") or ""
        passt = AUSGABE_MUSTER.match(titel)
        if passt:
            treffer.append({"id": kampagne["id"],
                            "jahr": int(passt.group(1)),
                            "nummer": int(passt.group(2)),
                            "gesendet": kampagne.get("send_time") or "",
                            "titel": titel})
    treffer.sort(key=lambda k: k["gesendet"], reverse=True)
    return treffer


def offener_entwurf() -> dict | None:
    for status in ("save", "schedule", "paused"):
        for kampagne in kampagnen(status, 60):
            titel = (kampagne.get("settings") or {}).get("title") or ""
            if AUSGABE_MUSTER.match(titel):
                return {"id": kampagne["id"], "titel": titel, "status": status}
    return None


def versandte_adressen(ausgaben_liste: list[dict], wieviele: int) -> set[str]:
    """Die News-Kurznamen der letzten Ausgaben. Mehr als vier braucht es nicht:
    Beruecksichtigt werden nur Meldungen der letzten Wochen, und die koennen
    hoechstens in den letzten beiden Ausgaben gestanden haben."""
    adressen: set[str] = set()
    for ausgabe in ausgaben_liste[:wieviele]:
        inhalt = mc(f"/campaigns/{ausgabe['id']}/content")
        for gefunden in re.finditer(
                r"monitor-versorgungsforschung\.de/news/([a-z0-9\-]+)/",
                inhalt.get("html") or ""):
            adressen.add(gefunden.group(1))
    return adressen


# --------------------------------------------------------------------------
# WordPress
# --------------------------------------------------------------------------

def wp(pfad: str, params: dict) -> list[dict]:
    url = f"{WP}/{pfad}?" + urllib.parse.urlencode(params)
    anfrage = urllib.request.Request(url, headers={"User-Agent": KENNUNG})
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:
        return json.loads(antwort.read())


def nurtext(roh: str) -> str:
    sauber = html.unescape(re.sub(r"<[^>]+>", " ", roh or ""))
    return re.sub(r"\s+", " ", sauber.replace("\xa0", " ")).strip()


def vorspann(beitrag: dict) -> str:
    """Der Vorspann einer Meldung.

    `excerpt.rendered` liefert WordPress bei laengeren Vorspaennen gekuerzt -
    mit Auslassungszeichen mitten im Satz. Auf der Artikelseite steht er
    vollstaendig in `<p class="postExcerpt">`; von dort holt das Skript ihn
    nach. Genau diesen Text hat die Redaktion bisher von Hand kopiert.
    """
    kurz = nurtext(beitrag.get("excerpt", {}).get("rendered", ""))
    if kurz and not kurz.rstrip().endswith(("…", "...")):
        return kurz
    try:
        anfrage = urllib.request.Request(beitrag["link"], headers={"User-Agent": KENNUNG})
        with urllib.request.urlopen(anfrage, timeout=60) as antwort:
            seite = antwort.read().decode("utf-8", "replace")
        gefunden = re.search(r'<p class="postExcerpt"[^>]*>(.*?)</p>', seite, re.S)
        if gefunden:
            voll = nurtext(gefunden.group(1))
            if voll:
                return voll
    except Exception as fehler:                  # Netz, Schutz-Plugin, Umbau
        print(f"  Hinweis: Vorspann von {beitrag['link']} nicht lesbar ({fehler})")
    return kurz


def neue_meldungen(tage: int) -> list[dict]:
    seit = (dt.datetime.now(BERLIN) - dt.timedelta(days=tage)).strftime("%Y-%m-%dT%H:%M:%S")
    gesammelt: list[dict] = []
    seite = 1
    while True:
        try:
            teil = wp("posts", {"categories": NEWS_RUBRIK, "per_page": 100, "page": seite,
                                "after": seit, "orderby": "date", "order": "desc",
                                "_fields": "id,date,slug,link,title,excerpt,tags"})
        except urllib.error.HTTPError as fehler:
            if fehler.code == 400:               # keine weitere Seite
                break
            raise
        if not teil:
            break
        gesammelt += teil
        if len(teil) < 100:
            break
        seite += 1
    return gesammelt


# --------------------------------------------------------------------------
# Zusammenstellen
# --------------------------------------------------------------------------

def einordnen(beitraege: list[dict], versandt: set[str]) -> dict[int, list[dict]]:
    """Jede Meldung landet in genau einer Rubrik - in der ersten, die zu ihren
    Schlagwoertern passt. Traegt eine Meldung "Digitalisierung" und "Studie",
    stuende sie sonst zweimal im Newsletter."""
    faecher: dict[int, list[dict]] = {tag: [] for _, _, tag in RUBRIKEN}
    for beitrag in beitraege:
        schlagwoerter = set(beitrag.get("tags") or [])
        if schlagwoerter & NICHT or beitrag["slug"] in versandt:
            continue
        for _, _, tag in RUBRIKEN:
            if tag in schlagwoerter:
                faecher[tag].append(beitrag)
                break
    return faecher


def kappen(faecher: dict[int, list[dict]], grenze: int) -> dict[int, list[dict]]:
    """Null heisst: alles, was noch nicht versandt wurde."""
    if grenze <= 0:
        return {tag: list(liste) for tag, liste in faecher.items()}
    return {tag: liste[:grenze] for tag, liste in faecher.items()}


def kuerzen(titel: str, grenze: int = 60) -> str:
    """Fuer die Betreffzeile: der Teil vor dem Doppelpunkt, wenn er fuer sich
    steht. So entsteht aus "Halbjahresbilanz der GKV entlarvt Panikmache:
    Krankenkassen erwirtschaften Milliarden-Ueberschuss" dieselbe Zeile, die
    auch die Redaktion gewaehlt hat."""
    kopf = titel.split(": ", 1)[0]
    return kopf if 20 <= len(kopf) <= grenze else titel


def auszuege_bauen(anzahl: int = 3) -> tuple[str, list[str]]:
    artikel = wp("abstract", {"per_page": anzahl, "orderby": "date", "order": "desc",
                              "_fields": "id,date,slug,link,title,excerpt"})
    zeilen, namen = [], []
    for eintrag in artikel:
        titel = nurtext(eintrag["title"]["rendered"])
        anriss = nurtext(eintrag.get("excerpt", {}).get("rendered", ""))
        namen.append(titel)
        zeilen.append(
            '\t<li><a href="' + html.escape(eintrag["link"]) + '" target="_blank">'
            '<strong>' + html.escape(titel) + ':</strong></a><strong> </strong> '
            + html.escape(anriss) + "</li>\n\t<br>")
    liste = ('<ul style="list-style-type:square;list-style-image:url(\''
             + PUNKT + "');\"><br>\n" + "\n".join(zeilen) + "\n</ul>")
    return liste, namen


def bereiche_bauen(topthema: dict, top_vorspann: str,
                   faecher: dict[int, list[dict]],
                   vorspaenne: dict[int, str], nummer: int) -> dict:
    """Die Bereiche der Vorlage. `newsitem_title` ist - anders als der Name
    vermuten laesst - die Ueberschrift des Aufmachers; die Ueberschriften der
    einzelnen Meldungen stecken in den Wiederholungen."""
    bereiche: dict[str, object] = {
        "title": f"Newsletterausgabe {nummer}",
        "newsitem_title": nurtext(topthema["title"]["rendered"]),
        "topthema_image": BILD_TOP.format(url=topthema["link"]),
        "topthema_content": html.escape(top_vorspann),
        "topthema_url": WEITER_TOP.format(url=topthema["link"]),
    }
    for bereich, _name, tag in RUBRIKEN:
        eintraege = []
        for beitrag in faecher[tag]:
            eintraege.append({
                "newsitem_title": nurtext(beitrag["title"]["rendered"]),
                "newsitem_image": BILD.format(url=beitrag["link"]),
                "newsitem_content": (html.escape(vorspaenne[beitrag["id"]]) + "<br>\n"
                                     + WEITER.format(url=beitrag["link"])),
            })
        bereiche[bereich] = eintraege
    return bereiche


# --------------------------------------------------------------------------

def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Legt den naechsten MVF-Newsletter als Entwurf in Mailchimp an.")
    zerleger.add_argument("--trocken", action="store_true",
                          help="nur zeigen, was hineinkaeme - nichts anlegen")
    zerleger.add_argument("--immer", action="store_true",
                          help="Torwaechter uebergehen (Wochentag, Abstand, offener Entwurf)")
    zerleger.add_argument("--tage", type=int, default=21,
                          help="wie weit zurueck nach neuen Meldungen gesucht wird (Vorgabe 21)")
    zerleger.add_argument("--pro-rubrik", default="0,6",
                          help="hoechstens so viele Meldungen je Rubrik, 0 = alle. "
                               "Mehrere Zahlen mit Komma ergeben mehrere Entwuerfe "
                               "(Vorgabe 0,6)")
    zerleger.add_argument("--abstand", type=int, default=10,
                          help="Mindestabstand in Tagen zur letzten Ausgabe (Vorgabe 10)")
    zerleger.add_argument("--topthema", type=int, default=0,
                          help="Beitragsnummer des Aufmachers (Vorgabe: neueste Gesundheitspolitik)")
    zerleger.add_argument("--ohne-auszuege", action="store_true",
                          help="'Aus der aktuellen Ausgabe' unveraendert aus der "
                               "Vorausgabe uebernehmen statt neu zu bauen")
    zerleger.add_argument("--rueckblick", type=int, default=4,
                          help="wie viele versendete Ausgaben nach schon Versandtem durchsucht werden")
    argumente = zerleger.parse_args()

    try:
        grenzen = [int(teil) for teil in argumente.pro_rubrik.split(",") if teil.strip()]
    except ValueError:
        return zerleger.error("--pro-rubrik erwartet Zahlen, etwa 3 oder 0,6")
    if not grenzen:
        return zerleger.error("--pro-rubrik braucht mindestens eine Zahl")

    heute = dt.datetime.now(BERLIN)
    print(f"MVF-Newsletter, Stand {heute:%d.%m.%Y %H:%M} Uhr\n")

    letzte = ausgaben()
    if not letzte:
        print("Keine versendete Ausgabe 'MVF Newsletter JJJJ-NN' gefunden - "
              "ohne Vorlage zum Kopieren kann das Skript nichts anlegen.")
        return 1
    vorausgabe = letzte[0]
    gesendet = dt.datetime.fromisoformat(vorausgabe["gesendet"]).astimezone(BERLIN)
    seither = (heute - gesendet).days
    print(f"Letzte Ausgabe: {vorausgabe['titel']}, versandt am "
          f"{gesendet:%d.%m.%Y} - das ist {seither} Tage her.")

    # Torwaechter. Drei Bedingungen, damit ein taeglicher Lauf hoechstens alle
    # zwei Wochen etwas anlegt: kein offener Entwurf, Abstand gewahrt, und
    # Montag - oder die Ausgabe ist ohnehin ueberfaellig. Der letzte Punkt
    # faengt ab, dass GitHubs Cron einen Montag ausfallen laesst; das ist im
    # August 2026 zweimal vorgekommen, siehe mvf-server/LIESMICH.md.
    if not argumente.immer:
        offen = offener_entwurf()
        if offen:
            print(f"Es liegt schon ein Entwurf: {offen['titel']} ({offen['status']}). "
                  "Nichts angelegt.")
            return 0
        if seither < argumente.abstand:
            print(f"Noch keine {argumente.abstand} Tage seit der letzten Ausgabe. "
                  "Nichts angelegt.")
            return 0
        if heute.weekday() != 0 and seither < 14:
            print("Heute ist nicht Montag und die Ausgabe ist noch nicht "
                  "ueberfaellig. Nichts angelegt.")
            return 0

    print(f"\nDurchsuche die letzten {argumente.rueckblick} Ausgaben nach schon "
          "versandten Meldungen ...")
    versandt = versandte_adressen(letzte, argumente.rueckblick)
    print(f"  {len(versandt)} Meldungen sind bereits hinausgegangen.")

    print(f"Hole Meldungen der letzten {argumente.tage} Tage von der Newsseite ...")
    beitraege = neue_meldungen(argumente.tage)
    print(f"  {len(beitraege)} Beitraege in der Rubrik News.")

    faecher = einordnen(beitraege, versandt)
    gesamt = sum(len(e) for e in faecher.values())
    if not gesamt:
        print("\nKeine neue Meldung, die noch nicht versandt waere. Nichts angelegt.")
        return 0

    # Aufmacher: entweder der genannte Beitrag oder die neueste Meldung der
    # ersten Rubrik, die etwas hergibt. Er faellt aus seiner Rubrik heraus,
    # sonst stuende er zweimal im Newsletter.
    topthema = None
    if argumente.topthema:
        for tag in list(faecher):
            for beitrag in faecher[tag]:
                if beitrag["id"] == argumente.topthema:
                    topthema = beitrag
                    faecher[tag].remove(beitrag)
                    break
            if topthema:
                break
        if not topthema:
            print(f"Beitrag {argumente.topthema} ist unter den neuen Meldungen "
                  "nicht dabei - nehme die Vorgabe.")
    if not topthema:
        for _, _, tag in RUBRIKEN:
            if faecher[tag]:
                topthema = faecher[tag].pop(0)
                break

    print(f"\nZur Auswahl stehen {gesamt} Meldungen:\n")
    print(f"  Aufmacher: {nurtext(topthema['title']['rendered'])}")
    for _, name, tag in RUBRIKEN:
        anzahl = len(faecher[tag])
        if anzahl:
            print(f"  {name}: {anzahl}")
            for beitrag in faecher[tag][:6]:
                print(f"    - {beitrag['date'][:10]}  "
                      f"{nurtext(beitrag['title']['rendered'])[:74]}")
            if anzahl > 6:
                print(f"    ... und {anzahl - 6} weitere")
        else:
            print(f"  {name}: nichts Neues")

    nummer = vorausgabe["nummer"] + 1
    jahr = vorausgabe["jahr"]
    if heute.year > jahr:                        # Jahreswechsel: wieder bei 01
        jahr, nummer = heute.year, 1

    kopfzeilen = [kuerzen(nurtext(topthema["title"]["rendered"]))]
    for _, _, tag in RUBRIKEN:
        if len(kopfzeilen) >= 3:
            break
        if faecher[tag]:
            kopfzeilen.append(kuerzen(nurtext(faecher[tag][0]["title"]["rendered"])))
    betreff = " | ".join(kopfzeilen)
    print(f"\n  Betreff beider Entwuerfe: {betreff}" if len(grenzen) > 1
          else f"\n  Betreff: {betreff}")

    # Die Vorspaenne kosten je Meldung einen Seitenabruf. Sie werden einmal
    # geholt und fuer alle Entwuerfe benutzt - der kleinere ist eine Teilmenge
    # des groesseren.
    print("\nHole die Vorspaenne ...")
    top_vorspann = vorspann(topthema)
    noetig = {beitrag["id"]: beitrag
              for grenze in grenzen
              for liste in kappen(faecher, grenze).values()
              for beitrag in liste}
    vorspaenne = {kennung: vorspann(beitrag) for kennung, beitrag in noetig.items()}
    print(f"  {len(vorspaenne)} Vorspaenne.")

    auszug_namen: list[str] = []
    auszug_liste = ""
    if not argumente.ohne_auszuege:
        auszug_liste, auszug_namen = auszuege_bauen()

    if argumente.trocken:
        for laufnummer, grenze in enumerate(grenzen, 1):
            teil = kappen(faecher, grenze)
            print(f"\n  Vorschlag {laufnummer} ({beschriftung(grenze)}): "
                  f"{sum(len(e) for e in teil.values())} Meldungen")
        print("\n--trocken: nichts angelegt.")
        return 0

    rechenzentrum = mc_schluessel().rsplit("-", 1)[-1]
    angelegt = []
    for laufnummer, grenze in enumerate(grenzen, 1):
        teil = kappen(faecher, grenze)
        name = f"MVF Newsletter {jahr}-{nummer:02d}"
        if len(grenzen) > 1:
            name += f" (Vorschlag {laufnummer} - {beschriftung(grenze)})"

        bereiche = bereiche_bauen(topthema, top_vorspann, teil, vorspaenne, nummer)
        if auszug_liste:
            bereiche["auszug_text_2"] = auszug_liste

        print(f"\nKopiere {vorausgabe['titel']} fuer {name} ...")
        neu = mc(f"/campaigns/{vorausgabe['id']}/actions/replicate", method="POST")
        kennung = neu["id"]
        mc(f"/campaigns/{kennung}", method="PATCH",
           body={"settings": {"title": name, "subject_line": betreff,
                              "from_name": "Monitor Versorgungsforschung | Newsletter",
                              "reply_to": "cms@m-vf.de"}})
        mc(f"/campaigns/{kennung}/content", method="PUT",
           body={"template": {"id": VORLAGE, "sections": bereiche}})
        angelegt.append((name, kennung, teil))
        print(f"  {sum(len(e) for e in teil.values())} Meldungen  ->  "
              f"https://{rechenzentrum}.admin.mailchimp.com"
              f"/campaigns/edit?id={kennung}")

    print("\n" + "-" * 70)
    print(f"Angelegt: {len(angelegt)} Entwurf" + ("" if len(angelegt) == 1 else "e")
          + f" fuer Ausgabe {jahr}-{nummer:02d}")
    print(f"Aufmacher: {nurtext(topthema['title']['rendered'])[:70]}")
    print("\nWas die Redaktion noch selbst pruefen muss:")
    print("  - Das Werbebanner stammt unveraendert aus der Vorausgabe.")
    print("  - Ebenso der Titelkopf. Er wechselt nur mit der Druckausgabe;")
    print("    den neuen baut 'python scripts/newsletter_kopf.py NN-JJJJ',")
    print("    eingesetzt wird er von Hand im Baukasten.")
    if auszug_namen:
        print("  - 'Aus der aktuellen Ausgabe' neu gesetzt - Langtitel, "
              "die bisher von Hand gekuerzt wurden:")
        for titel in auszug_namen:
            print(f"      {titel[:72]}")
    else:
        print("  - 'Aus der aktuellen Ausgabe' steht noch auf der Vorausgabe.")
    for name, _kennung, teil in angelegt:
        leer = [rubrik for _, rubrik, tag in RUBRIKEN if not teil[tag]]
        if leer:
            print(f"  - {name}: leere Rubriken ausblenden: {', '.join(leer)}")
    if len(angelegt) > 1:
        print("  - Zwei Fassungen zur Probe: die nicht gewaehlte bitte loeschen,")
        print("    sonst haelt der Torwaechter die naechste Ausgabe auf.")
    print("  - Die Ausgabennummer ist fortgezaehlt, nicht nachgerechnet.")
    print("  - Versendet wird von Hand, in Mailchimp.")
    return 0


def beschriftung(grenze: int) -> str:
    return "alles" if grenze <= 0 else f"{grenze} je Rubrik"


if __name__ == "__main__":
    raise SystemExit(main())
