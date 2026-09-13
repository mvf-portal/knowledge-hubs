#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Der Titelkopf des Newsletters: aus InDesign bauen und zu Mailchimp legen.

Ueber dem Newsletter steht das Titelbild der aktuellen gedruckten Ausgabe -
sechsmal im Jahr ein neues, 01 bis 06. Gebaut wird es bisher von Hand: die
InDesign-Datei der Vorausgabe kopieren, das Titelbild neu verknuepfen,
zweimal als JPG ausgeben, in Mailchimp hochladen, im Entwurf austauschen.

Dieses Skript nimmt die ersten vier Schritte ab:

    python scripts/newsletter_kopf.py 05-2026
    python scripts/newsletter_kopf.py 05-2026 --trocken
    python scripts/newsletter_kopf.py 05-2026 --ziel D:\\Probe

**Den fuenften Schritt nimmt es nicht ab, und das ist keine Nachlaessigkeit.**
Der Titelkopf steckt nicht in einem Bereich, den die Mailchimp-API setzen
koennte - er ist Teil des Kampagnen-HTML. Wer ihn ueber die API austauschen
wollte, muesste die ganze Kampagne als rohes HTML ersetzen und verloere damit
den Baukasten, in dem die Redaktion arbeitet. Am 13.09.2026 geprueft. Der
Austausch bleibt deshalb ein Klick in Mailchimp - sechsmal im Jahr, und nur
in der ersten Ausgabe je Druckausgabe. Danach erbt ihn jede Kopie von selbst.

Gebraucht werden: InDesign CS6 auf diesem Rechner (das Skript startet es, wenn
es nicht laeuft), `pip install pywin32`, und das Titelbild der neuen Ausgabe im
Archiv. Fehlt das Titelbild, sagt das Skript genau, wo es es erwartet hat.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATEN = pathlib.Path(os.environ["USERPROFILE"]) / "eRelation AG" / "Data - Daten"
NEWSLETTER = DATEN / "10_Web-Portale" / "MVF" / "000_Newsletter"
ARCHIV = (pathlib.Path(os.environ["USERPROFILE"]) / "eRelation AG"
          / "Data - eRelation" / "05_Archiv_MVF")
REDAKTION = (pathlib.Path(os.environ["USERPROFILE"]) / "eRelation AG"
             / "Data - eRelation" / "04_Versorgungsforschung" / "00 Redaktion")

# Der Kopf ist ein einziges Objekt auf der Seite, 218,7 x 106,2 mm. Bei 300 dpi
# ergibt das 2584 x 1255 Punkte, bei 72 dpi genau die 620 Punkte, auf die der
# Newsletter gebaut ist. Zweimal ausgeben ist einfacher als einmal ausgeben und
# verkleinern - InDesign rechnet ohnehin besser als eine Notloesung in Python.
AUFLOESUNGEN = [(300, ""), (72, "-620px")]

# InDesigns Aufzaehlungen sind Vierzeichenkuerzel als Zahl: "JPG " ist die
# Ausgabeart, "enMx" die hoechste JPEG-Stufe, "cRGB" der Farbraum.
JPG = 1246775072                 # ExportFormat.JPG
NICHT_SICHERN = 1852776480       # SaveOptions.NO
MAXIMAL = 1701727608             # JPEGOptionsQuality.MAXIMUM ("enMx")
RGB = 1666336578                 # JPEGColorSpace.RGB ("cRGB")
SEITENRAHMEN = 1131573328        # PDFCrop.CROP_PDF
INHALTSRAHMEN = 1131566703       # PDFCrop.CROP_CONTENT_VISIBLE_LAYERS

AUSGABE_MUSTER = re.compile(r"^(\d{2})-(\d{4})$")


def mc_schluessel() -> str:
    for name in ("MAILCHIMP_API_KEY", "KNOWLEDGEHUBSMC"):
        wert = os.environ.get(name)
        if wert:
            return wert.strip()
    return ""


def mc(pfad: str, method: str = "GET", body: dict | None = None) -> dict:
    schluessel = mc_schluessel()
    rechenzentrum = schluessel.rsplit("-", 1)[-1]
    daten = json.dumps(body).encode("utf-8") if body is not None else None
    anfrage = urllib.request.Request(
        f"https://{rechenzentrum}.api.mailchimp.com/3.0{pfad}", data=daten, method=method)
    anfrage.add_header("Authorization", "Basic " + base64.b64encode(
        f"any:{schluessel}".encode()).decode())
    anfrage.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(anfrage, timeout=180) as antwort:
        roh = antwort.read()
    return json.loads(roh) if roh else {}


def aufraeumen(name: str) -> None:
    """Eine aeltere Datei gleichen Namens weg. Mailchimp laesst Doppel zu, und
    zwei gleich heissende Titelkoepfe in der Auswahl sind eine Falle - die
    Redaktion greift zum falschen."""
    try:
        d = mc("/file-manager/files?count=60&sort_field=added_date&sort_dir=DESC&type=image")
    except Exception:
        return
    for datei in d.get("files", []):
        if datei.get("name") == name:
            try:
                mc(f"/file-manager/files/{datei['id']}", method="DELETE")
                print(f"  aeltere Fassung entfernt (Nr. {datei['id']})")
            except Exception as fehler:
                print(f"  aeltere Fassung blieb liegen: {fehler}")


def hochladen(bild: pathlib.Path) -> str:
    """Legt das Bild in Mailchimps Dateiverwaltung und gibt die Adresse zurueck."""
    schluessel = mc_schluessel()
    if not schluessel:
        return ""
    aufraeumen(bild.name)
    rechenzentrum = schluessel.rsplit("-", 1)[-1]
    koerper = json.dumps({"name": bild.name,
                          "file_data": base64.b64encode(bild.read_bytes()).decode()})
    anfrage = urllib.request.Request(
        f"https://{rechenzentrum}.api.mailchimp.com/3.0/file-manager/files",
        data=koerper.encode("utf-8"), method="POST")
    anfrage.add_header("Authorization", "Basic " + base64.b64encode(
        f"any:{schluessel}".encode()).decode())
    anfrage.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(anfrage, timeout=180) as antwort:
            return json.loads(antwort.read()).get("full_size_url", "")
    except urllib.error.HTTPError as fehler:
        print("  Mailchimp lehnt den Upload ab: "
              f"{fehler.code} {fehler.read().decode('utf-8', 'replace')[:300]}")
        return ""


def vorausgabe(nummer: int, jahr: int) -> tuple[int, int]:
    """Die Ausgabe davor - sechs im Jahr, danach faengt das Jahr von vorn an."""
    return (nummer - 1, jahr) if nummer > 1 else (6, jahr - 1)


def vorlage_suchen(nummer: int, jahr: int) -> pathlib.Path:
    """Die InDesign-Datei der Vorausgabe. Sie liegt entweder noch im
    Newsletter-Ordner oder schon im Unterordner `alte`."""
    name = f"MVF_NL Header_{nummer:02d}-{jahr}.indd"
    for ordner in (NEWSLETTER, NEWSLETTER / "alte"):
        if (ordner / name).is_file():
            return ordner / name
    raise SystemExit(f"Keine Vorlage gefunden: {name} (weder in {NEWSLETTER} "
                     f"noch in {NEWSLETTER / 'alte'})")


def titelbild(nummer: int, jahr: int, genannt: str = "") -> pathlib.Path:
    """Das Titelbild der Druckausgabe.

    Es liegt an zwei Stellen, je nachdem, wie weit die Ausgabe ist: waehrend
    der Produktion im Redaktionsordner (dort oft als PDF - InDesign platziert
    das ebenso), nach dem Erscheinen im Archiv. Gesucht wird in beiden; der
    Dateiname wechselt zwischen "MVF-0426_Titel" und "MVf0526-Titell", deshalb
    steht hier ein grobes Muster und kein fester Name. Ein Pfad auf der
    Kommandozeile schlaegt jede Suche.
    """
    if genannt:
        bild = pathlib.Path(genannt)
        if not bild.is_file():
            raise SystemExit(f"Das genannte Titelbild gibt es nicht: {bild}")
        return bild

    kurz = f"{jahr % 100:02d}"
    muster = re.compile(rf"mvf-?{nummer:02d}{kurz}.*titell?\.(jpg|jpeg|pdf|tif|tiff)$",
                        re.I)
    gesucht = [
        ARCHIV / str(jahr) / f"{nummer:02d}-{kurz}" / "05-Portal",
        REDAKTION / f"{nummer:02d}-{kurz}" / "05_portal",
        REDAKTION / f"{nummer:02d}-{kurz}" / "05-Portal",
    ]
    for ordner in gesucht:
        if not ordner.is_dir():
            continue
        treffer = sorted(d for d in ordner.iterdir() if muster.match(d.name))
        if treffer:
            return treffer[0]
    raise SystemExit(
        f"Das Titelbild der Ausgabe {nummer:02d}/{kurz} ist nirgends zu finden. "
        "Gesucht habe ich in:\n  " + "\n  ".join(str(o) for o in gesucht) +
        "\nLiegt es woanders, hilft --titelbild mit dem vollen Pfad.")


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Baut den Newsletter-Titelkopf einer Ausgabe und laedt ihn hoch.")
    zerleger.add_argument("ausgabe", help="Ausgabe als NN-JJJJ, etwa 05-2026")
    zerleger.add_argument("--titelbild", default="",
                          help="Pfad des Titelbilds, falls es nicht an der "
                               "ueblichen Stelle liegt")
    zerleger.add_argument("--ziel", default=str(NEWSLETTER),
                          help="Ordner fuer die neuen Dateien (Vorgabe: der Newsletter-Ordner)")
    zerleger.add_argument("--trocken", action="store_true",
                          help="nur pruefen, nichts bauen und nichts hochladen")
    zerleger.add_argument("--ohne-upload", action="store_true",
                          help="JPGs bauen, aber nicht zu Mailchimp legen")
    argumente = zerleger.parse_args()

    passt = AUSGABE_MUSTER.match(argumente.ausgabe.strip())
    if not passt:
        return zerleger.error("Die Ausgabe wird als NN-JJJJ geschrieben, etwa 05-2026")
    nummer, jahr = int(passt.group(1)), int(passt.group(2))
    if not 1 <= nummer <= 6:
        return zerleger.error("Es gibt sechs Ausgaben im Jahr, 01 bis 06.")

    vor_nummer, vor_jahr = vorausgabe(nummer, jahr)
    vorlage = vorlage_suchen(vor_nummer, vor_jahr)
    bild = titelbild(nummer, jahr, argumente.titelbild)
    ziel = pathlib.Path(argumente.ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    neu_indd = ziel / f"MVF_NL Header_{nummer:02d}-{jahr}.indd"

    # Der Kopf darf lange vor dem Erscheinen gebaut werden - eingesetzt wird er
    # erst am Erscheinungstag. Der Hinweis erspart ein zu frueh getauschtes Bild.
    try:
        termine = json.loads(
            (pathlib.Path(__file__).with_name("druckausgaben.json"))
            .read_text(encoding="utf-8"))["ausgaben"]
        tag = termine.get(f"{nummer:02d}-{jahr}")
    except Exception:
        tag = None

    print(f"Titelkopf Ausgabe {nummer:02d}/{jahr}")
    if tag:
        erscheint = datetime.date.fromisoformat(tag)
        if erscheint > datetime.date.today():
            print(f"  Erscheint am {erscheint:%d.%m.%Y} - bis dahin bleibt der "
                  "Kopf der Vorausgabe der richtige.")
        else:
            print(f"  Erschienen am {erscheint:%d.%m.%Y} - dieser Kopf gilt.")
    else:
        print(f"  Kein Erscheinungstag in druckausgaben.json - bitte "
              f"'{nummer:02d}-{jahr}' dort eintragen.")
    print(f"  Vorlage:    {vorlage}")
    print(f"  Titelbild:  {bild}")
    print(f"  Neue Datei: {neu_indd}")
    if argumente.trocken:
        print("\n--trocken: nichts gebaut.")
        return 0

    if neu_indd.exists():
        print(f"\n{neu_indd.name} gibt es schon - ich ruehre sie nicht an. "
              "Zum Neubauen vorher loeschen oder --ziel setzen.")
        return 1
    shutil.copy2(vorlage, neu_indd)

    try:
        import win32com.client
    except ImportError:
        raise SystemExit("pywin32 fehlt: pip install pywin32")

    # GetActiveObject scheitert immer - InDesign traegt sich nicht in die
    # Running Object Table ein. CreateObject greift auf eine laufende Sitzung
    # zu oder startet eine neue.
    indesign = win32com.client.Dispatch("InDesign.Application.CS6")
    dokument = indesign.Open(str(neu_indd), False)
    try:
        # Relink() gibt es zwar, aber ueber COM nicht: InDesign will dafuer ein
        # File-Objekt und weist jede Zeichenkette mit "Die Verknuepfungsressource
        # kann aus dem angegebenen URI nicht erstellt werden" ab - auch den
        # eigenen, unveraenderten Pfad. Place() auf den Rahmen tut dasselbe und
        # nimmt einen gewoehnlichen Pfad. Geprueft am 13.09.2026 mit CS6.
        titel = [v for v in dokument.Links if "titel" in v.Name.lower()]
        if len(titel) != 1:
            raise SystemExit(
                f"In {vorlage.name} stehen {len(titel)} Titelbilder, erwartet "
                "war genau eines. Die Vorlage hat sich geaendert.")
        grafik = titel[0].Parent
        rahmen = grafik.Parent
        # Der neue Titel wird auf den Platz des alten gesetzt - Rahmen und
        # Bildausschnitt bleiben damit auf den Millimeter dieselben. Ein
        # "einpassen" waere Auslegungssache und verschoebe das Cover.
        grenzen = grafik.GeometricBounds
        # Ein PDF platziert InDesign von Haus aus auf seinen INHALT - bei
        # MVf0526-Titell.pdf sind das 202,2 x 285,4 mm statt der 210 x 297 der
        # Seite. Das Titelbild fuellte damit den Rahmen bis zur Unterkante, und
        # die ragt 2,3 mm ueber die weisse Flaeche hinaus, auf der der Titel
        # liegt: Die letzte Zeile des Covers stand im Gruen. Mit dem
        # Seitenrahmen sitzt das PDF so wie die JPGs der Vorjahre.
        vorher = indesign.PDFPlacePreferences.PDFCrop
        indesign.PDFPlacePreferences.PDFCrop = SEITENRAHMEN
        try:
            rahmen.Place(str(bild))
        finally:
            indesign.PDFPlacePreferences.PDFCrop = vorher
        rahmen.Graphics.Item(1).GeometricBounds = grenzen

        # Neben dem Titelbild steht "Ausgabe 04/26" - in einem Textrahmen
        # INNERHALB der Gruppe, den dokument.TextFrames deshalb nicht findet.
        # Geaendert wird er mit Suchen/Ersetzen, damit die Schrift so bleibt,
        # wie sie gesetzt ist; ein neu geschriebener Rahmeninhalt verloere sie.
        kurz = f"{jahr % 100:02d}"
        indesign.FindGrepPreferences.FindWhat = ""
        indesign.ChangeGrepPreferences.ChangeTo = ""
        indesign.FindGrepPreferences.FindWhat = r"Ausgabe \d\d/\d\d"
        indesign.ChangeGrepPreferences.ChangeTo = f"Ausgabe {nummer:02d}/{kurz}"
        ersetzt = dokument.ChangeGrep()
        indesign.FindGrepPreferences.FindWhat = ""
        indesign.ChangeGrepPreferences.ChangeTo = ""
        if ersetzt.Count != 1:
            print(f"  Achtung: {ersetzt.Count} Stellen mit 'Ausgabe NN/JJ' "
                  "gefunden, erwartet war eine - bitte im Kopf nachsehen.")
        else:
            print(f"  Ausgabezeile: Ausgabe {nummer:02d}/{kurz}")

        dokument.Save()

        objekte = dokument.Pages.Item(1).PageItems
        if objekte.Count != 1:
            raise SystemExit(f"Die Seite traegt {objekte.Count} Objekte, erwartet "
                             "war genau eines - die Vorlage hat sich geaendert.")
        kopf = objekte.Item(1)

        indesign.JPEGExportPreferences.JPEGQuality = MAXIMAL
        indesign.JPEGExportPreferences.JpegColorSpace = RGB
        indesign.JPEGExportPreferences.AntiAlias = True
        gebaut = []
        for aufloesung, anhang in AUFLOESUNGEN:
            indesign.JPEGExportPreferences.ExportResolution = aufloesung
            datei = ziel / f"NL_Header_{nummer:02d}-{jahr}{anhang}.jpg"
            # Ein einzelnes Objekt gibt sich mit Export() aus, nicht mit
            # ExportFile() - das kann nur das Dokument.
            kopf.Export(JPG, str(datei), False)
            gebaut.append(datei)
            print(f"  gebaut: {datei.name} ({datei.stat().st_size // 1024} kB)")
    finally:
        dokument.Close(NICHT_SICHERN)

    if argumente.ohne_upload:
        print("\n--ohne-upload: nichts zu Mailchimp gelegt.")
        return 0

    klein = gebaut[-1]
    print(f"\nLege {klein.name} in Mailchimps Dateiverwaltung ...")
    adresse = hochladen(klein)
    if adresse:
        print(f"  {adresse}")
    else:
        print("  Nicht hochgeladen - Datei liegt aber im Ordner.")

    print("\nWas jetzt noch von Hand geschieht - einmal je Druckausgabe:")
    print("  Im Mailchimp-Entwurf oben auf den Titelkopf klicken, das neue Bild")
    print("  waehlen, den Link auf /internals/abonnement/ stehen lassen.")
    print("  Jede weitere Ausgabe erbt den Kopf dann von der Kopie.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
