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


def schreiben(hoechstens: int, trocken: bool, nur_woche: str = "",
              trotzdem: bool = False) -> int:
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
                # Die zweite Entscheidung: Ohne Freigabe wird nicht
                # geschrieben. Das ist die Bremse vor den Modellkosten.
                if freigabe_laden(woche).get(eintrag.name) != "schreiben":
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

                # Noch vor dem Modellaufruf: Gibt es das Thema schon? Die
                # Pruefung in entwurf() kaeme zu spaet - da ist der teure
                # Teil bereits bezahlt.
                sicht = daten.get(pdfs[0].name, {})
                wert, nahe = schon_auf_dem_portal(
                    sicht.get("titel", eintrag.stem),
                    f"{sicht.get('titel','')} {sicht.get('worum','')}")
                if nahe is not None and wert >= pm.VERGLEICH_MELDEN:
                    urteil = dublette_pruefen(
                        woche, eintrag.name, sicht.get("titel", ""),
                        sicht.get("worum", ""),
                        {"id": nahe["id"], "titel": nahe["title"]["rendered"],
                         "status": nahe.get("status", ""),
                         "datum": nahe.get("date", "")[:10],
                         "inhalt": nahe.get("content", {})
                         .get("rendered", "")})
                    # Das Urteil entscheidet, nicht die Zahl: Eine zweite
                    # Quelle zum selben Thema ist keine Dublette.
                    if urteil and urteil.get("abgedeckt") and not trotzdem:
                        print(f"    Schon erschienen ({nahe['status']}, "
                              f"Nr. {nahe['id']}): "
                              f"{urteil.get('begruendung','')[:80]}")
                        print("    uebersprungen - nichts geschrieben, nichts "
                              "bezahlt.")
                        continue
                    if urteil:
                        print(f"    verwandt zu Nr. {nahe['id']}, aber nicht "
                              f"dasselbe: {urteil.get('begruendung','')[:70]}")
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

                bilder = bilder_sammeln(pdfs, daten, woche.name[:4])
                try:
                    angelegt = pm.entwurf(meldung, inhalt, None, False,
                                          None, bilder, "")
                except Exception as fehler:
                    print(f"    WordPress: {str(fehler)[:110]}")
                    continue
                if angelegt:
                    fertig[eintrag.name] = {"datum": pm.dt_heute(),
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


def bilder_sammeln(pdfs: list[pathlib.Path], daten: dict, jahr: str = "",
                   hoechstens: int = 3) -> list:
    """Abbildungen aus den Dokumenten, jede mit ihrer Quellenangabe.

    Zurueck kommen Dreiergespanne (Name, Daten, Quelle). Die Quelle wird in
    der Mediathek zur Bildunterschrift - bei fremden Abbildungen ist das
    Pflicht, nicht Zierde. Welches Dokument das Bild geliefert hat, weiss nur
    diese Stelle; spaeter laesst es sich nicht mehr zuordnen.
    """
    gefunden = []
    for pfad in pdfs:
        if len(gefunden) >= hoechstens:
            break
        try:
            bilder = pm.bilder_aus_pdf(pfad)
        except Exception:
            continue
        sicht = daten.get(pfad.name, {})
        herausgeber = sicht.get("absender", "")
        werk = sicht.get("titel", pfad.stem)
        quelle = ", ".join(t for t in (herausgeber, werk, jahr) if t)
        for lfd, (name, rohdaten) in enumerate(
                bilder[:hoechstens - len(gefunden)], 1):
            kennung = re.sub(r"[^\wäöüß -]", "", f"{herausgeber} {name}")[:80]
            # Die Abbildungsnummer macht die Angabe nachpruefbar: Wer das PDF
            # aufschlaegt, findet genau dieses Bild wieder. Gezaehlt wird die
            # Reihenfolge im Dokument - mehr gibt das PDF nicht her.
            gefunden.append((kennung or name, rohdaten,
                             f"{quelle}, Abb. {lfd}"))
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


# Die zweite Entscheidung: Einsortiert heisst noch nicht geschrieben. Erst
# die Freigabe loest den teuren Modellaufruf aus - ein zurueckgestelltes
# Thema kostet nichts und bleibt trotzdem auffindbar.
FREIGABE_DATEI = "freigabe.json"
PORTAL_TAGE = 60                # so weit zurueck wird auf Doppelung geprueft
# Grobe Hausnummern je Laenge, damit auf der Seite steht, was ein Lauf kostet.
# Gemessen am 06.10.2026: eine Meldung aus einem 40-Seiten-Gutachten lag bei
# etwa 25 Cent.
KOSTEN = {"wichtig-ausfuehrlich": 0.60, "wichtig-lang": 0.40,
          "wichtig-mittel": 0.25, "wichtig-kurz": 0.15}


def freigabe_laden(woche: pathlib.Path) -> dict:
    try:
        return json.loads((woche / FREIGABE_DATEI).read_text(encoding="utf-8"))
    except Exception:
        return {}


def freigabe_setzen(woche: pathlib.Path, name: str, wert: str) -> None:
    daten = freigabe_laden(woche)
    daten[name] = wert
    (woche / FREIGABE_DATEI).write_text(
        json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")


def schon_auf_dem_portal(titel: str, text: str) -> tuple[float, dict | None]:
    """Steht das Thema schon als Entwurf oder Beitrag auf der Seite?

    Dieselbe Messung wie in der Pressestrecke - Schnittmenge der seltenen
    Begriffe gegen alles, was in den letzten drei Wochen erschienen oder
    angelegt wurde. Hier zaehlt sie doppelt: Sie laeuft VOR der Entscheidung
    und damit vor dem Geld.
    """
    kopf = pm.zugang()
    if kopf is None:
        return 0.0, None
    try:
        # Weiter zurueck als bei den Pressemitteilungen: Ein Gesetzentwurf
        # oder ein Gutachten kommt bei Kloepfer auch Wochen nach der
        # Pressemitteilung dazu - die drei Treffer vom 06.10.2026 lagen
        # zwischen 6 und 20 Tagen zurueck, der naechste kann aelter sein.
        return pm.inhaltlich_schon_da(titel, text, kopf, tage=PORTAL_TAGE)
    except Exception:
        return 0.0, None


# Die Zahl aus dem Begriffsvergleich sagt "aehnlich", nicht "dasselbe". Ob
# ein Dokument wirklich erledigt ist oder etwas Neues bringt, kann nur jemand
# entscheiden, der beide Texte liest. Das kostet einen halben Cent und macht
# aus "moeglicherweise" ein Ja oder Nein.
DUBLETTEN_DATEI = "dubletten.json"
DUBLETTEN_SYSTEM = (
    "Du prüfst für die Redaktion von Monitor Versorgungsforschung, ob ein "
    "neues Dokument bereits durch einen vorhandenen Beitrag abgedeckt ist.\n"
    "Abgedeckt heißt: Der Beitrag berichtet über denselben Vorgang und nennt "
    "im Kern dasselbe. Eine zweite Quelle zum selben Thema, die neue Zahlen, "
    "eine andere Position oder einen anderen Aspekt beiträgt, ist NICHT "
    "abgedeckt - daraus wird eine eigene Meldung.\n"
    "Im Zweifel gilt: nicht abgedeckt. Eine ausgelassene Meldung ist ein "
    "größerer Verlust als eine, die sich als Dublette erweist.\n"
    "Schreibe mit Umlauten, nie in Ersatzschreibung."
)
DUBLETTEN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["abgedeckt", "begruendung"],
    "properties": {
        "abgedeckt": {"type": "boolean"},
        "begruendung": {"type": "string"},
    },
}


def dublette_pruefen(woche: pathlib.Path, name: str, titel: str, worum: str,
                     beitrag: dict) -> dict | None:
    """Ist das Thema durch den vorhandenen Beitrag wirklich erledigt?

    Das Urteil wird gemerkt - der Dienst baut die Seite bei jedem Aufruf neu,
    und dreimal dieselbe Frage ist dreimal derselbe Preis.
    """
    datei = woche / DUBLETTEN_DATEI
    try:
        gemerkt = json.loads(datei.read_text(encoding="utf-8"))
    except Exception:
        gemerkt = {}
    schluessel = f"{name}|{beitrag['id']}"
    if schluessel in gemerkt:
        return gemerkt[schluessel]

    schluessel_api = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel_api:
        return None
    import re as regex

    import anthropic
    vorhanden = regex.sub(r"<[^>]+>", " ",
                          beitrag.get("inhalt", ""))[:2500]
    auftrag = (
        f"VORHANDENER BEITRAG ({beitrag.get('status','')}, "
        f"{beitrag.get('datum','')})\n"
        f"Titel: {beitrag.get('titel','')}\n{vorhanden}\n\n"
        f"NEUES DOKUMENT\nTitel: {titel}\n{worum}\n\n"
        "Ist das neue Dokument durch den vorhandenen Beitrag abgedeckt?\n"
        "- abgedeckt: true nur, wenn eine weitere Meldung nichts hinzufügt.\n"
        "- begruendung: ein Satz. Bei false: was das neue Dokument bringt, "
        "das im Beitrag fehlt.")
    try:
        antwort = anthropic.Anthropic(api_key=schluessel_api).messages.create(
            model=SICHT_MODELL, max_tokens=400, system=DUBLETTEN_SYSTEM,
            output_config={"format": {"type": "json_schema",
                                      "schema": DUBLETTEN_SCHEMA}},
            messages=[{"role": "user", "content": auftrag}])
        urteil = json.loads(next(b.text for b in antwort.content
                                 if b.type == "text"))
    except Exception:
        return None
    gemerkt[schluessel] = urteil
    datei.write_text(json.dumps(gemerkt, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return urteil


def eingeordnete_posten() -> list:
    """Was in den Laengen-Ordnern liegt und auf die Freigabe wartet."""
    posten = []
    for woche in sorted(stammordner().glob("*-KW*"), reverse=True):
        daten = sichtung_laden(woche)
        stand = freigabe_laden(woche)
        try:
            fertig = json.loads(
                (woche / "geschrieben.json").read_text(encoding="utf-8"))
        except Exception:
            fertig = {}
        for fach in LAENGEN:
            ordner = woche / fach
            if not ordner.exists():
                continue
            for eintrag in sorted(ordner.iterdir()):
                if eintrag.is_dir():
                    teile = sorted(eintrag.glob("*.pdf"))
                    if not teile:
                        continue
                    stuecke = sorted((daten.get(t.name, {}) for t in teile),
                                     key=lambda e: e.get("platz", 99))
                    titel = eintrag.name.replace("Thema - ", "")
                    absender = ", ".join(dict.fromkeys(
                        e.get("absender", "") for e in stuecke))
                    seiten = sum(e.get("seiten", 0) for e in stuecke)
                    worum = (stuecke[0].get("buendel_warum")
                             or stuecke[0].get("worum", "")) if stuecke else ""
                    # Fuer die Dublettenpruefung zaehlt der ganze Inhalt des
                    # Buendels: Das zweite Dokument ist oft gerade das, was
                    # im vorhandenen Beitrag fehlt - beim Thema Community
                    # Health Nurses etwa das Rechtsgutachten neben dem
                    # Positionspapier.
                    pruef_text = " ".join(
                        f"{e.get('titel','')}: {e.get('worum','')[:260]}"
                        for e in stuecke)
                    anzahl = len(teile)
                elif eintrag.suffix.lower() == ".pdf":
                    e = daten.get(eintrag.name, {})
                    titel = e.get("titel", eintrag.stem)
                    absender = e.get("absender", "")
                    seiten = e.get("seiten", 0)
                    worum = e.get("worum", "")
                    pruef_text = worum
                    anzahl = 1
                else:
                    continue
                eintragsdaten = {
                    "woche": woche.name, "name": eintrag.name, "fach": fach,
                    "titel": titel, "absender": absender, "seiten": seiten,
                    "worum": worum, "anzahl": anzahl,
                    "zeichen": LAENGEN[fach],
                    "kosten": KOSTEN.get(fach, 0.25),
                    "stand": ("geschrieben" if eintrag.name in fertig
                              else stand.get(eintrag.name, "offen"))}
                # Vor der Entscheidung nachsehen, ob es das Thema schon gibt.
                if eintragsdaten["stand"] != "geschrieben":
                    wert, nahe = schon_auf_dem_portal(
                        titel, f"{titel} {pruef_text}")
                    if nahe is not None and wert >= pm.VERGLEICH_MELDEN:
                        doppelt = {
                            "wert": round(wert, 2), "id": nahe["id"],
                            "titel": nahe["title"]["rendered"],
                            "status": nahe.get("status", ""),
                            "datum": nahe.get("date", "")[:10],
                            "link": nahe.get("link", ""),
                            "inhalt": nahe.get("content", {})
                            .get("rendered", "")}
                        urteil = dublette_pruefen(woche, eintrag.name, titel,
                                                  pruef_text, doppelt)
                        if urteil:
                            doppelt["abgedeckt"] = bool(urteil["abgedeckt"])
                            doppelt["warum"] = str(
                                urteil.get("begruendung", ""))[:220]
                        doppelt.pop("inhalt", None)
                        eintragsdaten["doppelt"] = doppelt
                posten.append(eintragsdaten)
    return posten


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


def dublettenzeile(d: dict) -> str:
    """Der Hinweis auf einen vorhandenen Beitrag - mit klarem Urteil."""
    wo = (f"<a href='{html.escape(d.get('link',''))}' target='_blank'>"
          f"{html.escape(d.get('titel','')[:72])}</a> "
          f"({'Entwurf' if d.get('status') == 'draft' else 'veröffentlicht'}"
          f" am {d.get('datum','')}, Nr. {d.get('id')})")
    if d.get("abgedeckt") is True:
        return (f"<p class='doppelt ja'><strong>Schon erschienen – nicht "
                f"schreiben.</strong> {wo}<br>"
                f"{html.escape(d.get('warum',''))}</p>")
    if d.get("abgedeckt") is False:
        return (f"<p class='doppelt nein'><strong>Verwandt, aber nicht "
                f"dasselbe.</strong> {wo}<br>"
                f"{html.escape(d.get('warum',''))}</p>")
    # Ohne Urteil bleibt nur die Messung - und die sagt "aehnlich".
    return (f"<p class='doppelt'>Ähnlich zu einem vorhandenen Beitrag "
            f"({d.get('wert', 0):.2f}), nicht geprüft: {wo}</p>")


def seite_bauen() -> str:
    # Der Dienst laeuft stundenlang; der Bestand der Seite darf nicht von
    # heute Morgen sein. Vor jedem Aufbau neu holen.
    pm._bestand.clear()
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

    # Zweiter Teil: Was einsortiert ist, wartet auf die Freigabe. Geschrieben
    # wird nur, was hier freigegeben ist - das ist die Bremse vor den Kosten.
    zweite = []
    eingeordnet = eingeordnete_posten()
    freigegeben = [p for p in eingeordnet if p["stand"] == "schreiben"]
    summe = sum(p["kosten"] for p in freigegeben)
    for p in eingeordnet:
        knopf = {"offen": "", "schreiben": "freigegeben",
                 "zurueckgestellt": "zurückgestellt",
                 "geschrieben": "geschrieben"}[p["stand"]]
        zweite.append(
            f"<article class='zweite {p['stand']}' "
            f"data-woche='{html.escape(p['woche'])}' "
            f"data-name=\"{html.escape(p['name'])}\">"
            f"<div class='kopf'>"
            f"<span class='fachmarke'>{p['fach'].replace('wichtig-', '')}"
            f"<small>{p['zeichen']:,}</small></span>".replace(",", ".")
            + (f"<span class='buendelmarke'>{p['anzahl']} Dok.</span>"
               if p["anzahl"] > 1 else "")
            + f"<h2>{html.escape(p['titel'])}</h2></div>"
            f"<div class='meta'>{html.escape(p['absender'][:70])} · "
            f"{p['seiten']} S. · {html.escape(p['woche'])} · "
            f"ca. {p['kosten']:.2f} €</div>".replace(".", ",", 1)
            + f"<p class='worum'>{html.escape(p['worum'][:240])}</p>"
            + (dublettenzeile(p["doppelt"]) if p.get("doppelt") else "")
            + ("<div class='knoepfe'>"
               "<button data-wert='schreiben' class='k schreiben'>"
               "wirklich schreiben</button>"
               "<button data-wert='zurueckgestellt' class='k zurueck'>"
               "zurückstellen</button></div>"
               if p["stand"] in ("offen", "schreiben", "zurueckgestellt")
               else "")
            + (f"<p class='stand'>{knopf}</p>" if knopf else "")
            + "</article>")

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
 h1.zwei{{margin-top:2em;border-top:2px solid #d8dee4;padding-top:1em}}
 .fachmarke{{background:#1a7f37;color:#fff;border-radius:6px;
  padding:.1em .6em;font-size:12px;font-weight:600;display:flex;gap:.4em}}
 .fachmarke small{{font-weight:400;opacity:.8}}
 article.zweite{{border-left:4px solid #d0d7de}}
 article.schreiben{{border-left-color:#1a7f37;background:#f6fbf7}}
 article.zurueckgestellt{{opacity:.5}}
 article.geschrieben{{opacity:.45;border-left-color:#8250df}}
 button.zurueck{{border-color:#9a6700;color:#9a6700}}
 .stand{{font-weight:600;color:#1a7f37;margin:.2em 0 0}}
 .summe{{background:#eef1f4;border-radius:8px;padding:.7em 1em;
  margin:.6em 0 1.4em;font-size:14px}}
 .doppelt{{background:#fff8c5;border:1px solid #d4a72c;border-radius:6px;
  padding:.5em .8em;font-size:13px;color:#7d4e00;margin:.4em 0}}
 .doppelt a{{color:#7d4e00}}
 .doppelt.ja{{background:#ffebe9;border-color:#cf222e;color:#82071e}}
 .doppelt.ja a{{color:#82071e}}
 .doppelt.nein{{background:#eef6ff;border-color:#8bb9f0;color:#0a3069}}
 .doppelt.nein a{{color:#0a3069}}
</style>
<h1>Kloepfer einsortieren</h1>
<p class="hinweis">{len(posten)} Dokumente noch ohne Entscheidung. Ein Klick
verschiebt die Datei – grün heißt: daraus soll eine Meldung in dieser Länge
werden. Bündel werden zu <em>einer</em> Meldung.</p>
{"".join(zeilen) or "<p class='hinweis'>Alles einsortiert.</p>"}

<h1 class="zwei">Freigeben – was wirklich geschrieben wird</h1>
<p class="summe" id="summe">{len(freigegeben)} von {len(eingeordnet)}
freigegeben · geschätzte Kosten des nächsten Laufs:
<strong>{summe:.2f} €</strong>. Zurückgestelltes bleibt liegen und kostet
nichts – es lässt sich jederzeit nachträglich freigeben.</p>
{"".join(zweite) or "<p class='hinweis'>Noch nichts einsortiert.</p>"}
<p><button class="k" onclick="fetch('/fertig').then(()=>document.body.innerHTML=
 '<h1>Fertig.</h1><p>Das Fenster kann zu.</p>')">Fertig – Dienst beenden</button>
 <span class="hinweis">Beendet sich auch von selbst, wenn zwei Stunden nichts
 geschieht.</span></p>
<script>
// Erste Entscheidung: die Datei in einen Laengen-Ordner verschieben.
document.querySelectorAll('button.k[data-fach]').forEach(k => {{
  k.addEventListener('click', async () => {{
    const a = k.closest('article');
    const antwort = await fetch('/entscheiden', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{woche:a.dataset.woche, name:a.dataset.name,
                            fach:k.dataset.fach}})}});
    const d = await antwort.json();
    a.classList.add('erledigt');
    a.querySelector('.knoepfe').innerHTML =
      d.ok ? '<span class="fertig">→ ' + d.fach + ' · die Freigabe steht '
             + 'unten</span>'
           : '<span style="color:#cf222e">' + d.fehler + '</span>';
  }});
}});

// Zweite Entscheidung: freigeben oder zuruecklegen.
document.querySelectorAll('button.k[data-wert]').forEach(k => {{
  k.addEventListener('click', async () => {{
    const a = k.closest('article');
    const antwort = await fetch('/freigeben', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{woche:a.dataset.woche, name:a.dataset.name,
                            wert:k.dataset.wert}})}});
    const d = await antwort.json();
    if (!d.ok) return;
    a.classList.remove('schreiben','zurueckgestellt');
    a.classList.add(d.wert);
    document.getElementById('summe').innerHTML =
      d.anzahl + ' von ' + d.gesamt + ' freigegeben · geschätzte Kosten des '
      + 'nächsten Laufs: <strong>' + d.summe.toFixed(2).replace('.', ',')
      + ' €</strong>';
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

            if self.path.startswith("/freigeben"):
                wert = str(wunsch.get("wert", ""))
                antwort = {"ok": False, "wert": wert}
                if wert in ("schreiben", "zurueckgestellt") and woche.exists():
                    freigabe_setzen(woche, name, wert)
                    alle = eingeordnete_posten()
                    frei = [p for p in alle if p["stand"] == "schreiben"]
                    antwort = {"ok": True, "wert": wert, "anzahl": len(frei),
                               "gesamt": len(alle),
                               "summe": round(sum(p["kosten"] for p in frei), 2)}
                self._sende(json.dumps(antwort).encode("utf-8"),
                            "application/json")
                return

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
    p.add_argument("--trotzdem", action="store_true",
                   help="auch schreiben, was als schon erschienen gilt")
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
                         a.trocken, a.woche or "", a.trotzdem)

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
