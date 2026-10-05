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
        uebersicht(woche)
    return 0


# -------------------------------------------------------------- Uebersicht
def uebersicht(woche: pathlib.Path) -> pathlib.Path:
    """Die Liste zum Lesen - sortiert nach Relevanz."""
    daten = sichtung_laden(woche)
    wo = {}
    for fach in FAECHER:
        for datei in (woche / fach).glob("*.pdf"):
            wo[datei.name] = fach

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


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("was", choices=["ernten", "uebersicht", "ordnen"])
    p.add_argument("--hoechstens", type=int, default=60,
                   help="wie viele PDFs je Lauf gesichtet werden")
    p.add_argument("--trocken", action="store_true",
                   help="nur zeigen, nichts speichern und nichts verschieben")
    p.add_argument("--woche", help="bei 'uebersicht': welche, etwa 2026-KW40")
    a = p.parse_args()

    if a.was == "ernten":
        return ernten(a.hoechstens, a.trocken)

    stamm = stammordner()
    wochen = ([stamm / a.woche] if a.woche
              else sorted(w for w in stamm.glob("*-KW*") if w.is_dir()))
    if not wochen:
        print(f"Keine Lieferung unter {stamm}")
        return 1
    for woche in wochen:
        if a.was == "ordnen":
            rangfolge(woche)
        uebersicht(woche)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
