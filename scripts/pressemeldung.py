#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aus einer Pressemitteilung wird ein WordPress-Entwurf in der Rubrik News.

Anke Heiser stellt Pressemitteilungen bisher von Hand ein: Text aus dem PDF
oder der Mail holen, kuerzen, Vorspann schreiben, Schlagwort setzen, Bild
suchen, Entwurf anlegen. Dieses Skript nimmt ihr alles ab bis auf die
Freigabe - genau wie `tagesnews.py`, nur ist die Quelle hier keine
Sammeldatei, sondern eine einzelne Pressemitteilung.

    python scripts/pressemeldung.py postfach             # alle neuen Mails
    python scripts/pressemeldung.py lernen               # Logos nachtragen
    python scripts/pressemeldung.py outlook              # die offene Mail
    python scripts/pressemeldung.py Pressemitteilung_DNVF.pdf
    python scripts/pressemeldung.py https://example.org/pm.html --bild abb.jpg
    python scripts/pressemeldung.py pm.pdf --trocken     # nur ansehen

Gelesen werden PDF, Mail (.eml und .msg), HTML-Seiten und einfacher Text -
und mit `outlook` die Mail, die in Outlook gerade offen oder markiert ist.
Haengt an der Mail ein PDF, zaehlt dessen Text mit: In der Mail steht oft nur
ein Anrisstext, die Mitteilung selbst im Anhang.

Fuer die beiden Mailwege braucht es je eine Bibliothek, die sonst niemand
laedt: `pip install pywin32` fuer Outlook, `pip install extract_msg` fuer
abgelegte .msg-Dateien. Ohne sie laufen die uebrigen Wege unveraendert.

**Die Adressen baut das Skript, nicht das Sprachmodell.** Aus der Quelle wird
eine Liste der dort wirklich stehenden Links gezogen; nur daraus darf das
Modell waehlen. Ein Modell, das URLs erfinden darf, erfindet sie irgendwann
auch - dieselbe Regel wie in den Tagesnews.

Ebenso das Schlagwort: Das Modell nennt einen Namen aus der Hausliste, die
Nummer schlaegt das Skript nach. Neue Schlagwoerter legt es nie an.

Der Entwurf ist ein Entwurf. Der WordPress-Benutzer hat die Rolle Autor und
koennte gar nicht veroeffentlichen - das bleibt bei der Redaktion.

Geheimnisse in der Umgebung, benannt wie in tagesnews.py:
    KNOWLEDGEHUBS    Anthropic-Schluessel
    WPUSER           WordPress-Benutzer (Rolle Autor)
    WPPASSWORT       dessen Anwendungspasswort
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WP = "https://www.monitor-versorgungsforschung.de/wp-json/wp/v2"
WP_KATEGORIE = 1000            # "News"
# Ohne eigene Kennung sieht die Anfrage aus wie ein Skript von der Stange;
# das Schutz-Plugin der MVF-Seite antwortet darauf mit 403.
KENNUNG = "MVF-Pressemeldung/1.0 (+https://www.monitor-versorgungsforschung.de)"

# Standbild fuer Meldungen ohne eigenes Bild. Steht hier als Nummer aus der
# Mediathek; wird es neu hochgeladen, aendert sich die Nummer. Mit `--bild`
# laedt das Skript stattdessen ein eigenes Bild hoch. 0 heisst: kein Bild,
# dann setzt die Redaktion eines - das ist der einzige Handgriff, der bleibt.
WP_STANDBILD = 0

# Die Mediathek ist mit dem Plugin Wicked Folders in Ordner geteilt. Bilder,
# die einfach hochgeladen werden, landen in keinem davon und sind fuer die
# Redaktion praktisch verschwunden. Deshalb wandern sie hier gleich in den
# Ordner, in dem Anke Heiser ihre Newsbilder sammelt:
#   News (15)
#     News Logos (14)
#     News_Abbildungen (2117)   <- hierhin
# ("News Abbildungen" mit Leerzeichen, Nr. 2052, ist eine Dublette und haengt
# unter "Logos auf der Seite" - nicht verwechseln.)
WP_MEDIENORDNER = 2117
# Welches Logo zu welchem Absender gehoert. Die Liste waechst von selbst:
# Was die Redaktion als Beitragsbild waehlt, traegt `pressemeldung.py lernen`
# nach. Von Hand vorbelegt sind nur die Faelle, die eindeutig waren - eine
# Volltextsuche in der Mediathek traf zu oft daneben (kvsachsen -> AOK
# Niedersachsen, gehe.de -> "geheimpreise").
LOGO_DATEI = pathlib.Path(__file__).with_name("logos.json")
# Zwischenspeicher: welcher Entwurf zu welchem Absender gehoert, solange die
# Redaktion das Bild noch nicht gesetzt hat.
WARTE_DATEI = pathlib.Path(__file__).with_name("logos-offen.json")
# Was die Redaktion einmal gewaehlt hat, ist noch kein Logo: Fuer eine
# einzelne Meldung passt oft ein Diagramm oder ein Artikelbild. Ein Logo
# wiederholt sich - deshalb zaehlt eine Wahl erst beim zweiten Mal, es sei
# denn, der Dateiname sagt selbst "logo".
KANDIDATEN_DATEI = pathlib.Path(__file__).with_name("logos-kandidaten.json")
LERN_TAGE = 30
WF = ("https://www.monitor-versorgungsforschung.de/wp-json/"
      "wicked-folders/v1")

# Die Schlagwoerter der Newsseite, Stand 20.08.2026. Nachsehen laesst sich
# das unter /wp-json/wp/v2/tags?per_page=100 - die Nummern sind stabil,
# solange niemand ein Schlagwort loescht und neu anlegt.
SCHLAGWOERTER = {
    "Gesundheitspolitik": 1041,
    "Versorgungsmanagement": 1046,
    "Digitalisierung": 1037,
    "Studie": 1039,
    "Indikationen": 1044,
    "Pflege": 2116,
    "Personalie": 1040,
    "Pandemie": 1045,
    "Termine": 2722,
    "Innovationen": 2056,
    "Vermischtes": 2920,
    "Register": 1042,
    "AMNOG": 1043,
    "Knowledge-Hubs": 2923,
    "Mindestmenge": 2251,
}

MODELL = os.environ.get("MODEL", "claude-opus-5")

# Dieser Prompt steht bewusst MIT Umlauten - in den Tagesnews hat das Modell
# die ASCII-Ersatzschreibung seiner Anweisung in den Fliesstext uebernommen.
SYSTEM = (
    "Du bereitest Pressemitteilungen für die Nachrichtenseite von Monitor "
    "Versorgungsforschung auf, einem Fachmagazin für Versorgungsforschung. "
    "Die Leserschaft arbeitet im deutschen Gesundheitswesen: Kliniken, "
    "Praxen, Kostenträger, Selbstverwaltung, Politik. Sie ist fachkundig und "
    "hat wenig Zeit.\n"
    "Du referierst die Mitteilung, du übernimmst sie nicht. Werbesprache, "
    "Selbstlob und Ausrufezeichen des Absenders fallen weg oder werden dem "
    "Absender ausdrücklich zugeschrieben ('nach Angaben des Verbands'). "
    "Wörtliche Zitate bleiben im Wortlaut und in Anführungszeichen, mit "
    "Namen und Funktion der zitierten Person. Zahlen und Daten bleiben exakt "
    "so, wie sie in der Quelle stehen - nichts hinzufügen, nichts runden, "
    "nichts schätzen.\n"
    "Siezen. Keine Superlative, keine leeren Wendungen wie 'spannende "
    "Einblicke'. Schreibe durchgehend korrekte deutsche Rechtschreibung mit "
    "Umlauten (ä, ö, ü, ß) - niemals die Ersatzschreibung ae, oe, ue, ss."
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["titel", "textauszug", "absaetze", "schlagwort"],
    "properties": {
        "titel": {"type": "string"},
        "textauszug": {"type": "string"},
        "absaetze": {"type": "array", "items": {"type": "string"}},
        # Nur Adressen, die in der Quelle stehen - siehe adressen().
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url", "anker"],
                "properties": {
                    "url": {"type": "string"},
                    "anker": {"type": "string"},
                    "einleitung": {"type": "string"},
                },
            },
        },
        "hintergrund": {"type": "string"},
        "schlagwort": {"type": "string", "enum": sorted(SCHLAGWOERTER)},
    },
}


# --------------------------------------------------------------- Quelle lesen
def text_aus_pdf(pfad: pathlib.Path) -> str:
    from pypdf import PdfReader
    return "\n".join(s.extract_text() or "" for s in PdfReader(str(pfad)).pages)


def text_aus_mail(pfad: pathlib.Path) -> str:
    """Der Textteil einer weitergeleiteten Mail - HTML nur als Rueckfall."""
    import email
    import email.policy
    nachricht = email.message_from_bytes(pfad.read_bytes(),
                                         policy=email.policy.default)
    teile = [nachricht.get("Subject", "")]
    teil = nachricht.get_body(preferencelist=("plain", "html"))
    if teil is not None:
        inhalt = teil.get_content()
        teile.append(entkleide(inhalt)
                     if teil.get_content_type() == "text/html" else inhalt)
    for anhang in nachricht.iter_attachments():
        if anhang.get_content_type() == "application/pdf":
            teile.append(text_aus_pdf_bytes(anhang.get_payload(decode=True)))
    return "\n\n".join(teile)


def text_aus_pdf_bytes(rohdaten: bytes) -> str:
    """Ein PDF, das nur im Arbeitsspeicher liegt - etwa als Mailanhang."""
    import io
    from pypdf import PdfReader
    return "\n".join(s.extract_text() or ""
                     for s in PdfReader(io.BytesIO(rohdaten)).pages)


def text_aus_msg(pfad: pathlib.Path) -> str:
    """Eine aus Outlook abgelegte Nachricht (.msg) samt PDF-Anhaengen."""
    import extract_msg
    nachricht = extract_msg.Message(str(pfad))
    teile = [nachricht.subject or "", nachricht.body or ""]
    for anhang in nachricht.attachments:
        name = (anhang.longFilename or anhang.shortFilename or "").lower()
        if name.endswith(".pdf") and isinstance(anhang.data, bytes):
            teile.append(text_aus_pdf_bytes(anhang.data))
    return "\n\n".join(teile)


def text_aus_outlook() -> str:
    """Die Mail, die in Outlook gerade offen ist - sonst die markierte.

    So ist der Weg fuer die Redaktion der kuerzeste: Mitteilung lesen, Skript
    starten, fertig. Nichts abspeichern, nichts umbenennen, kein PDF drucken.
    """
    import tempfile
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = None
    fenster = outlook.ActiveInspector()
    if fenster is not None:
        mail = fenster.CurrentItem            # die geoeffnete Mail
    else:
        ansicht = outlook.ActiveExplorer()
        auswahl = ansicht.Selection if ansicht is not None else None
        if auswahl is not None and auswahl.Count:
            mail = auswahl.Item(1)            # die markierte Mail
    if mail is None:
        raise SystemExit("In Outlook ist keine Mail offen oder markiert.")
    return text_aus_mailobjekt(mail)


def text_aus_mailobjekt(mail, laut: bool = True) -> str:
    """Betreff, Text und die PDF-Anhaenge einer Outlook-Nachricht."""
    import tempfile

    teile = [str(getattr(mail, "Subject", "")), str(getattr(mail, "Body", ""))]
    # Anhaenge kann nur Outlook selbst herausgeben, und nur als Datei.
    ordner = pathlib.Path(tempfile.mkdtemp(prefix="pm-anhang-"))
    for anhang in mail.Attachments:
        name = str(anhang.FileName)
        if not name.lower().endswith(".pdf"):
            continue
        ziel = ordner / name
        anhang.SaveAsFile(str(ziel))
        teile.append(text_aus_pdf(ziel))
        if laut:
            print(f"Anhang gelesen: {name}")
    return "\n\n".join(teile)


# Woran eine Pressemitteilung im Posteingang zu erkennen ist. Abgelesen an
# 120 Mails, die Peter Stegmaier an die Redaktion weitergeleitet hat, und am
# laufenden Betrieb.
#
# Geprueft wird der *oertliche Teil* der Adresse, nicht die ganze Zeichenkette:
# Eine Liste mit "presse@" liess `presseabteilung@news.ifo.de` durchfallen -
# das Klammeraffe stand im Weg. Jetzt genuegt es, dass der Teil vor dem @ eines
# dieser Woerter enthaelt.
PM_POSTFACH = ("presse", "press", "medien", "media", "kommunikation",
               "communication", "newsroom", "pressoffice", "infodienst")
PM_BETREFF = ("pressemitteilung", "pressemeldung", "presseinformation",
              "presseinfo", "presseerklärung", "pressestatement",
              "presse-information", "pm:", "pm |", "pm //")

# Was dieselben Verteiler sonst noch schicken und was keine Meldung ergibt.
# Der G-BA-Infodienst etwa verschickt Beschluesse und Stellenangebote ueber
# dieselbe Adresse wie seine Pressemitteilungen.
PM_NICHT = ("stellenangebot", "einladung", "save the date", "terminhinweis",
            "inkrafttreten von beschlüssen", "newsletter", "abmeldung",
            "pressegespräch", "pressekonferenz", "akkreditierung",
            "veranstaltungshinweis", "reminder:", "ankündigung buch")


def ist_pressemitteilung(absender: str, betreff: str,
                         anfang: str = "") -> bool:
    """Absender, Betreff - und zur Not der Anfang des Textes.

    Die dritte Stufe faengt Mitteilungen, die weder ein Pressepostfach noch
    ein Signalwort im Betreff tragen: Steht "Pressemitteilung" im Kopf des
    Textes, ist es eine.
    """
    absender, betreff = absender.lower(), betreff.lower()
    if any(m in betreff for m in PM_NICHT):
        return False
    oertlich = absender.split("@")[0]
    if any(m in oertlich for m in PM_POSTFACH):
        return True
    if any(m in betreff for m in PM_BETREFF):
        return True
    return any(m in anfang[:400].lower() for m in PM_BETREFF)


def entkleide(roh: str) -> str:
    """HTML auf Text herunterbrechen - ohne Fremdbibliothek."""
    roh = re.sub(r"(?is)<(script|style|nav|footer)[^>]*>.*?</\1>", " ", roh)
    roh = re.sub(r"(?i)<(p|br|div|li|tr|h[1-6])[^>]*>", "\n", roh)
    roh = re.sub(r"<[^>]+>", " ", roh)
    return html.unescape(roh)


def hole(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": KENNUNG})
    with urllib.request.urlopen(req, timeout=60) as r:
        roh = r.read()
        art = r.headers.get_content_type()
    if art == "application/pdf":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(roh)
        return text_aus_pdf(pathlib.Path(f.name))
    text = roh.decode("utf-8", "replace")
    return entkleide(text) if art == "text/html" else text


def quelle_lesen(quelle: str) -> str:
    if quelle.lower() == "outlook":
        return saeubern(text_aus_outlook())
    if quelle.startswith(("http://", "https://")):
        return saeubern(hole(quelle))
    pfad = pathlib.Path(quelle)
    if not pfad.exists():
        raise SystemExit(f"Nicht gefunden: {pfad}")
    endung = pfad.suffix.lower()
    if endung == ".pdf":
        roh = text_aus_pdf(pfad)
    elif endung == ".eml":
        roh = text_aus_mail(pfad)
    elif endung == ".msg":
        roh = text_aus_msg(pfad)
    elif endung in (".html", ".htm"):
        roh = entkleide(pfad.read_text(encoding="utf-8", errors="replace"))
    else:
        roh = pfad.read_text(encoding="utf-8", errors="replace")
    return saeubern(roh)


# Zeilen, die in jeder Verteiler-Mail stehen und in keiner Meldung.
BALLAST = re.compile(
    r"(?i)(nicht richtig angezeigt|aus dem verteiler abzumelden|"
    r"^\s*(von|an|gesendet|betreff)\s*:|^\s*seite \d+|^\s*\d+\s*$)")


def saeubern(text: str) -> str:
    zeilen = [z.rstrip() for z in text.replace("\r", "").split("\n")]
    zeilen = [z for z in zeilen if not BALLAST.search(z)]
    text = "\n".join(zeilen)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def adressen(text: str) -> list[str]:
    """Die Adressen, die in der Quelle wirklich stehen - die Erlaubnisliste."""
    roh = re.findall(r"https?://[^\s<>\"')\]]+", text)
    sauber, gesehen = [], set()
    for u in roh:
        u = u.rstrip(".,;:")
        # Ab- und Anmeldelinks der Verteilersoftware gehoeren nicht in die
        # Meldung; sie tragen oft auch eine Kennung des Empfaengers.
        if re.search(r"(?i)abmeld|unsubscribe|optout|mailchi\.mp", u):
            continue
        if u not in gesehen:
            gesehen.add(u)
            sauber.append(u)
    return sauber


# ---------------------------------------------------------------- Schreiben
def schreibe_meldung(text: str, links: list[str], hinweis: str = "") -> dict:
    import anthropic

    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt - keine Meldung geschrieben.")

    erlaubt = "\n".join(f"- {u}" for u in links) or "- (keine)"
    auftrag = (
        "Hier ist eine Pressemitteilung im Wortlaut. Mache daraus eine "
        "Meldung für die Newsseite.\n\n"
        "- titel: eine Zeile, höchstens 75 Zeichen. **Die Sache steht vorn, "
        "der Absender dahinter**, getrennt durch einen Doppelpunkt - also "
        "'Mehr Prävention für Kinder: DAK-Gesundheit begrüßt G-BA-Entscheidung' "
        "und nicht 'DAK-Gesundheit: Mehr Prävention für Kinder'. Wer die "
        "Meldung überfliegt, soll am Anfang der Zeile lesen, worum es geht.\n"
        "- textauszug: zwei Sätze, zusammen höchstens 300 Zeichen. Sie stehen "
        "als Vorspann in Listen und bei Suchmaschinen und kommen im Fließtext "
        "NICHT noch einmal vor. Länger ist nicht besser: Suchmaschinen "
        "schneiden ab.\n"
        "- absaetze: vier bis sieben Absätze Fließtext, je zwei bis vier "
        "Sätze. Das Wichtigste zuerst. Höchstens zwei wörtliche Zitate, im "
        "Wortlaut. Keine Zwischenüberschriften, kein HTML, keine Adressen.\n"
        "- links: nur Adressen aus der folgenden Liste, höchstens zwei, mit "
        "sprechendem Ankertext. Keine Adresse erfinden, keine abwandeln. "
        "Passt keine, lass die Liste leer.\n"
        f"{erlaubt}\n"
        "- hintergrund: ein kurzer Absatz, der die absendende Institution "
        "einordnet (Rechtsform, Auftrag, Größe) - nur aus der Quelle. Steht "
        "am Ende der Meldung. Fehlt in der Quelle alles dazu, lass ihn weg.\n"
        "- schlagwort: genau eines aus der Hausliste, und zwar das inhaltlich "
        "nächstliegende. 'Vermischtes' ist die Notlösung für Meldungen, die "
        "wirklich in keine Rubrik passen - nicht die bequeme Wahl, wenn zwei "
        "Rubriken in Frage kommen. Geht es um Selbstverwaltung, Gesetzgebung, "
        "Verbände oder Finanzierung, ist es 'Gesundheitspolitik'.\n"
        "Lass Anrede, Kopfzeilen, Kontaktblock und Verteilerhinweise der "
        "Mitteilung weg. Steht ein Absatz in der Quelle doppelt, nimm ihn "
        "einmal.\n"
    )
    if hinweis:
        auftrag += f"\nZusätzlicher Hinweis der Redaktion: {hinweis}\n"
    auftrag += f"\n--- Pressemitteilung ---\n{text[:60000]}"

    antwort = anthropic.Anthropic(api_key=schluessel).messages.create(
        model=MODELL,
        max_tokens=4000,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": auftrag}],
    )
    return json.loads(next(b.text for b in antwort.content if b.type == "text"))


def escape(t: str) -> str:
    return html.escape(t or "", quote=True)


def baue_html(meldung: dict, erlaubt: list[str]) -> str:
    teile = [f"<p>{escape(a)}</p>" for a in meldung.get("absaetze", []) if a.strip()]

    for link in meldung.get("links", []):
        url = link.get("url", "")
        if url not in erlaubt:        # erfunden oder abgewandelt - faellt weg
            print(f"Hinweis: Adresse nicht in der Quelle, weggelassen: {url}")
            continue
        vorne = link.get("einleitung", "").strip()
        vorne = f"{escape(vorne)} " if vorne else ""
        teile.append(
            f'<p>{vorne}<a href="{escape(url)}" target="_blank" '
            f'rel="noopener">{escape(link.get("anker") or url)}</a></p>')

    if meldung.get("hintergrund"):
        teile.append(f"<p>{escape(meldung['hintergrund'])}</p>")
    return "\n".join(teile)


# ------------------------------------------------------------ Absenderlogos
def domain_von(adresse: str) -> str:
    treffer = re.search(r"@([\w.-]+\.\w{2,})", adresse or "")
    return treffer.group(1).lower() if treffer else ""


def logos_laden() -> dict:
    try:
        return json.loads(LOGO_DATEI.read_text(encoding="utf-8"))
    except Exception:
        return {}


def logos_schreiben(logos: dict) -> None:
    LOGO_DATEI.write_text(json.dumps(logos, ensure_ascii=False, indent=1,
                                     sort_keys=True), encoding="utf-8")


def warteliste() -> list:
    try:
        return json.loads(WARTE_DATEI.read_text(encoding="utf-8"))
    except Exception:
        return []


def merken(beitrag: int, domain: str, gesetzt: int) -> None:
    """Notieren, zu welchem Absender ein Entwurf gehoert.

    `gesetzt` ist das Bild, das dieses Skript vorgeschlagen hat. Nur wenn die
    Redaktion spaeter ein *anderes* waehlt, ist das eine Aussage ueber den
    Absender - das eigene Diagramm einer einzelnen Mitteilung taugt nicht als
    Logo fuer alle kuenftigen.
    """
    if not domain:
        return
    liste = [e for e in warteliste() if e.get("beitrag") != beitrag]
    liste.append({"beitrag": beitrag, "domain": domain, "gesetzt": gesetzt,
                  "datum": dt_heute()})
    WARTE_DATEI.write_text(json.dumps(liste, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def lernen() -> int:
    """Die Wahl der Redaktion nachtragen - aber erst, wenn sie sich bestaetigt.

    Fuer jeden vorgemerkten Entwurf wird nachgesehen, welches Beitragsbild
    inzwischen daran haengt. Ein anderes als das vorgeschlagene ist eine
    Aussage der Redaktion; in die Logoliste kommt es aber erst, wenn dieselbe
    Wahl zum zweiten Mal faellt. Ausnahme: Traegt die Datei "logo" im Namen,
    ist die Sache schon beim ersten Mal klar.
    """
    import datetime

    kopf = zugang()
    if kopf is None:
        print("WPUSER oder WPPASSWORT fehlt - nichts zu lernen.")
        return 1
    logos, offen = logos_laden(), warteliste()
    try:
        kandidaten = json.loads(KANDIDATEN_DATEI.read_text(encoding="utf-8"))
    except Exception:
        kandidaten = {}

    bleibt, gelernt, vorgemerkt = [], 0, 0
    for eintrag in offen:
        try:
            d = wp_ruf(f"/posts/{eintrag['beitrag']}"
                       f"?context=edit&_fields=id,status,featured_media", kopf)
        except urllib.error.HTTPError:
            continue                    # geloescht - Eintrag faellt weg
        bild = d.get("featured_media") or 0
        if bild and bild != eintrag.get("gesetzt"):
            domain = eintrag["domain"]
            zaehler = kandidaten.setdefault(domain, {})
            zaehler[str(bild)] = zaehler.get(str(bild), 0) + 1
            try:
                m = wp_ruf(f"/media/{bild}?_fields=slug", kopf)
                heisst_logo = "logo" in str(m.get("slug", "")).lower()
            except Exception:
                heisst_logo = False
            if zaehler[str(bild)] >= 2 or heisst_logo:
                logos[domain] = bild
                gelernt += 1
                grund = "Dateiname" if heisst_logo else "zweite Wahl"
                print(f"  gelernt: {domain} -> Bild {bild} ({grund})")
            else:
                vorgemerkt += 1
                print(f"  vorgemerkt: {domain} -> Bild {bild} "
                      f"(einmal gewaehlt, wartet auf Bestaetigung)")
            continue
        alt = (datetime.date.today()
               - datetime.date.fromisoformat(eintrag["datum"])).days
        if alt < LERN_TAGE and d.get("status") == "draft":
            bleibt.append(eintrag)      # wartet noch auf die Redaktion
    logos_schreiben(logos)
    KANDIDATEN_DATEI.write_text(
        json.dumps(kandidaten, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    WARTE_DATEI.write_text(json.dumps(bleibt, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"{gelernt} gelernt, {vorgemerkt} vorgemerkt, {len(bleibt)} offen, "
          f"{len(logos)} Logos insgesamt.")
    return 0


# -------------------------------------------------------------- WordPress
def zugang() -> str | None:
    nutzer = os.environ.get("WPUSER", "").strip()
    passwort = os.environ.get("WPPASSWORT", "").strip()
    if not (nutzer and passwort):
        return None
    return base64.b64encode(f"{nutzer}:{passwort}".encode()).decode()


def wp_ruf(pfad: str, kopf: str, daten: bytes | None = None,
           art: str = "application/json", methode: str = "GET") -> dict:
    kopfzeilen = {"Authorization": f"Basic {kopf}",
                  "User-Agent": KENNUNG,
                  "Accept": "application/json"}
    if daten is not None:
        kopfzeilen["Content-Type"] = art
    req = urllib.request.Request(f"{WP}{pfad}", data=daten, method=methode,
                                 headers=kopfzeilen)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def schon_da(titel: str, kopf: str) -> dict | None:
    """Dieselbe Mitteilung zweimal einzuspielen passiert leicht - einmal aus
    der Mail, einmal von der Webseite. Vor dem Anlegen wird nachgesehen."""
    frage = urllib.parse.urlencode({"search": titel[:60],
                                    "status": "draft,pending,publish",
                                    "per_page": 5,
                                    "_fields": "id,title,status,link"})
    try:
        for e in wp_ruf(f"/posts?{frage}", kopf):
            if e["title"]["rendered"].strip().lower()[:40] == titel.strip().lower()[:40]:
                return e
    except urllib.error.HTTPError:
        pass                            # Suche gescheitert - lieber anlegen
    return None


def in_ordner(medien: list[int], kopf: str,
              ordner: int = WP_MEDIENORDNER) -> None:
    """Hochgeladene Bilder in den Mediathek-Ordner der Redaktion einsortieren."""
    if not medien:
        return
    koerper = json.dumps({"post_type": "attachment",
                          "post_ids": medien}).encode("utf-8")
    req = urllib.request.Request(
        f"{WF}/folders/{ordner}/assign", data=koerper, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {kopf}",
                 "User-Agent": KENNUNG,
                 "Accept": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60)
        print(f"  Einsortiert in Mediathek-Ordner {ordner}")
    except urllib.error.HTTPError as e:
        # Nicht schlimm: Das Bild ist hochgeladen, es liegt nur im Wurzelordner.
        print(f"  Einsortieren fehlgeschlagen (HTTP {e.code}) - "
              f"Bild liegt in der Mediathek ohne Ordner.")


def bilder_aus_pdf(pfad: pathlib.Path) -> list[tuple[str, bytes]]:
    """Die Bilder aus der Mitteilung - Logos, Diagramme, Fotos.

    Anke braucht ein Beitragsbild, und das Material dafuer steckt meist schon
    in der Mitteilung. Zu kleine Bilder faellt weg: Aufzaehlungspunkte,
    Trennlinien und Briefkopf-Schnipsel taugen nicht als Beitragsbild.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    gefunden = []
    for nummer, seite in enumerate(PdfReader(str(pfad)).pages, 1):
        try:
            bilder = list(seite.images)
        except Exception:
            continue                    # ohne Pillow gibt es keine Bilder
        for lfd, bild in enumerate(bilder, 1):
            breite = getattr(getattr(bild, "image", None), "width", 0) or 0
            if breite < 300:
                continue
            endung = pathlib.Path(bild.name).suffix or ".png"
            gefunden.append((f"seite{nummer}-bild{lfd}{endung}", bild.data))
    return gefunden


def bilder_aus_mailobjekt(mail) -> list[tuple[str, bytes]]:
    """Das Bildmaterial einer Outlook-Nachricht.

    Zweierlei kommt in Frage: Bilder, die als Datei anhaengen, und Bilder in
    einem angehaengten PDF. Beides wird nach Breite gesiebt - was schmaler
    als 300 Pixel ist, ist Signaturschmuck, kein Beitragsbild.
    """
    import tempfile

    gefunden = []
    ordner = pathlib.Path(tempfile.mkdtemp(prefix="pm-mailbild-"))
    for anhang in mail.Attachments:
        name = str(anhang.FileName)
        endung = pathlib.Path(name).suffix.lower()
        if endung not in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
            continue
        ziel = ordner / name
        try:
            anhang.SaveAsFile(str(ziel))
        except Exception:
            continue
        if endung == ".pdf":
            gefunden.extend(bilder_aus_pdf(ziel))
            continue
        if breit_genug(ziel):
            gefunden.append((name, ziel.read_bytes()))
    return gefunden


def breit_genug(pfad: pathlib.Path, mindestens: int = 300) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return True                     # ohne Pillow lieber mitnehmen
    try:
        with Image.open(pfad) as bild:
            return bild.width >= mindestens
    except Exception:
        return False


def masse(rohdaten: bytes) -> tuple[int, int]:
    """Breite und Hoehe eines Bildes im Arbeitsspeicher."""
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(rohdaten)) as bild:
            return bild.width, bild.height
    except Exception:
        return 0, 0


def bestes_bild(bilder: list[tuple[str, bytes]]) -> int:
    """Welches Bild traegt die Meldung am ehesten?

    Das flaechenmaessig groesste. Briefkoepfe und Signaturlogos sind breite
    schmale Streifen; ein Diagramm oder ein Foto hat mehr Flaeche. Perfekt
    ist die Regel nicht - deshalb setzt sie nur einen Vorschlag, den die
    Redaktion im Beitrag mit zwei Klicks austauscht.
    """
    beste, bester_wert = 0, -1
    for nummer, (_, rohdaten) in enumerate(bilder):
        breite, hoehe = masse(rohdaten)
        wert = breite * hoehe or len(rohdaten)
        if wert > bester_wert:
            beste, bester_wert = nummer, wert
    return beste


# Breite der Bilder in der Mediathek. Die Redaktion legt Newsbilder in dieser
# Groesse ab (U10-Meldung 300x150, Tagesnews-Logo 300x158) - alles Groessere
# waere Ballast, denn die Newsliste zeigt die Bilder ohnehin klein.
BILDBREITE = 300


def verkleinern(name: str, rohdaten: bytes) -> tuple[str, bytes]:
    """Auf BILDBREITE bringen, Seitenverhaeltnis behalten.

    Nur verkleinern, nie vergroessern: Ein 200 Pixel breites Logo wuerde beim
    Hochrechnen nur unschaerfer. PNG bleibt PNG (Logos mit klaren Kanten),
    alles andere wird JPEG.
    """
    try:
        import io

        from PIL import Image
    except ImportError:
        return name, rohdaten
    try:
        with Image.open(io.BytesIO(rohdaten)) as bild:
            if bild.width <= BILDBREITE:
                return name, rohdaten
            hoehe = round(bild.height * BILDBREITE / bild.width)
            klein = bild.convert("RGBA" if bild.mode == "RGBA" else "RGB")
            klein = klein.resize((BILDBREITE, hoehe), Image.LANCZOS)
            eimer = io.BytesIO()
            if klein.mode == "RGBA":
                klein.save(eimer, "PNG", optimize=True)
                name = pathlib.Path(name).with_suffix(".png").name
            else:
                klein.save(eimer, "JPEG", quality=85, optimize=True)
                name = pathlib.Path(name).with_suffix(".jpg").name
            return name, eimer.getvalue()
    except Exception:
        return name, rohdaten


def bilder_anhaengen(bilder: list[tuple[str, bytes]], beitrag: int,
                     kopf: str, titel: str) -> list[int]:
    """Die Bilder der Mitteilung an den Entwurf haengen.

    Angehaengt heisst: Im Dialog *Beitragsbild festlegen* stehen sie unter
    "Hochgeladen zu diesem Beitrag" ganz vorn. Ausgewaehlt wird trotzdem von
    Hand - welches Bild eine Meldung traegt, entscheidet die Redaktion.
    """
    neue = []
    for name, rohdaten in bilder:
        vorher = len(rohdaten)
        name, rohdaten = verkleinern(name, rohdaten)
        if len(rohdaten) < vorher:
            print(f"  {name}: {vorher // 1024} KB -> "
                  f"{len(rohdaten) // 1024} KB ({BILDBREITE} Pixel breit)")
        art = mimetypes.guess_type(name)[0] or "image/png"
        kopfzeilen = {"Authorization": f"Basic {kopf}",
                      "User-Agent": KENNUNG,
                      "Content-Type": art,
                      "Content-Disposition": f'attachment; filename="{name}"'}
        req = urllib.request.Request(f"{WP}/media", data=rohdaten,
                                     method="POST", headers=kopfzeilen)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            wp_ruf(f"/media/{d['id']}", kopf,
                   json.dumps({"post": beitrag, "alt_text": titel,
                               "title": f"Aus der Pressemitteilung: {titel}"}
                              ).encode("utf-8"), methode="POST")
            neue.append(d["id"])
            print(f"  Bild aus der Mitteilung angehaengt: {d.get('source_url','')}")
        except urllib.error.HTTPError as e:
            print(f"  Bild {name} nicht hochgeladen: HTTP {e.code}")
    in_ordner(neue, kopf)
    return neue


def bild_hochladen(pfad: pathlib.Path, kopf: str, titel: str) -> int:
    art = mimetypes.guess_type(pfad.name)[0] or "application/octet-stream"
    kopfzeilen = {"Authorization": f"Basic {kopf}",
                  "User-Agent": KENNUNG,
                  "Content-Type": art,
                  "Content-Disposition": f'attachment; filename="{pfad.name}"'}
    req = urllib.request.Request(f"{WP}/media", data=pfad.read_bytes(),
                                 method="POST", headers=kopfzeilen)
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    # Der Alternativtext gehoert zur Barrierefreiheit und wird sonst vergessen.
    try:
        wp_ruf(f"/media/{d['id']}", kopf,
               json.dumps({"alt_text": titel}).encode("utf-8"), methode="POST")
    except urllib.error.HTTPError:
        pass
    in_ordner([d["id"]], kopf)
    print(f"Bild hochgeladen: {d['id']} ({d.get('source_url','')})")
    return d["id"]


def entwurf(meldung: dict, inhalt: str, bild: pathlib.Path | None,
            trocken: bool, quelle: pathlib.Path | None = None,
            bilder: list[tuple[str, bytes]] | None = None,
            domain: str = "") -> bool:
    """Legt den Entwurf an. Rueckgabe: ob wirklich einer entstanden ist -
    beim Postfachlauf soll die Zaehlung nicht Dubletten mitzaehlen."""
    kopf = zugang()
    if kopf is None:
        print("WPUSER oder WPPASSWORT fehlt - kein Entwurf angelegt.")
        return False

    doppelt = schon_da(meldung["titel"], kopf)
    if doppelt:
        print(f"Gibt es schon ({doppelt['status']}, Nr. {doppelt['id']}): "
              f"{doppelt.get('link','')}")
        print("Kein zweiter Entwurf angelegt.")
        return False

    if trocken:
        print(f"[trocken] Entwurf waere angelegt: {meldung['titel']}")
        return False

    felder = {
        "title": meldung["titel"],
        "content": inhalt,
        "status": "draft",             # NIE veroeffentlichen - das macht die Redaktion
        "categories": [WP_KATEGORIE],
        "excerpt": meldung.get("textauszug", ""),
        "tags": [SCHLAGWOERTER[meldung["schlagwort"]]],
    }
    nummer = bild_hochladen(bild, kopf, meldung["titel"]) if bild else WP_STANDBILD
    if nummer:
        felder["featured_media"] = nummer

    try:
        d = wp_ruf("/posts", kopf, json.dumps(felder).encode("utf-8"),
                   methode="POST")
    except urllib.error.HTTPError as e:
        # Der Wortlaut aus WordPress sagt, woran es lag - ohne ihn raet man nur.
        print(f"WordPress lehnt ab: HTTP {e.code} {e.reason}")
        print(f"  Antwort: {e.read().decode('utf-8', 'replace')[:600]}")
        return False
    print(f"Entwurf angelegt: Nr. {d['id']}")
    print(f"  Bearbeiten: https://www.monitor-versorgungsforschung.de/"
          f"wp-admin/post.php?post={d['id']}&action=edit")

    # Das Bildmaterial der Mitteilung gleich mit an den Entwurf haengen -
    # sonst muesste die Redaktion die Quelle erst wieder heraussuchen.
    if bilder is None and quelle is not None and quelle.suffix.lower() == ".pdf":
        bilder = bilder_aus_pdf(quelle)
    hochgeladen = []
    if bilder:
        print(f"  {len(bilder)} Bild(er) aus der Mitteilung:")
        hochgeladen = bilder_anhaengen(bilder, d["id"], kopf, meldung["titel"])

    # Immer eines eintragen: Ein Entwurf ohne Bild sieht in der Liste aus wie
    # ein Fehler. Welches es am Ende wird, entscheidet die Redaktion - das
    # Austauschen kostet zwei Klicks, das erste Suchen kostet Minuten.
    if not nummer and hochgeladen:
        vorschlag = hochgeladen[min(bestes_bild(bilder), len(hochgeladen) - 1)]
        try:
            wp_ruf(f"/posts/{d['id']}", kopf,
                   json.dumps({"featured_media": vorschlag}).encode("utf-8"),
                   methode="POST")
            nummer = vorschlag
            print(f"  Beitragsbild vorgeschlagen: Nr. {vorschlag}")
        except urllib.error.HTTPError as e:
            print(f"  Beitragsbild nicht gesetzt: HTTP {e.code}")

    # Enthaelt die Mitteilung kein Bild, kommt das Logo des Absenders zum
    # Zug - sofern eines bekannt ist.
    if not nummer and domain:
        aus_liste = logos_laden().get(domain)
        if aus_liste:
            try:
                wp_ruf(f"/posts/{d['id']}", kopf,
                       json.dumps({"featured_media": aus_liste}).encode("utf-8"),
                       methode="POST")
                nummer = aus_liste
                print(f"  Logo des Absenders eingetragen: Nr. {aus_liste}")
            except urllib.error.HTTPError as e:
                print(f"  Logo nicht gesetzt: HTTP {e.code}")

    # Vormerken, damit `lernen` spaeter sieht, wofuer sich die Redaktion
    # entschieden hat.
    merken(d["id"], domain, nummer or 0)

    if not nummer:
        print("  Kein Bild in der Mitteilung und kein Logo bekannt - die "
              "Redaktion waehlt eines unter 'Beitragsbild festlegen'.")
    return True


# -------------------------------------------------------------------- Ablage
def ablageordner() -> pathlib.Path:
    """Wohin die Mitteilung samt Vorschau wandert.

    Die Redaktion braucht die Quelle noch, wenn der Entwurf laengst steht -
    fuer das Beitragsbild, fuer Rueckfragen, fuer die Ablage. Liegt ein
    OneDrive-Ordner vor, kommt sie dorthin: Dann findet Anke Heiser sie auch
    von ihrem Rechner aus.
    """
    eigen = os.environ.get("PM_ABLAGE", "").strip()
    if eigen:
        return pathlib.Path(eigen)
    heim = pathlib.Path.home()
    # Das geschaeftliche OneDrive zuerst ("OneDrive - eRelation AG"): Dort
    # kommt die Redaktion heran, im privaten nicht.
    kandidaten = sorted((k for k in heim.glob("OneDrive*") if k.is_dir()),
                        key=lambda k: (" - " not in k.name, k.name))
    if kandidaten:
        return kandidaten[0] / "Pressemeldungen"
    return heim / "Documents" / "Pressemeldungen"


def ablegen(meldung: dict, inhalt: str, quelltext: str,
            quelle: pathlib.Path | None) -> pathlib.Path:
    kurz = re.sub(r"[^\wäöüßÄÖÜ ]", "", meldung["titel"])[:60].strip()
    kurz = re.sub(r"\s+", "-", kurz).lower()
    ordner = ablageordner() / f"{dt_heute()}-{kurz}"
    ordner.mkdir(parents=True, exist_ok=True)

    if quelle is not None and quelle.exists():
        (ordner / quelle.name).write_bytes(quelle.read_bytes())
    else:
        # Aus Outlook gibt es keine Datei - dann wenigstens den Wortlaut.
        (ordner / "quelle.txt").write_text(quelltext, encoding="utf-8")
    vorschau(meldung, inhalt, ordner / "vorschau.html")
    return ordner


def dt_heute() -> str:
    import datetime
    return datetime.date.today().isoformat()


def dt_jetzt_utc():
    """Jetzt, mit Zeitzone - Outlook liefert Zeitstempel mit Zone, und ohne
    laesst sich das nicht vergleichen."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc)


# ------------------------------------------------------------------- Vorschau
def vorschau(meldung: dict, inhalt: str, ziel: pathlib.Path) -> None:
    """Die Meldung als Seite zum Ansehen - so, wie sie im Beitrag steht."""
    seite = (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{escape(meldung['titel'])}</title>"
        "<style>body{font:17px/1.6 Georgia,serif;max-width:44em;margin:3em auto;"
        "padding:0 1em;color:#222}h1{font:600 30px/1.25 system-ui,sans-serif}"
        ".auszug{font:600 18px/1.5 system-ui,sans-serif;color:#444;"
        "border-left:4px solid #c8102e;padding-left:1em;margin:1.5em 0}"
        ".fuss{font:14px system-ui,sans-serif;color:#666;margin-top:3em;"
        "border-top:1px solid #ddd;padding-top:1em}</style>"
        f"<h1>{escape(meldung['titel'])}</h1>"
        f"<div class='auszug'>{escape(meldung.get('textauszug',''))}</div>"
        f"{inhalt}"
        f"<p class='fuss'>Rubrik News &middot; Schlagwort "
        f"{escape(meldung.get('schlagwort',''))} &middot; Vorschau, "
        f"kein Beitrag auf der Seite</p>")
    ziel.write_text(seite, encoding="utf-8")
    print(f"Vorschau: {ziel}")


class Zweifach:
    """Ausgabe gleichzeitig ins Fenster und ins Protokoll.

    Beim Lauf ueber den Zeitplan gibt es kein Fenster (pyw.exe) - dann faellt
    der erste Kanal einfach weg.
    """

    def __init__(self, *kanaele):
        self.kanaele = [k for k in kanaele if k is not None]

    def write(self, text):
        for k in self.kanaele:
            try:
                k.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self):
        for k in self.kanaele:
            try:
                k.flush()
            except Exception:
                pass


# ------------------------------------------------------------ Postfachlauf
PM_ORDNER = "Pressemitteilungen"
PM_ERLEDIGT = "erledigt"
# Woran das Skript erkennt, dass es eine Mitteilung schon hatte. Bewusst
# nicht am Gelesen-Merkmal: Wer eine Mail oeffnet, um zu sehen, was drinsteht,
# wuerde sie damit aus der Automatik nehmen.
PM_MARKE = "Pressemeldung erledigt"
PM_TAGE = 3                            # aelteres bleibt liegen


def unterordner(eltern, name: str):
    for f in eltern.Folders:
        if str(f.Name).lower() == name.lower():
            return f
    return eltern.Folders.Add(name)


def postfach_durchgehen(hoechstens: int, trocken: bool) -> int:
    """Ungelesene Pressemitteilungen aus dem Posteingang abarbeiten.

    Bewusst ohne Outlook-Regel: In diesem Postfach liegen 210 Regeln, darunter
    eine beschaedigte - Outlook speichert deshalb keine neue mehr. Die
    Merkmale stehen ohnehin besser hier im Skript, wo sie versioniert sind und
    sich aendern lassen, ohne in Outlook zu klicken.
    """
    import win32com.client

    # Zuerst nachsehen, wofuer sich die Redaktion inzwischen entschieden hat -
    # so waechst die Logoliste ohne einen zweiten Zeitplan.
    try:
        lernen()
    except Exception as fehler:
        print(f"Logos lernen fehlgeschlagen: {str(fehler)[:120]}")

    raum = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    posteingang = raum.GetDefaultFolder(6)                  # olFolderInbox
    ziel = unterordner(posteingang, PM_ORDNER)
    erledigt = unterordner(ziel, PM_ERLEDIGT)

    import datetime
    grenze = (dt_jetzt_utc() - datetime.timedelta(days=PM_TAGE))

    kandidaten = []
    for quelle in (ziel, posteingang):                      # Ordner zuerst
        posten = quelle.Items
        posten.Sort("[ReceivedTime]", True)
        for mail in posten:
            if len(kandidaten) >= hoechstens * 4:
                break
            try:
                if mail.Class != 43:                        # 43 = MailItem
                    continue
                if PM_MARKE in str(getattr(mail, "Categories", "")):
                    continue                                # schon gehabt
                if mail.ReceivedTime < grenze:
                    break                                   # ab hier nur Aelteres
                absender = str(getattr(mail, "SenderEmailAddress", ""))
                betreff = str(getattr(mail, "Subject", ""))
            except Exception:
                continue
            # Im Ordner Pressemitteilungen zaehlt jede Mail - dort liegt sie
            # ja, weil jemand sie fuer eine haelt.
            anfang = str(getattr(mail, "Body", ""))[:400]
            if quelle is ziel or ist_pressemitteilung(absender, betreff,
                                                      anfang):
                kandidaten.append(mail)

    if not kandidaten:
        print("Keine neue Pressemitteilung gefunden.")
        return 0

    print(f"{len(kandidaten)} Mitteilung(en) gefunden, "
          f"davon werden {min(hoechstens, len(kandidaten))} bearbeitet.\n")
    fertig = 0
    for mail in kandidaten[:hoechstens]:
        betreff = str(getattr(mail, "Subject", ""))[:70]
        print(f"--- {betreff}")
        try:
            text = saeubern(text_aus_mailobjekt(mail, laut=False))
            if len(text) < 400:
                print("  Zu wenig Text - uebersprungen.\n")
                continue
            meldung = schreibe_meldung(text, adressen(text))
            if meldung.get("schlagwort") not in SCHLAGWOERTER:
                meldung["schlagwort"] = "Vermischtes"
            inhalt = baue_html(meldung, adressen(text))
            print(f"  {meldung['titel']}")
            if trocken:
                print("  [trocken] kein Entwurf, Mail bleibt liegen.\n")
                continue
            neu = entwurf(meldung, inhalt, None, False, None,
                          bilder_aus_mailobjekt(mail),
                          domain_von(str(getattr(mail, "SenderEmailAddress",
                                                 ""))))
            ablegen(meldung, inhalt, text, None)
            # Erst jetzt anfassen: Was schiefgeht, bleibt unmarkiert liegen
            # und kommt beim naechsten Lauf wieder dran.
            vorhanden = str(getattr(mail, "Categories", "")).strip()
            mail.Categories = f"{vorhanden}; {PM_MARKE}".strip("; ")
            mail.UnRead = False
            mail.Save()
            mail.Move(erledigt)
            fertig += 1 if neu else 0
            print()
        except Exception as fehler:
            print(f"  Fehlgeschlagen: {fehler}\n")
    print(f"{fertig} Entwurf/Entwuerfe angelegt.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("quelle",
                   help="'postfach' fuer den Reihum-Lauf, 'outlook' fuer die "
                        "offene Mail, 'lernen' fuer die Logo-Liste, sonst "
                        "PDF, .eml, .msg, HTML-Datei, Textdatei oder URL")
    p.add_argument("--bild", help="Bilddatei fuer das Beitragsbild")
    p.add_argument("--hinweis", default="",
                   help="Zusatz fuer das Modell, etwa 'Fokus auf die Zahlen'")
    p.add_argument("--trocken", action="store_true",
                   help="nur schreiben und anzeigen, nichts anlegen")
    p.add_argument("--vorschau", help="Vorschau-HTML hierhin schreiben")
    p.add_argument("--aus-json", help="fertige Meldung aus Datei statt vom Modell")
    p.add_argument("--hoechstens", type=int, default=5,
                   help="bei 'postfach': wie viele Mitteilungen je Lauf")
    a = p.parse_args()

    if a.quelle.lower() == "lernen":
        return lernen()

    if a.quelle.lower() == "postfach":
        # Der Zeitplan startet das Skript ohne Fenster - was dabei geschieht,
        # muss also in eine Datei, sonst ist es nicht nachvollziehbar.
        protokoll = ablageordner() / "pressemeldung.log"
        protokoll.parent.mkdir(parents=True, exist_ok=True)
        with open(protokoll, "a", encoding="utf-8") as datei:
            import contextlib
            import datetime
            datei.write(f"\n===== {datetime.datetime.now():%d.%m.%Y %H:%M} =====\n")
            with contextlib.redirect_stdout(Zweifach(sys.stdout, datei)):
                return postfach_durchgehen(a.hoechstens, a.trocken)

    text = quelle_lesen(a.quelle)
    if len(text) < 400:
        print(f"Nur {len(text)} Zeichen aus der Quelle gelesen - "
              "ist das PDF ein Scan? Dann braucht es erst eine Texterkennung.")
        return 1
    links = adressen(text)

    if a.aus_json:
        # utf-8-sig: Windows-Programme setzen gern eine Bytefolgemarke davor.
        meldung = json.loads(
            pathlib.Path(a.aus_json).read_text(encoding="utf-8-sig"))
    else:
        meldung = schreibe_meldung(text, links, a.hinweis)

    if meldung.get("schlagwort") not in SCHLAGWOERTER:
        print(f"Unbekanntes Schlagwort {meldung.get('schlagwort')!r} - "
              "Vermischtes gesetzt.")
        meldung["schlagwort"] = "Vermischtes"

    inhalt = baue_html(meldung, links)
    if len(meldung["titel"]) > 75:
        # Laengere Titel schneidet die Trefferliste der Suchmaschinen ab.
        print(f"Hinweis: Titel ist {len(meldung['titel'])} Zeichen lang - "
              "in der Trefferliste bricht er ab.")
    print(f"\nTitel:       {meldung['titel']}  ({len(meldung['titel'])} Zeichen)")
    print(f"Textauszug:  {meldung.get('textauszug','')}")
    print(f"Schlagwort:  {meldung['schlagwort']}\n")
    print(inhalt)

    if a.vorschau:
        vorschau(meldung, inhalt, pathlib.Path(a.vorschau))

    bild = pathlib.Path(a.bild) if a.bild else None
    if bild and not bild.exists():
        raise SystemExit(f"Bild nicht gefunden: {bild}")

    quelldatei = None
    if a.quelle.lower() != "outlook" and not a.quelle.startswith("http"):
        quelldatei = pathlib.Path(a.quelle)

    entwurf(meldung, inhalt, bild, a.trocken, quelldatei)
    if not a.trocken:
        ordner = ablegen(meldung, inhalt, text, quelldatei)
        print(f"  Quelle und Vorschau abgelegt: {ordner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
