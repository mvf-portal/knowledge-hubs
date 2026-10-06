#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kloepfers woechentliche PDF-Lieferung sichten und zur Entscheidung vorlegen.

Albrecht Kloepfer (iX-Media) schickt jede Woche die "iX-Highlights
Service-Dateien" - verteilt auf mehrere Mails, zusammen rund achtzehn PDFs:
Gesetzentwuerfe, Stellungnahmen, Gutachten, Studien, Pressemitteilungen.
Gemessen am Bestand seit Juni 2026: 326 PDFs in 67 Mails.

Dieses Skript nimmt die Sichtung ab, nicht die Entscheidung.

    python scripts/kloepfer.py ernten        # Mails leeren, PDFs sichten
    python scripts/kloepfer.py uebersicht    # nur die Seite neu bauen

Was dabei entsteht, liegt unter
`OneDrive - eRelation AG\\Kloepfer\\<Kalenderwoche>`:

    00-neu\\               frisch eingetroffen, noch nicht entschieden
    wichtig-ausfuehrlich\\ }
    wichtig-lang\\         } hierhin ziehen, was eine Meldung werden soll -
    wichtig-mittel\\       } der Ordner bestimmt die Laenge
    wichtig-kurz\\         }
    sichern\\              aufheben, aber nicht schreiben
    papierkorb\\           weg damit
    uebersicht.html       die Liste zum Lesen
    sichtung.json         was das Modell zu jedem PDF gesagt hat

**Die Entscheidung faellt im Explorer**, durch Verschieben. Das ist absichtlich
so: Es braucht keinen laufenden Dienst, funktioniert von jedem Geraet ueber
OneDrive, und die Redaktion kann es ohne Einweisung. Stufe 2 liest spaeter aus,
was in welchem Ordner gelandet ist.

Geheimnisse in der Umgebung wie bei pressemeldung.py:
    KNOWLEDGEHUBS    Anthropic-Schluessel
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pressemeldung as pm                                      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTLOOK_ORDNER = "KloepfersInput"
# Kloepfers eigener Wochenrueckblick ("iX-Highlights 39. KW 2026.pdf") liegt
# der Lieferung bei. Er ist seine redaktionelle Leistung, nicht unsere Quelle -
# die Servicedateien tragen eine fuehrende Nummer, der Rueckblick nicht.
NICHT_ERNTEN = re.compile(r"(?i)^\s*ix[- ]highlights")
FAECHER = ["00-neu", "wichtig-ausfuehrlich", "wichtig-lang", "wichtig-mittel",
           "wichtig-kurz", "sichern", "papierkorb"]
# Die Laengen, die Stufe 2 aus dem Ordnernamen liest. Obergrenzen, keine
# Vorgaben: Gibt eine zweiseitige Stellungnahme nur 4.000 Zeichen her, werden
# es 4.000. Gestreckte Texte erfinden.
LAENGEN = {"wichtig-ausfuehrlich": 15000, "wichtig-lang": 10000,
           "wichtig-mittel": 5000, "wichtig-kurz": 2000}

# Zum Sichten genuegt das kleine Modell - es soll einordnen, nicht schreiben.
SICHT_MODELL = os.environ.get("SICHTMODELL", "claude-haiku-4-5-20251001")
# Nur die sieben Schlagwoerter, aus denen sich der Newsletter speist
# (newsletter.py, RUBRIKEN). "Vermischtes" und "Termine" fallen heraus - sie
# kaemen nie in den Newsletter.
SCHLAGWOERTER = {
    "Gesundheitspolitik": 1041,
    "Digitalisierung": 1037,
    "Versorgungsmanagement": 1046,
    "Studie": 1039,
    "Indikationen": 1044,
    "Pflege": 2116,
    "Personalie": 1040,
}

SICHT_SYSTEM = (
    "Du sichtest Dokumente für die Redaktion von Monitor Versorgungsforschung, "
    "einem Fachmagazin für Versorgungsforschung. Die Leserschaft arbeitet im "
    "deutschen Gesundheitswesen: Kliniken, Praxen, Kostenträger, "
    "Selbstverwaltung, Politik.\n"
    "Du urteilst nüchtern und ohne Werbesprache. Was ein Dokument wert ist, "
    "entscheidet sich an der Frage: Erfährt diese Leserschaft hier etwas, das "
    "ihre Arbeit berührt - eine Regeländerung, Zahlen zur Versorgung, eine "
    "Position, die Gewicht hat? Ein Papier ohne neue Aussage ist auch dann "
    "gering relevant, wenn es von einem großen Absender kommt.\n"
    "Schreibe durchgehend korrekte deutsche Rechtschreibung mit Umlauten "
    "(ä, ö, ü, ß) - niemals die Ersatzschreibung ae, oe, ue, ss."
)

SICHT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["titel", "art", "absender", "worum", "relevanz",
                 "begruendung", "schlagwort", "bildrechte"],
    "properties": {
        "titel": {"type": "string"},
        "art": {"type": "string",
                "enum": ["Gesetzentwurf", "Stellungnahme", "Gutachten",
                         "Studie", "Pressemitteilung", "Positionspapier",
                         "Statistik", "Sonstiges"]},
        "absender": {"type": "string"},
        "worum": {"type": "string"},
        "relevanz": {"type": "string", "enum": ["hoch", "mittel", "gering"]},
        "begruendung": {"type": "string"},
        "schlagwort": {"type": "string", "enum": sorted(SCHLAGWOERTER)},
        "bildrechte": {"type": "string",
                       "enum": ["CC-BY", "Pressematerial", "unklar"]},
        "empfohlene_laenge": {"type": "string",
                              "enum": ["ausfuehrlich", "lang", "mittel",
                                       "kurz", "keine"]},
    },
}


# ----------------------------------------------------------------- Ablage
def stammordner() -> pathlib.Path:
    """Wohin die Lieferung wandert - neben die Pressemeldungen."""
    eigen = os.environ.get("KLOEPFER_ABLAGE", "").strip()
    if eigen:
        return pathlib.Path(eigen)
    return pm.ablageordner().with_name("Kloepfer")


def kalenderwoche(betreff: str, empfangen) -> str:
    """Die KW aus dem Betreff - sonst aus dem Empfangsdatum.

    Kloepfer schreibt "40.KW 2026", manchmal "29. /30.KW 2026" und einmal
    "39.KW" ohne Jahr. Die erste Zahl genuegt; das Jahr kommt notfalls vom
    Zeitstempel.
    """
    jahr = str(empfangen)[:4]
    treffer = re.search(r"(\d{1,2})\s*\.?\s*/?\s*(?:\d{1,2}\s*\.?)?\s*KW",
                        betreff, re.I)
    if treffer:
        return f"{jahr}-KW{int(treffer.group(1)):02d}"
    kw = datetime.date.fromisoformat(str(empfangen)[:10]).isocalendar()[1]
    return f"{jahr}-KW{kw:02d}"


def faecher_anlegen(woche: pathlib.Path) -> None:
    for name in FAECHER:
        (woche / name).mkdir(parents=True, exist_ok=True)


def sauberer_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return name[:120] or "dokument.pdf"


def abdruck(rohdaten: bytes) -> str:
    return hashlib.sha256(rohdaten).hexdigest()[:16]


def sichtung_laden(woche: pathlib.Path) -> dict:
    try:
        return json.loads((woche / "sichtung.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def sichtung_schreiben(woche: pathlib.Path, daten: dict) -> None:
    (woche / "sichtung.json").write_text(
        json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")


# ---------------------------------------------------------------- Sichten
def sichten(text: str, dateiname: str, seiten: int) -> dict:
    """Ein PDF einordnen: worum geht es, lohnt sich eine Meldung?"""
    import anthropic

    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt - nichts gesichtet.")

    auftrag = (
        f"Dateiname: {dateiname}\nUmfang: {seiten} Seiten\n\n"
        "Sichte dieses Dokument:\n"
        "- titel: worum es geht, eine Zeile, höchstens 80 Zeichen. Nicht der "
        "Dateiname, sondern die Sache.\n"
        "- art: die Gattung des Dokuments.\n"
        "- absender: wer es herausgibt (Verband, Behörde, Institut, Firma).\n"
        "- worum: drei Sätze. Was steht drin, welche Zahlen, welche Forderung "
        "oder Änderung. Konkret, mit Zahl, wenn eine da ist.\n"
        "- relevanz: hoch, mittel oder gering für diese Leserschaft.\n"
        "- begruendung: ein Satz, warum.\n"
        "- schlagwort: eines aus der Hausliste.\n"
        "- bildrechte: Steht im Dokument eine Lizenz wie CC BY oder ein "
        "Hinweis 'Abdruck honorarfrei', ist es CC-BY beziehungsweise "
        "Pressematerial. Steht nichts dergleichen da: unklar.\n"
        "- empfohlene_laenge: Wie viel gibt das Dokument her? ausfuehrlich "
        "(rund 15.000 Zeichen) nur bei umfangreichen Gutachten mit eigenen "
        "Daten; kurz (2.000) bei knappen Stellungnahmen; keine, wenn eine "
        "Meldung nicht lohnt.\n\n"
        f"--- Dokument ---\n{text[:16000]}"
    )
    antwort = anthropic.Anthropic(api_key=schluessel).messages.create(
        model=SICHT_MODELL, max_tokens=1200, system=SICHT_SYSTEM,
        output_config={"format": {"type": "json_schema",
                                  "schema": SICHT_SCHEMA}},
        messages=[{"role": "user", "content": auftrag}])
    return json.loads(next(b.text for b in antwort.content if b.type == "text"))


# Die Einzelsichtung urteilt ueber jedes Dokument fuer sich - und vergibt
# dann 31 von 41 Mal "hoch". Das ist nicht falsch, nur nutzlos: Jedes dieser
# Papiere ist fuer sich genommen relevant. Brauchbar wird die Liste erst im
# Vergleich, deshalb sieht das Modell zum Schluss die ganze Woche auf einmal
# und bringt sie in eine Reihenfolge.
RANG_SYSTEM = (
    "Du bist Chef vom Dienst eines Fachmagazins für Versorgungsforschung und "
    "entscheidest, worüber die Redaktion diese Woche schreibt. Es ist Platz "
    "für wenige Meldungen, nicht für alle Dokumente.\n"
    "Vorn steht, was neu ist und Folgen hat: ein Kabinettsentwurf, eine "
    "Richtlinie, die ab morgen gilt, belastbare Zahlen zur Versorgung, ein "
    "Gutachten mit eigener Erhebung. Hinten steht, was erwartbar ist: die "
    "Stellungnahme eines Verbands zur eigenen Branche, eine Umfrage ohne "
    "Versorgungsbezug, ein Positionspapier, das die bekannte Position "
    "wiederholt.\n"
    "Schreibe mit Umlauten (ä, ö, ü, ß), nie in Ersatzschreibung."
)
RANG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reihenfolge"],
    "properties": {
        "reihenfolge": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["nummer", "platz", "lohnt", "warum"],
                "properties": {
                    "nummer": {"type": "integer"},
                    "platz": {"type": "integer"},
                    "lohnt": {"type": "boolean"},
                    "warum": {"type": "string"},
                },
            },
        },
    },
}


def rangfolge(woche: pathlib.Path) -> int:
    """Die Woche im Vergleich ordnen - ein Aufruf fuer die ganze Lieferung."""
    import anthropic

    daten = sichtung_laden(woche)
    brauchbar = [(datei, e) for datei, e in sorted(daten.items())
                 if not e.get("fehler")]
    if not brauchbar:
        return 0
    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt.")

    liste = []
    for nummer, (datei, e) in enumerate(brauchbar, 1):
        liste.append(
            f"{nummer}. [{e.get('art','')}, {e.get('absender','')}, "
            f"{e.get('seiten',0)} S.] {e.get('titel','')}\n"
            f"   {e.get('worum','')[:260]}")

    auftrag = (
        f"Hier sind {len(brauchbar)} Dokumente einer Wochenlieferung.\n\n"
        + "\n".join(liste) +
        "\n\nBringe sie in eine Reihenfolge:\n"
        "- nummer: die Nummer aus der Liste.\n"
        "- platz: 1 für das wichtigste, dann aufsteigend. Jede Zahl nur "
        "einmal.\n"
        "- lohnt: true nur für die Dokumente, über die diese Woche wirklich "
        "eine Meldung entstehen sollte. Als Richtschnur: etwa ein Viertel "
        "der Liste, nicht mehr.\n"
        "- warum: ein kurzer Satz, der die Platzierung trägt.\n"
        "Jedes Dokument kommt genau einmal vor."
    )
    antwort = anthropic.Anthropic(api_key=schluessel).messages.create(
        model=SICHT_MODELL, max_tokens=4000, system=RANG_SYSTEM,
        output_config={"format": {"type": "json_schema",
                                  "schema": RANG_SCHEMA}},
        messages=[{"role": "user", "content": auftrag}])
    urteil = json.loads(next(b.text for b in antwort.content
                             if b.type == "text"))

    getroffen = 0
    for eintrag in urteil.get("reihenfolge", []):
        nummer = eintrag.get("nummer", 0)
        if not 1 <= nummer <= len(brauchbar):
            continue
        datei, _ = brauchbar[nummer - 1]
        daten[datei]["platz"] = eintrag.get("platz", 99)
        daten[datei]["lohnt"] = bool(eintrag.get("lohnt"))
        daten[datei]["warum"] = str(eintrag.get("warum", ""))[:200]
        getroffen += 1
    sichtung_schreiben(woche, daten)
    lohnen = sum(1 for e in daten.values() if e.get("lohnt"))
    print(f"  {woche.name}: {getroffen} eingeordnet, {lohnen} empfohlen")
    return 0


# ---------------------------------------------------------------- Buendeln
# Oft gehoeren mehrere Dokumente einer Woche zum selben Vorgang: der
# Barmer-Arzneimittelreport und die Pressemappe dazu, das ALM-Gutachten zur
# GOAE und die Stellungnahme desselben Hauses, zwei Antworten der
# Bundesregierung zur Cannabisgesetzgebung. Wer daraus einzelne Meldungen
# macht, stellt sie unverbunden nebeneinander.
#
# Ueber Wortueberschneidung ist das nicht zu finden - gemessen am 06.10.2026:
# von vier Buendeln fand das Verfahren eines und dazu einen Fehltreffer. Also
# entscheidet das Modell, das den Sinn sieht.
BUENDEL_SYSTEM = (
    "Du ordnest die Wochenlieferung eines Fachmagazins für "
    "Versorgungsforschung. Deine Aufgabe: erkennen, welche Dokumente zum "
    "selben Vorgang gehören und deshalb in einer Meldung zusammengehören.\n"
    "Derselbe Vorgang heißt: dasselbe Gesetz, derselbe Bericht samt "
    "Pressemappe, dieselbe Auseinandersetzung, dieselbe Entscheidung. "
    "NICHT dasselbe Themenfeld - zwei Papiere über Pflege sind kein Bündel, "
    "solange sie verschiedene Vorgänge behandeln. Im Zweifel nicht bündeln: "
    "Eine zu Unrecht getrennte Meldung ist ein kleiner Schaden, eine zu "
    "Unrecht verschmolzene ein großer.\n"
    "Schreibe mit Umlauten (ä, ö, ü, ß), nie in Ersatzschreibung."
)
BUENDEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["buendel"],
    "properties": {
        "buendel": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "nummern", "warum"],
                "properties": {
                    "name": {"type": "string"},
                    "nummern": {"type": "array", "items": {"type": "integer"}},
                    "warum": {"type": "string"},
                },
            },
        },
    },
}


def ordnername(name: str) -> str:
    sauber = re.sub(r'[\\/:*?"<>|]', " ", name).strip()
    sauber = re.sub(r"\s+", " ", sauber)[:60].strip(" .")
    return f"Thema - {sauber}" if sauber else "Thema"


def buendeln(woche: pathlib.Path) -> int:
    """Dokumente desselben Vorgangs in einen Themenordner legen.

    Verschoben wird nur, was noch in 00-neu liegt - was schon entschieden
    ist, bleibt unberuehrt.
    """
    import anthropic

    daten = sichtung_laden(woche)
    offen = [(datei, e) for datei, e in sorted(daten.items())
             if not e.get("fehler") and (woche / "00-neu" / datei).exists()]
    if len(offen) < 2:
        return 0
    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt.")

    liste = []
    for nummer, (datei, e) in enumerate(offen, 1):
        liste.append(f"{nummer}. [{e.get('art','')}, {e.get('absender','')}] "
                     f"{e.get('titel','')}\n   {e.get('worum','')[:220]}")
    auftrag = (
        f"Hier sind {len(offen)} Dokumente einer Wochenlieferung.\n\n"
        + "\n".join(liste) +
        "\n\nWelche gehören zum selben Vorgang?\n"
        "- name: wie der Vorgang heißt, zwei bis fünf Wörter.\n"
        "- nummern: mindestens zwei Nummern aus der Liste. Jede Nummer "
        "höchstens einmal in der ganzen Antwort.\n"
        "- warum: ein Satz, was die Dokumente verbindet.\n"
        "Gibt es keine Bündel, antworte mit einer leeren Liste. Dokumente "
        "ohne Partner tauchen nicht auf."
    )
    antwort = anthropic.Anthropic(api_key=schluessel).messages.create(
        model=SICHT_MODELL, max_tokens=2000, system=BUENDEL_SYSTEM,
        output_config={"format": {"type": "json_schema",
                                  "schema": BUENDEL_SCHEMA}},
        messages=[{"role": "user", "content": auftrag}])
    urteil = json.loads(next(b.text for b in antwort.content
                             if b.type == "text"))

    vergeben: set[int] = set()
    gebaut = 0
    for buendel in urteil.get("buendel", []):
        nummern = [n for n in buendel.get("nummern", [])
                   if 1 <= n <= len(offen) and n not in vergeben]
        if len(nummern) < 2:
            continue
        vergeben.update(nummern)
        ordner = woche / "00-neu" / ordnername(buendel.get("name", ""))
        ordner.mkdir(exist_ok=True)
        for n in nummern:
            datei, _ = offen[n - 1]
            quelle = woche / "00-neu" / datei
            if quelle.exists():
                quelle.replace(ordner / datei)
            daten[datei]["buendel"] = ordner.name
            daten[datei]["buendel_warum"] = str(buendel.get("warum", ""))[:200]
        gebaut += 1
        print(f"  Bündel: {ordner.name} ({len(nummern)} Dokumente)")
    sichtung_schreiben(woche, daten)
    if not gebaut:
        print("  kein Bündel gefunden")
    return 0


def seitenzahl(pfad: pathlib.Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pfad)).pages)
    except Exception:
        return 0


# ----------------------------------------------------------------- Ernten
def ernten(hoechstens: int, trocken: bool) -> int:
    """Die Mails im Ordner KloepfersInput leeren und die PDFs sichten."""
    import win32com.client

    raum = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    posteingang = raum.GetDefaultFolder(6)
    quelle = None
    for f in posteingang.Folders:
        if str(f.Name) == OUTLOOK_ORDNER:
            quelle = f
    if quelle is None:
        raise SystemExit(f"Outlook-Ordner {OUTLOOK_ORDNER} fehlt.")
    erledigt = None
    for f in quelle.Folders:
        if str(f.Name) == "erledigt":
            erledigt = f
    if erledigt is None:
        erledigt = quelle.Folders.Add("erledigt")

    posten = quelle.Items
    try:
        posten.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    mails = [m for m in posten]
    print(f"{len(mails)} Mail(s) in {OUTLOOK_ORDNER}")

    neu, uebersprungen, gesichtet = 0, 0, 0
    beruehrte_wochen = set()
    for mail in mails:
        try:
            if mail.Class != 43:
                continue
            betreff = str(getattr(mail, "Subject", ""))
            empfangen = mail.ReceivedTime
        except Exception:
            continue
        woche_name = kalenderwoche(betreff, empfangen)
        woche = stammordner() / woche_name
        faecher_anlegen(woche)
        beruehrte_wochen.add(woche_name)
        daten = sichtung_laden(woche)

        for anhang in mail.Attachments:
            name = str(anhang.FileName)
            if not name.lower().endswith(".pdf"):
                continue
            if NICHT_ERNTEN.match(name):
                print(f"  uebersprungen (Kloepfers Wochenrueckblick): {name}")
                continue
            if gesichtet >= hoechstens:
                print("  Obergrenze erreicht - der Rest beim naechsten Lauf.")
                break
            ziel = woche / "00-neu" / sauberer_name(name)
            # Schon einmal geholt? Dann steckt die Datei irgendwo in der
            # Woche - auch in einem Entscheidungsordner.
            if any((woche / fach / ziel.name).exists() for fach in FAECHER):
                uebersprungen += 1
                continue
            if trocken:
                print(f"  [trocken] {woche_name}: {ziel.name}")
                neu += 1
                continue
            try:
                anhang.SaveAsFile(str(ziel))
            except Exception as fehler:
                print(f"  {name}: {str(fehler)[:70]}")
                continue
            neu += 1
            kennung = abdruck(ziel.read_bytes())
            if kennung in {e.get("abdruck") for e in daten.values()}:
                print(f"  wortgleich schon da: {ziel.name}")
                ziel.unlink(missing_ok=True)
                uebersprungen += 1
                continue
            text = pm.text_aus_pdf(ziel)
            if len(text) < 600:
                print(f"  {ziel.name}: kaum Text (Scan?) - ungesichtet")
                daten[ziel.name] = {"abdruck": kennung, "seiten": seitenzahl(ziel),
                                    "fehler": "kaum Text, vermutlich ein Scan"}
                continue
            try:
                urteil = sichten(text, ziel.name, seitenzahl(ziel))
            except Exception as fehler:
                print(f"  {ziel.name}: Sichtung gescheitert "
                      f"({str(fehler)[:60]})")
                continue
            urteil["abdruck"] = kennung
            urteil["seiten"] = seitenzahl(ziel)
            urteil["zeichen"] = len(text)
            urteil["mail"] = betreff[:80]
            urteil["eingegangen"] = str(empfangen)[:10]
            daten[ziel.name] = urteil
            gesichtet += 1
            print(f"  {urteil['relevanz']:<7} {urteil['titel'][:62]}")
        if not trocken:
            sichtung_schreiben(woche, daten)
            try:
                mail.UnRead = False
                mail.Move(erledigt)
            except Exception as fehler:
                print(f"  Mail nicht verschoben: {str(fehler)[:60]}")

    global NEUE_PDFS
    NEUE_PDFS = neu
    print(f"\n{neu} neue PDFs, {gesichtet} gesichtet, "
          f"{uebersprungen} schon bekannt")
    for woche_name in sorted(beruehrte_wochen):
        if trocken:
            continue
        woche = stammordner() / woche_name
        try:
            rangfolge(woche)
        except Exception as fehler:
            print(f"  Reihenfolge gescheitert: {str(fehler)[:90]}")
        try:
            buendeln(woche)
        except Exception as fehler:
            print(f"  Buendeln gescheitert: {str(fehler)[:90]}")
        uebersicht(woche)
    return 0


# -------------------------------------------------------------- Uebersicht
def uebersicht(woche: pathlib.Path) -> pathlib.Path:
    """Die Liste zum Lesen - sortiert nach Relevanz."""
    daten = sichtung_laden(woche)
    # Auch eine Ebene tiefer nachsehen: Buendel liegen in Themenordnern.
    wo = {}
    for fach in FAECHER + ["geschrieben"]:
        for datei in (woche / fach).rglob("*.pdf"):
            eltern = datei.parent
            wo[datei.name] = (fach if eltern.name == fach
                              else f"{fach} / {eltern.name}")

    # Sortiert wird nach dem Platz aus dem Vergleich; die Einzelrelevanz ist
    # nur noch Beiwerk, weil sie fast immer "hoch" sagt.
    rang = {"hoch": 0, "mittel": 1, "gering": 2}
    zeilen = sorted(daten.items(),
                    key=lambda e: (e[1].get("platz", 99),
                                   rang.get(e[1].get("relevanz"), 3),
                                   e[1].get("titel", "")))

    farbe = {"hoch": "#1a7f37", "mittel": "#9a6700", "gering": "#8b949e"}
    teile = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>Kloepfer {woche.name}</title>",
        "<style>body{font:15px/1.55 system-ui,sans-serif;max-width:60em;"
        "margin:2em auto;padding:0 1em;color:#1f2328}"
        "h1{font-size:24px;margin-bottom:.2em}"
        ".hinweis{color:#57606a;margin-bottom:2em}"
        "article{border-top:1px solid #d8dee4;padding:1.1em 0}"
        ".kopf{display:flex;gap:.6em;align-items:baseline;flex-wrap:wrap}"
        ".rel{font-weight:600;text-transform:uppercase;font-size:12px;"
        "letter-spacing:.04em}"
        ".art{background:#eef1f4;border-radius:10px;padding:.1em .6em;"
        "font-size:12px;color:#57606a}"
        ".titel{font-weight:600;font-size:17px}"
        ".datei{font-family:ui-monospace,Consolas,monospace;font-size:12px;"
        "color:#57606a;word-break:break-all}"
        ".fach{font-size:12px;padding:.1em .6em;border-radius:10px;"
        "background:#ddf4ff;color:#0969da}"
        ".unklar{background:#fff8c5;color:#7d4e00}"
        ".platz{font:600 13px/1 system-ui;color:#57606a;min-width:1.6em}"
        ".stern{background:#1a7f37;color:#fff;border-radius:10px;"
        "padding:.1em .6em;font-size:12px;font-weight:600}"
        "article.empfohlen{background:#f6fbf7;border-left:3px solid #1a7f37;"
        "padding-left:.9em}"
        ".warum{color:#1f2328;border-left:2px solid #d8dee4;padding-left:.8em;"
        "margin:.4em 0}"
        "</style>",
        f"<h1>Kloepfer-Lieferung {woche.name}</h1>",
        f"<p class='hinweis'>{len(daten)} Dokumente. Entschieden wird im "
        "Explorer: die Datei aus <code>00-neu</code> in einen der Ordner "
        "ziehen &ndash; <code>wichtig-ausfuehrlich</code>, "
        "<code>wichtig-lang</code>, <code>wichtig-mittel</code>, "
        "<code>wichtig-kurz</code>, <code>sichern</code> oder "
        "<code>papierkorb</code>. Der Ordner bestimmt die Länge der Meldung."
        "</p>",
    ]
    for datei, e in zeilen:
        if e.get("fehler"):
            teile.append(
                f"<article><div class='kopf'><span class='rel'>?</span>"
                f"<span class='titel'>{html.escape(datei)}</span></div>"
                f"<p>{html.escape(e['fehler'])}</p></article>")
            continue
        rel = e.get("relevanz", "?")
        fach = wo.get(datei, "00-neu")
        rechte = e.get("bildrechte", "unklar")
        empfohlen = " empfohlen" if e.get("lohnt") else ""
        teile.append(
            f"<article class='{empfohlen.strip()}'>"
            f"<div class='kopf'>"
            f"<span class='platz'>{e.get('platz', '–')}</span>"
            + ("<span class='stern'>schreiben</span>" if empfohlen else "")
            + f"<span class='rel' style='color:{farbe.get(rel, '#57606a')}'>"
            f"{html.escape(rel)}</span>"
            f"<span class='titel'>{html.escape(e.get('titel', datei))}</span>"
            f"<span class='art'>{html.escape(e.get('art', ''))}</span>"
            f"<span class='art'>{html.escape(e.get('absender', ''))}</span>"
            f"<span class='art'>{e.get('seiten', 0)} S.</span>"
            f"<span class='fach'>{html.escape(fach)}</span>"
            f"</div>"
            f"<p>{html.escape(e.get('worum', ''))}</p>"
            + (f"<p class='warum'>{html.escape(e.get('warum', ''))}</p>"
               if e.get("warum") else "")
            + f"<p class='hinweis'>{html.escape(e.get('begruendung', ''))} "
            f"&middot; Schlagwort {html.escape(e.get('schlagwort', ''))} "
            f"&middot; Vorschlag: {html.escape(e.get('empfohlene_laenge', '-'))}"
            f" &middot; <span class='art"
            f"{' unklar' if rechte == 'unklar' else ''}'>"
            f"Bildrechte {html.escape(rechte)}</span></p>"
            f"<p class='datei'>{html.escape(datei)}</p>"
            "</article>")

    ziel = woche / "uebersicht.html"
    ziel.write_text("\n".join(teile) + "\n", encoding="utf-8")
    print(f"Übersicht: {ziel}")
    return ziel


# ------------------------------------------------------------- Schreiben
SCHREIB_SYSTEM = (
    "Du schreibst für die Nachrichtenseite von Monitor Versorgungsforschung, "
    "einem Fachmagazin für Versorgungsforschung. Die Leserschaft arbeitet im "
    "deutschen Gesundheitswesen: Kliniken, Praxen, Kostenträger, "
    "Selbstverwaltung, Politik. Sie ist fachkundig und hat wenig Zeit.\n"
    "Du referierst die Dokumente, du übernimmst sie nicht. Jede Wertung "
    "gehört dem, der sie geäußert hat, und wird ihm zugeschrieben "
    "('nach Einschätzung des Verbands', 'das Gutachten kommt zu dem "
    "Schluss'). Wir selbst werten nicht.\n"
    "Zahlen, Daten und Fristen bleiben exakt so, wie sie in der Quelle "
    "stehen - nichts hinzufügen, nichts runden, nichts schätzen. Was nicht "
    "in den Dokumenten steht, steht auch nicht in der Meldung: kein "
    "Hintergrundwissen, keine geläufige Formel anstelle einer knapperen "
    "Aussage.\n"
    "Liegen mehrere Dokumente zum selben Vorgang vor, wird daraus EINE "
    "Meldung: Das wichtigste führt, die übrigen liefern Gegenpositionen und "
    "Zahlen. Wer was sagt, muss erkennbar bleiben.\n"
    "Siezen. Keine Superlative, keine Werbesprache, keine leeren Wendungen. "
    "Schreibe durchgehend korrekte deutsche Rechtschreibung mit Umlauten "
    "(ä, ö, ü, ß) - niemals die Ersatzschreibung ae, oe, ue, ss."
)
SCHREIB_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["titel", "textauszug", "abschnitte", "schlagwort"],
    "properties": {
        "titel": {"type": "string"},
        "textauszug": {"type": "string"},
        "abschnitte": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["absaetze"],
                "properties": {
                    "ueberschrift": {"type": "string"},
                    "absaetze": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "quellen": {"type": "array", "items": {"type": "string"}},
        "schlagwort": {"type": "string", "enum": sorted(SCHLAGWOERTER)},
    },
}
# Wie viel Quelltext je Dokument ins Modell geht. Das fuehrende Dokument
# ausfuehrlich, die uebrigen knapper - sie liefern Positionen, nicht Substanz.
QUELLE_FUEHREND = 90000
QUELLE_WEITERE = 25000


def schreib_auftrag(stuecke: list[tuple[str, dict, str]], zeichen: int,
                    buendel: str = "") -> str:
    teile = []
    for nummer, (datei, sicht, text) in enumerate(stuecke, 1):
        grenze = QUELLE_FUEHREND if nummer == 1 else QUELLE_WEITERE
        rolle = "FÜHRENDES DOKUMENT" if nummer == 1 else "weiteres Dokument"
        teile.append(
            f"\n\n===== {rolle} {nummer}: {sicht.get('titel', datei)} =====\n"
            f"Gattung: {sicht.get('art','')}   "
            f"Herausgeber: {sicht.get('absender','')}   "
            f"Umfang: {sicht.get('seiten',0)} Seiten\n\n{text[:grenze]}")
    kopf = (
        f"Schreibe eine Meldung von höchstens {zeichen} Zeichen "
        f"(Fließtext ohne Überschriften gerechnet).\n\n"
        "**Die Zahl ist eine Obergrenze, keine Vorgabe.** Gibt das Material "
        "weniger her, schreibe weniger - lieber 4.000 belastbare Zeichen als "
        f"{zeichen} gestreckte. Strecken heißt erfinden.\n\n"
        "- titel: eine Zeile, höchstens 75 Zeichen. Die Sache steht vorn, "
        "der Absender dahinter, getrennt durch einen Doppelpunkt.\n"
        "- textauszug: zwei Sätze, höchstens 300 Zeichen. Sie stehen als "
        "Vorspann in Listen und bei Suchmaschinen und kommen im Fließtext "
        "NICHT noch einmal vor.\n"
        "- abschnitte: der Text. Je Abschnitt eine 'ueberschrift' und "
        "'absaetze'. Unter 4.000 Zeichen genügt ein Abschnitt ohne "
        "Überschrift; darüber gliedere nach Sachfragen, nicht nach "
        "Dokumenten.\n"
        "- quellen: je Dokument eine Zeile - Herausgeber, Titel, Jahr. "
        "Sie steht am Ende der Meldung.\n"
        "- schlagwort: eines aus der Hausliste.\n")
    if buendel:
        kopf += (f"\nDie Dokumente gehören zum selben Vorgang "
                 f"('{buendel}'). Daraus wird EINE Meldung, die die "
                 "Positionen gegeneinanderstellt.\n")
    return kopf + "".join(teile)


def schreiben(hoechstens: int, trocken: bool, nur_woche: str = "") -> int:
    """Was in den Laengen-Ordnern liegt, zu Entwuerfen machen."""
    import anthropic

    stamm = stammordner()
    wochen = ([stamm / nur_woche] if nur_woche
              else sorted(w for w in stamm.glob("*-KW*") if w.is_dir()))
    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt.")
    modell = os.environ.get("MODEL", "claude-opus-5")
    gemacht = 0

    for woche in wochen:
        daten = sichtung_laden(woche)
        fertig_datei = woche / "geschrieben.json"
        try:
            fertig = json.loads(fertig_datei.read_text(encoding="utf-8"))
        except Exception:
            fertig = {}
        (woche / "geschrieben").mkdir(exist_ok=True)

        for fach, zeichen in LAENGEN.items():
            ordner = woche / fach
            if not ordner.exists():
                continue
            posten = sorted(list(ordner.glob("*.pdf"))
                            + [p for p in ordner.iterdir() if p.is_dir()])
            for eintrag in posten:
                if gemacht >= hoechstens:
                    print("  Obergrenze erreicht - der Rest beim naechsten Lauf.")
                    return 0
                if eintrag.name in fertig:
                    continue
                pdfs = ([eintrag] if eintrag.is_file()
                        else sorted(eintrag.glob("*.pdf")))
                if not pdfs:
                    continue

                # Das bestplatzierte Dokument fuehrt.
                def platz(p: pathlib.Path) -> int:
                    return daten.get(p.name, {}).get("platz", 99)
                pdfs.sort(key=platz)

                stuecke = []
                for pfad in pdfs:
                    sicht = daten.get(pfad.name, {"titel": pfad.stem})
                    try:
                        text = pm.text_aus_pdf(pfad)
                    except Exception as fehler:
                        print(f"  {pfad.name}: nicht lesbar "
                              f"({str(fehler)[:50]})")
                        continue
                    stuecke.append((pfad.name, sicht, text))
                if not stuecke:
                    continue

                art = "Bündel" if eintrag.is_dir() else "Einzelstück"
                print(f"\n--- {fach} / {art}: {eintrag.name[:62]}")
                print(f"    {len(stuecke)} Dokument(e), Ziel {zeichen} Zeichen")
                auftrag = schreib_auftrag(
                    stuecke, zeichen,
                    eintrag.name if eintrag.is_dir() else "")
                try:
                    antwort = anthropic.Anthropic(
                        api_key=schluessel).messages.create(
                        model=modell, max_tokens=16000, system=SCHREIB_SYSTEM,
                        output_config={"format": {"type": "json_schema",
                                                  "schema": SCHREIB_SCHEMA}},
                        messages=[{"role": "user", "content": auftrag}])
                    meldung = json.loads(next(b.text for b in antwort.content
                                              if b.type == "text"))
                except Exception as fehler:
                    print(f"    Schreiben gescheitert: {str(fehler)[:110]}")
                    continue

                inhalt, laenge = baue_beitrag(meldung, stuecke)
                # Die Obergrenze muss halten: Der erste Durchgang lag bei der
                # Probe am 06.10.2026 um ein Drittel darueber (6.614 statt
                # 5.000). Einmal kuerzen lassen, mit der Auflage, keine Zahl
                # zu opfern.
                if laenge > zeichen * 1.1:
                    print(f"    {laenge} Zeichen - zu lang, wird gekuerzt")
                    try:
                        antwort = anthropic.Anthropic(
                            api_key=schluessel).messages.create(
                            model=modell, max_tokens=16000,
                            system=SCHREIB_SYSTEM,
                            output_config={"format": {"type": "json_schema",
                                                      "schema": SCHREIB_SCHEMA}},
                            messages=[
                                {"role": "user", "content": auftrag},
                                {"role": "assistant",
                                 "content": json.dumps(meldung,
                                                       ensure_ascii=False)},
                                {"role": "user", "content":
                                 f"Der Fließtext hat {laenge} Zeichen, erlaubt "
                                 f"sind {zeichen}. Kürze auf höchstens "
                                 f"{zeichen} Zeichen. Streiche Einordnendes "
                                 "und Wiederholungen, niemals eine Zahl, eine "
                                 "Frist oder eine Zuschreibung. Gleiches "
                                 "Format."}])
                        gekuerzt = json.loads(next(b.text for b in antwort.content
                                                   if b.type == "text"))
                        inhalt2, laenge2 = baue_beitrag(gekuerzt, stuecke)
                        if laenge2 and laenge2 <= laenge:
                            meldung, inhalt, laenge = gekuerzt, inhalt2, laenge2
                    except Exception as fehler:
                        print(f"    Kuerzen gescheitert: {str(fehler)[:80]}")
                print(f"    {meldung['titel'][:66]}")
                print(f"    {laenge} Zeichen Fließtext, Schlagwort "
                      f"{meldung.get('schlagwort','?')}")
                if trocken:
                    vorschau = woche / "geschrieben" / f"{eintrag.stem}.html"
                    vorschau.write_text(inhalt, encoding="utf-8")
                    print(f"    [trocken] Vorschau: {vorschau.name}")
                    gemacht += 1
                    continue

                bilder = bilder_sammeln(pdfs, daten)
                try:
                    angelegt = pm.entwurf(meldung, inhalt, None, False,
                                          None, bilder, "")
                except Exception as fehler:
                    print(f"    WordPress: {str(fehler)[:110]}")
                    continue
                if angelegt:
                    fertig[eintrag.name] = {"datum": dt_heute(),
                                            "titel": meldung["titel"],
                                            "zeichen": laenge}
                    ziel = woche / "geschrieben" / eintrag.name
                    try:
                        eintrag.replace(ziel)
                    except Exception:
                        pass
                    gemacht += 1
        fertig_datei.write_text(
            json.dumps(fertig, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
    print(f"\n{gemacht} Meldung(en) geschrieben.")
    return 0


def baue_beitrag(meldung: dict, stuecke: list) -> tuple[str, int]:
    """Die Meldung als HTML, dazu die Zahl der Zeichen im Fliesstext."""
    teile, laenge = [], 0
    for abschnitt in meldung.get("abschnitte", []):
        ueberschrift = (abschnitt.get("ueberschrift") or "").strip()
        if ueberschrift:
            teile.append(f"<h3>{html.escape(ueberschrift)}</h3>")
        for absatz in abschnitt.get("absaetze", []):
            if absatz.strip():
                teile.append(f"<p>{html.escape(absatz.strip())}</p>")
                laenge += len(absatz.strip())
    quellen = [q for q in meldung.get("quellen", []) if q.strip()]
    if quellen:
        teile.append("<p><strong>Quellen</strong><br>"
                     + "<br>".join(html.escape(q) for q in quellen) + "</p>")
    return "\n".join(teile), laenge


def bilder_sammeln(pdfs: list[pathlib.Path], daten: dict,
                   hoechstens: int = 3) -> list:
    """Abbildungen aus den Dokumenten - mit dem Herausgeber im Dateinamen.

    Der Name wandert in die Mediathek und traegt damit die Quelle mit; die
    Bildunterschrift im Beitrag setzt die Redaktion.
    """
    gefunden = []
    for pfad in pdfs:
        if len(gefunden) >= hoechstens:
            break
        try:
            bilder = pm.bilder_aus_pdf(pfad)
        except Exception:
            continue
        herausgeber = daten.get(pfad.name, {}).get("absender", "")
        for name, rohdaten in bilder[:hoechstens - len(gefunden)]:
            kennung = re.sub(r"[^\wäöüß -]", "", f"{herausgeber} {name}")[:80]
            gefunden.append((kennung or name, rohdaten))
    return gefunden


# ----------------------------------------------------------- Entscheiden
# Die Uebersicht war zum Lesen gebaut; entschieden wurde im Explorer. Das
# Verschieben von Hand ist aber genau der Handgriff, den niemand macht.
# Deshalb eine Seite mit Knoepfen: Ein kleiner Dienst auf dem eigenen Rechner
# nimmt den Klick entgegen und verschiebt die Datei. Kein fremder Server,
# nichts verlaesst den Rechner.
DIENST_PORT = int(os.environ.get("KLOEPFER_PORT", "8808"))
NEUE_PDFS = 0                   # wie viele PDFs der letzte Lauf geholt hat
KNOEPFE = [("wichtig-ausfuehrlich", "ausführlich", "15.000"),
           ("wichtig-lang", "lang", "10.000"),
           ("wichtig-mittel", "mittel", "5.000"),
           ("wichtig-kurz", "kurz", "2.000"),
           ("sichern", "sichern", ""),
           ("papierkorb", "weg", "")]


def offene_posten() -> list:
    """Was noch in 00-neu liegt - Einzelstuecke und Buendel."""
    posten = []
    for woche in sorted(stammordner().glob("*-KW*"), reverse=True):
        daten = sichtung_laden(woche)
        neu = woche / "00-neu"
        if not neu.exists():
            continue
        for eintrag in sorted(neu.iterdir()):
            if eintrag.is_dir():
                teile = sorted(eintrag.glob("*.pdf"))
                if not teile:
                    continue
                stuecke = [daten.get(t.name, {}) for t in teile]
                stuecke.sort(key=lambda e: e.get("platz", 99))
                erstes = stuecke[0] if stuecke else {}
                posten.append({
                    "woche": woche.name, "name": eintrag.name, "buendel": True,
                    "platz": erstes.get("platz", 99),
                    "titel": eintrag.name.replace("Thema - ", ""),
                    "worum": erstes.get("buendel_warum", ""),
                    "teile": [e.get("titel", "") for e in stuecke],
                    "absender": ", ".join(
                        dict.fromkeys(e.get("absender", "") for e in stuecke)),
                    "art": f"{len(teile)} Dokumente",
                    "seiten": sum(e.get("seiten", 0) for e in stuecke),
                    "lohnt": any(e.get("lohnt") for e in stuecke),
                    "relevanz": erstes.get("relevanz", ""),
                    "laenge": erstes.get("empfohlene_laenge", ""),
                    "rechte": erstes.get("bildrechte", "unklar")})
            elif eintrag.suffix.lower() == ".pdf":
                e = daten.get(eintrag.name, {})
                posten.append({
                    "woche": woche.name, "name": eintrag.name,
                    "buendel": False, "platz": e.get("platz", 99),
                    "titel": e.get("titel", eintrag.stem),
                    "worum": e.get("worum", ""), "teile": [],
                    "absender": e.get("absender", ""),
                    "art": e.get("art", ""), "seiten": e.get("seiten", 0),
                    "lohnt": bool(e.get("lohnt")),
                    "relevanz": e.get("relevanz", ""),
                    "laenge": e.get("empfohlene_laenge", ""),
                    "rechte": e.get("bildrechte", "unklar")})
    # Innerhalb der Woche nach Platz, die neueste Woche zuerst.
    posten.sort(key=lambda p: p["platz"])
    posten.sort(key=lambda p: p["woche"], reverse=True)
    return posten


def seite_bauen() -> str:
    posten = offene_posten()
    zeilen = []
    for nummer, p in enumerate(posten):
        knoepfe = "".join(
            f"<button data-fach='{fach}' class='k {fach}'>{beschriftung}"
            + (f"<small>{zeichen}</small>" if zeichen else "")
            + "</button>" for fach, beschriftung, zeichen in KNOEPFE)
        teile = ("<ul class='teile'>"
                 + "".join(f"<li>{html.escape(t)}</li>" for t in p["teile"])
                 + "</ul>") if p["teile"] else ""
        vorschlag = (f"<span class='vorschlag'>Vorschlag: {p['laenge']}</span>"
                     if p["laenge"] and p["laenge"] != "keine" else "")
        zeilen.append(
            f"<article id='p{nummer}' data-woche='{html.escape(p['woche'])}' "
            f"data-name=\"{html.escape(p['name'])}\" "
            f"class='{'empfohlen' if p['lohnt'] else ''}'>"
            f"<div class='kopf'>"
            f"<span class='platz'>{p['platz'] if p['platz'] < 99 else '·'}</span>"
            + ("<span class='stern'>schreiben</span>" if p["lohnt"] else "")
            + ("<span class='buendelmarke'>Bündel</span>" if p["buendel"] else "")
            + f"<h2>{html.escape(p['titel'])}</h2></div>"
            f"<div class='meta'>{html.escape(p['absender'][:70])} · "
            f"{html.escape(p['art'])} · {p['seiten']} S. · "
            f"{html.escape(p['woche'])} {vorschlag}"
            + (" · <span class='unklar'>Bildrechte unklar</span>"
               if p["rechte"] == "unklar" else "")
            + "</div>"
            f"<p class='worum'>{html.escape(p['worum'][:400])}</p>"
            f"{teile}"
            f"<div class='knoepfe'>{knoepfe}</div>"
            "</article>")

    return f"""<!doctype html><meta charset="utf-8">
<title>Kloepfer einsortieren</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;max-width:64em;margin:0 auto;
  padding:1em;color:#1f2328;background:#fff}}
 h1{{font-size:22px;margin:.4em 0}}
 .hinweis{{color:#57606a;margin-bottom:1.5em}}
 article{{border:1px solid #d8dee4;border-radius:8px;padding:.8em 1em;
  margin-bottom:.9em}}
 article.empfohlen{{border-left:4px solid #1a7f37;background:#f6fbf7}}
 article.erledigt{{opacity:.42}}
 .kopf{{display:flex;gap:.6em;align-items:baseline;flex-wrap:wrap}}
 h2{{font-size:17px;margin:0;font-weight:600}}
 .platz{{font-weight:600;color:#57606a;min-width:1.4em}}
 .stern{{background:#1a7f37;color:#fff;border-radius:10px;padding:.05em .55em;
  font-size:11px;font-weight:600;text-transform:uppercase}}
 .buendelmarke{{background:#0969da;color:#fff;border-radius:10px;
  padding:.05em .55em;font-size:11px;font-weight:600}}
 .meta{{color:#57606a;font-size:13px;margin:.3em 0 .5em}}
 .vorschlag{{background:#eef1f4;border-radius:8px;padding:.05em .5em}}
 .unklar{{background:#fff8c5;color:#7d4e00;border-radius:8px;padding:0 .4em}}
 .worum{{margin:.2em 0 .6em}}
 .teile{{margin:.2em 0 .6em 1.2em;color:#57606a;font-size:13px}}
 .knoepfe{{display:flex;gap:.4em;flex-wrap:wrap}}
 button.k{{border:1px solid #d0d7de;background:#f6f8fa;border-radius:6px;
  padding:.35em .8em;font:600 13px system-ui;cursor:pointer;display:flex;
  gap:.4em;align-items:baseline}}
 button.k small{{font-weight:400;color:#57606a}}
 button.k:hover{{background:#eaeef2}}
 .wichtig-ausfuehrlich,.wichtig-lang,.wichtig-mittel,.wichtig-kurz{{
  border-color:#1a7f37;color:#1a7f37}}
 .papierkorb{{border-color:#cf222e;color:#cf222e}}
 .fertig{{color:#1a7f37;font-weight:600}}
</style>
<h1>Kloepfer einsortieren</h1>
<p class="hinweis">{len(posten)} offene Dokumente. Ein Klick verschiebt die
Datei – grün heißt: daraus wird eine Meldung in dieser Länge.
Bündel werden zu <em>einer</em> Meldung.</p>
{"".join(zeilen) or "<p>Nichts offen.</p>"}
<p><button class="k" onclick="fetch('/fertig').then(()=>document.body.innerHTML=
 '<h1>Fertig.</h1><p>Das Fenster kann zu.</p>')">Fertig – Dienst beenden</button>
 <span class="hinweis">Beendet sich auch von selbst, wenn zwei Stunden nichts
 geschieht.</span></p>
<script>
document.querySelectorAll('button.k').forEach(k => {{
  k.addEventListener('click', async () => {{
    const a = k.closest('article');
    const antwort = await fetch('/entscheiden', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{woche:a.dataset.woche, name:a.dataset.name,
                            fach:k.dataset.fach}})}});
    const d = await antwort.json();
    a.classList.add('erledigt');
    a.querySelector('.knoepfe').innerHTML =
      d.ok ? '<span class="fertig">→ ' + d.fach + '</span>'
           : '<span style="color:#cf222e">' + d.fehler + '</span>';
  }});
}});
</script>
"""


def dienst(oeffnen: bool = True) -> int:
    """Die Entscheidungsseite auf dem eigenen Rechner anbieten."""
    import http.server
    import threading
    import webbrowser

    import time

    class Griff(http.server.BaseHTTPRequestHandler):
        zuletzt = time.time()                # fuer den Waechter unten

        def log_message(self, *_):           # kein Protokollrauschen
            pass

        def handle_one_request(self):
            Griff.zuletzt = time.time()
            super().handle_one_request()

        def _sende(self, inhalt: bytes, art: str = "text/html") -> None:
            self.send_response(200)
            self.send_header("Content-Type", f"{art}; charset=utf-8")
            self.send_header("Content-Length", str(len(inhalt)))
            self.end_headers()
            self.wfile.write(inhalt)

        def do_GET(self):
            if self.path.startswith("/fertig"):
                self._sende("<p>Fertig. Das Fenster kann zu.</p>"
                            .encode("utf-8"))
                threading.Thread(target=self.server.shutdown).start()
                return
            self._sende(seite_bauen().encode("utf-8"))

        def do_POST(self):
            laenge = int(self.headers.get("Content-Length", "0"))
            wunsch = json.loads(self.rfile.read(laenge) or b"{}")
            woche = stammordner() / str(wunsch.get("woche", ""))
            name = str(wunsch.get("name", ""))
            fach = str(wunsch.get("fach", ""))
            antwort = {"ok": False, "fehler": "unbekannt", "fach": fach}
            if fach in FAECHER and (woche / "00-neu" / name).exists():
                quelle = woche / "00-neu" / name
                ziel = woche / fach / name
                try:
                    quelle.replace(ziel)
                    antwort = {"ok": True, "fach": fach, "fehler": ""}
                except Exception as fehler:
                    antwort["fehler"] = str(fehler)[:90]
            else:
                antwort["fehler"] = "nicht gefunden"
            self._sende(json.dumps(antwort).encode("utf-8"),
                        "application/json")

    adresse = f"http://127.0.0.1:{DIENST_PORT}/"
    server = http.server.ThreadingHTTPServer(("127.0.0.1", DIENST_PORT), Griff)
    print(f"Entscheidungsseite: {adresse}   (Strg+C beendet)")
    if oeffnen:
        webbrowser.open(adresse)

    # Ohne Fenster gestartet (Zeitplan) gaebe es kein Strg+C: Nach zwei
    # Stunden ohne Zugriff macht der Dienst von selbst Schluss.
    def waechter() -> None:
        import time
        while True:
            time.sleep(60)
            if time.time() - Griff.zuletzt > 7200:
                server.shutdown()
                return

    threading.Thread(target=waechter, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbeendet")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("was", choices=["ernten", "uebersicht", "ordnen",
                                   "buendeln", "schreiben", "entscheiden"])
    p.add_argument("--hoechstens", type=int, default=60,
                   help="wie viele PDFs je Lauf gesichtet werden")
    p.add_argument("--trocken", action="store_true",
                   help="nur zeigen, nichts speichern und nichts verschieben")
    p.add_argument("--woche", help="bei 'uebersicht': welche, etwa 2026-KW40")
    p.add_argument("--zeigen", action="store_true",
                   help="nach dem Ernten die Entscheidungsseite oeffnen")
    a = p.parse_args()

    if a.was == "entscheiden":
        return dienst()

    if a.was == "ernten":
        ergebnis = ernten(a.hoechstens, a.trocken)
        # Nach einer frischen Lieferung gleich die Entscheidungsseite zeigen -
        # sonst bleibt die Arbeit liegen.
        if not a.trocken and a.zeigen and NEUE_PDFS and offene_posten():
            return dienst()
        return ergebnis

    if a.was == "schreiben":
        return schreiben(a.hoechstens if a.hoechstens != 60 else 2,
                         a.trocken, a.woche or "")

    stamm = stammordner()
    wochen = ([stamm / a.woche] if a.woche
              else sorted(w for w in stamm.glob("*-KW*") if w.is_dir()))
    if not wochen:
        print(f"Keine Lieferung unter {stamm}")
        return 1
    for woche in wochen:
        if a.was == "ordnen":
            rangfolge(woche)
        if a.was == "buendeln":
            buendeln(woche)
        uebersicht(woche)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
