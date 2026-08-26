#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Die Tagesnews: ein WordPress-Entwurf und die Liste an die Redaktion.

Aus der Sammeldatei von `studien_sammeln.py` entsteht taeglich zweierlei:

1. Ein **Entwurf auf m-vf.de** in der Kategorie News - kurze Meldung mit ein
   paar Beispielen und Verweisen in die Hubs. Freigegeben wird er von Hand;
   das Skript veroeffentlicht nichts. Der WordPress-Benutzer hat deshalb die
   Rolle Autor und kann gar nicht veroeffentlichen, selbst wenn es wollte.
2. Eine **Mailchimp-Ausgabe an die Redaktion** mit allen Neuzugaengen,
   nach Hub gruppiert.

Beides entsteht **werktags** und aus derselben Menge: montags samt der Studien
vom Wochenende. Die Hubs selbst werden weiter taeglich aktualisiert.

Der Sinn ist der Zulauf: Wer die Meldung auf m-vf.de liest, findet den Weg in
die Hubs - und wird dort vielleicht Abonnent. Deshalb fuehren die Verweise in
die Hubs und nicht zu PubMed.

**Die Verweise baut das Skript, nicht das Sprachmodell.** Es liefert nur Text;
jede Adresse entsteht aus der Sammeldatei. Ein Modell, das URLs erfinden darf,
erfindet sie irgendwann auch.

Aufruf:
    python scripts/tagesnews.py                 # beides
    python scripts/tagesnews.py --nur-wordpress
    python scripts/tagesnews.py --nur-mail
    python scripts/tagesnews.py --trocken       # nur ausgeben, nichts anlegen

Geheimnisse in der Umgebung - benannt wie in den Portalen, nach dem Repo:
    KNOWLEDGEHUBS    Anthropic-Schluessel
    KNOWLEDGEHUBSMC  Mailchimp-Schluessel (MC wie bei IMPFHUBMC)
    WPUSER           WordPress-Benutzer, hier knowledge-hubs (Rolle Autor)
    WPPASSWORT       dessen Anwendungspasswort

(GitHub laesst in Secret-Namen keine Bindestriche zu - daher KNOWLEDGEHUBS
ohne. Im WordPress-Benutzernamen sind sie erlaubt, das ist ein Wert.)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import verwandtes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WP = "https://www.monitor-versorgungsforschung.de/wp-json/wp/v2"
# Steht als Textauszug unter dem Titel und als Meta-Beschreibung in der
# Trefferliste der Suchmaschinen. Bewusst jeden Tag derselbe Satz: Er
# beschreibt die Reihe, nicht den einzelnen Tag.
WP_AUSZUG = ("Aus der Forschung frisch auf den Schreibtisch. "
             "Jeden Tag durch die Knowledge-Hubs von MVF: heute {n} {wort}")
# Das Beitragsbild aus der Mediathek ("TagesnewsLogo.png"). Wird es je neu
# hochgeladen, aendert sich die Nummer; die neue steht unter
# /wp-json/wp/v2/media?search=TagesnewsLogo
WP_BILD = 82099
# Dasselbe Bild im Kopf der Tagesliste. Aus der Mediathek geladen und nicht
# angehaengt: Ein eingebettetes Bild macht die Nachricht schwer und faellt
# bei manchen Programmen in den Anhang statt in den Text.
BILD_URL = ("https://www.monitor-versorgungsforschung.de/wp-content/"
            "uploads/2026/08/TagesnewsLogo.png")
WP_KATEGORIE = 1000            # "News" - am 19.08.2026 nachgesehen
UEBERSICHT = "https://knowledge-hubs.m-vf.de/"


def auszug(anzahl: int) -> str:
    """Der feste Satz mit der Zahl des Tages - kurz genug fuer Yoast."""
    return WP_AUSZUG.format(n=anzahl,
                            wort="Studie" if anzahl == 1 else "Studien")


def textauszug(anzahl: int, vorspann: str) -> str:
    """Was ins WordPress-Feld 'Textauszug' gehoert: fester Satz + Vorspann.

    Der Vorspann stand bis zum 20.08.2026 als erster Absatz im Haupttext.
    Seither traegt ihn der Textauszug, und der Haupttext beginnt bei den
    Beispielen - so steht die Einordnung dort, wo WordPress sie in Listen und
    Teasern ausspielt, statt doppelt im Fliesstext.

    Fuer die Meta-Beschreibung bleibt es beim kurzen auszug(): Yoast schneidet
    bei rund 155 Zeichen ab, und beides zusammen ist deutlich laenger.
    """
    return f"{auszug(anzahl)}. {vorspann}".strip()
UTM = "?utm_source=mvf-news&utm_medium=referral&utm_campaign=tagesnews"

# Die Gruppe wird zur Laufzeit ueber ihren sichtbaren Namen gesucht. Die
# Nummern aus dem Anmeldeformular (group[16144][65536]) sind andere als die
# Kennungen der Schnittstelle - wer sie einsetzt, bekommt HTTP 500.
MC_GRUPPE_NAME = "Redaktion Tagesliste"
MC_LISTE_KENNUNG = "1c8fc10ec7"
MC_ABSENDER = "Monitor Versorgungsforschung"
MC_ANTWORT = "redaktion@m-vf.de"

MODELL = os.environ.get("MODEL", "claude-opus-5")

# Dieser Prompt steht bewusst MIT Umlauten - anders als die Kommentare im
# uebrigen Skript. Solange er in ASCII-Ersatzschreibung verfasst war, hat das
# Modell die Orthografie seiner Anweisung uebernommen: die Meldung vom
# 20.08.2026 stand live mit "ueber", "Pflegekraeften", "Kosteneffektivitaet"
# und dem gar nicht mehr gueltigen "Eintreaege" - mitten zwischen den korrekt
# geschriebenen Studientiteln aus studien.json. Die Zeile ganz unten sagt es
# noch einmal ausdruecklich, weil das Modell hier freien Text schreibt.
SYSTEM = (
    "Du schreibst kurze Meldungen für die Nachrichtenseite von Monitor "
    "Versorgungsforschung, einem Fachmagazin für Versorgungsforschung. "
    "Deine Leserschaft arbeitet im deutschen Gesundheitswesen: Kliniken, "
    "Praxen, Kostenträger, Selbstverwaltung, Politik. Sie ist fachkundig und "
    "hat wenig Zeit. Schreibe knapp, konkret und ohne Werbesprache. Siezen. "
    "Keine Ausrufezeichen, keine Superlative, keine leeren Wendungen wie "
    "'spannende Einblicke' oder 'wertvolle Erkenntnisse'. "
    "Schreibe durchgehend korrekte deutsche Rechtschreibung mit Umlauten "
    "(ä, ö, ü, ß) - niemals die Ersatzschreibung ae, oe, ue, ss."
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["titel", "vorspann", "meta_beschreibung", "zwischentitel",
                 "beispiele", "verwandte_suche", "schluss"],
    "properties": {
        "titel": {"type": "string"},
        "vorspann": {"type": "string"},
        # Was in der Trefferliste von Google steht. Bis zum 26.08.2026 stand
        # dort bei JEDER Tagesnews derselbe Satz aus WP_AUSZUG, nur die Zahl
        # wechselte - fuer Suchmaschinen faktisch dieselbe Beschreibung auf
        # vielen Seiten. Jetzt schreibt das Modell sie taeglich neu.
        "meta_beschreibung": {"type": "string"},
        # Zwischenueberschrift ueber der Beispielliste. Der Beitrag hatte bis
        # zum 26.08.2026 gar keine Ueberschrift im Text - nur Listen und
        # Absaetze. Suchmaschinen lesen die Gliederung einer Seite an den
        # Ueberschriften ab; ohne sie ist ein Beitrag eine flache Textwand.
        "zwischentitel": {"type": "string"},
        # Je Beispiel die PMID der gemeinten Studie - daraus baut das Skript
        # den Verweis. Das Modell nennt nie selbst eine Adresse.
        "beispiele": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pmid", "satz"],
                "properties": {
                    "pmid": {"type": "string"},
                    "satz": {"type": "string"},
                },
            },
        },
        # Ein bis zwei Suchbegriffe fuer das MVF-Archiv; die Adressen holt
        # verwandtes.py aus der WordPress-Suche. Dieselbe Regel wie bei den
        # Studienverweisen: Das Modell nennt nie selbst eine Adresse.
        "verwandte_suche": {"type": "array", "items": {"type": "string"}},
        "schluss": {"type": "string"},
    },
}


# ------------------------------------------------------------------- Daten
def studien_von_heute() -> tuple[list[dict], str]:
    """Die Neuzugaenge des heutigen Tages - Grundlage der Tagesliste."""
    pfad = pathlib.Path("studien.json")
    if not pfad.exists():
        raise SystemExit("studien.json fehlt - erst scripts/studien_sammeln.py laufen lassen.")
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    heute = dt.date.today().isoformat()
    return [e for e in daten.get("studien", []) if e.get("aufgenommen") == heute], heute


def studien_fuer_meldung() -> list[dict]:
    """Was in Meldung und Tagesliste gehoert - montags samt Wochenende.

    Die Newsseite bekommt werktags Zuwachs, die Hubs werden aber taeglich
    aktualisiert. Ohne diesen Rueckgriff fielen die Studien von Samstag und
    Sonntag heraus.

    **Seit dem 24.08.2026 gilt das auch fuer die Tagesliste an die Redaktion.**
    Vorher lief sie taeglich und blieb bei einem Tag - mit der Folge, dass am
    24.08. eine Mail ueber 11 Studien neben einem Beitragsentwurf ueber 44
    stand. Zwei Zahlen fuer denselben Lauf, die beide stimmten und sich
    trotzdem widersprachen. Beide Wege zaehlen jetzt dasselbe.
    """
    daten = json.loads(pathlib.Path("studien.json").read_text(encoding="utf-8"))
    tag = dt.date.today()
    tage = {tag.isoformat()}
    if tag.weekday() == 0:
        tage |= {(tag - dt.timedelta(days=n)).isoformat() for n in (1, 2)}
    return [e for e in daten.get("studien", []) if e.get("aufgenommen") in tage]


def hub_zahl() -> int:
    """Wie viele Hubs die Reihe hat - gezaehlt, nicht ausgeschrieben.

    Stand bis zum 20.08.2026 als Wort "acht" an zwei Stellen im Text: im
    Auftrag ans Modell und im Schlusslink der Meldung. Beim neunten Hub
    (gender.m-vf.de) waren beide falsch, ohne dass etwas kaputtging - genau
    die Sorte Fehler, die live steht, bis sie jemandem auffaellt. Gezaehlt
    wird jetzt in studien.json, das studien_sammeln.py aus PORTALE schreibt.
    """
    daten = json.loads(pathlib.Path("studien.json").read_text(encoding="utf-8"))
    return len(daten.get("hubs", []))


def wortzahl(n: int) -> str:
    """Kleine Zahlen ausgeschrieben - so liest sich die Meldung wie Text.

    Die Werte stehen MIT Umlaut: Sie landen im Fliesstext der Meldung und im
    Auftrag ans Modell, nicht im Kommentar. Fuer die Ersatzschreibung gilt
    hier dasselbe wie fuer den Prompt weiter oben.
    """
    worte = {7: "sieben", 8: "acht", 9: "neun", 10: "zehn", 11: "elf", 12: "zwölf"}
    return worte.get(n, str(n))


def nach_hub(studien: list[dict]) -> dict[str, list[dict]]:
    raus: dict[str, list[dict]] = {}
    for e in studien:
        raus.setdefault(e["hub"], []).append(e)
    return raus


def hub_adresse(e: dict) -> str:
    return f"https://{e['domain']}/{UTM}"


def escape(t: str) -> str:
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ------------------------------------------------------------------- Text
def schreibe_news(studien: list[dict]) -> dict:
    import anthropic

    # Das Geheimnis heisst hier KNOWLEDGEHUBS, nicht ANTHROPIC_API_KEY - bewusst
    # ohne Rueckfallweg, damit ein falscher Name sofort auffaellt statt still
    # den Schluessel eines anderen Portals zu greifen.
    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt - keine Meldung geschrieben.")

    gruppen = nach_hub(studien)
    material = []
    for hub, liste in gruppen.items():
        material.append(f"\n### {hub} ({len(liste)} Studien)")
        for e in liste:
            material.append(
                f"- PMID {e['pmid']} | {e.get('journal','')} {e.get('year','')} | "
                f"{e.get('title','')} | Ergebnis: {e.get('result','')}")

    auftrag = (
        f"Heute sind in den {wortzahl(hub_zahl())} Knowledge-Hubs "
        f"{len(studien)} neue Studien "
        f"aufgenommen worden, verteilt auf {len(gruppen)} Hubs.\n"
        f"{chr(10).join(material)}\n\n"
        "Schreibe daraus eine kurze Meldung:\n"
        "- titel: höchstens 65 Zeichen. **Die Themen stehen vorn, die Zahl "
        "dahinter**, getrennt durch einen Doppelpunkt - also 'Pflegepersonal, "
        "Klimafolgen und KI-Diagnostik: 23 neue Studien' und nicht '23 neue "
        "Studien in den Knowledge-Hubs aufgenommen'. Zwei bis drei Themen "
        "genügen, die restlichen stehen ohnehin im Text. Grund: Nach 'neue "
        "Studien in den Knowledge-Hubs' sucht niemand; nach den Fachthemen "
        "schon. Passt es nicht in 65 Zeichen, lass ein Thema weg, nicht die "
        "Zahl.\n"
        "- meta_beschreibung: EIN Satz, 120 bis 155 Zeichen, für die "
        "Trefferliste von Google. Nennt die konkreten Themen des Tages und "
        "eines der Ergebnisse - nicht die Gattung. Jeden Tag ein anderer Satz: "
        "Eine Beschreibung, die auf hundert Seiten gleich lautet, ist für "
        "Suchmaschinen wertlos. Höchstens 155 Zeichen, sonst wird "
        "abgeschnitten.\n"
        "- vorspann: zwei bis drei Sätze. Nennt die Zahl der Studien und der "
        "Hubs und sagt, was die Leserschaft davon hat.\n"
        "- zwischentitel: eine Zeile über der Beispielliste, drei bis sieben "
        "Wörter, die das inhaltliche Thema des Tages benennen - nicht "
        "'Beispiele' oder 'Die Studien', sondern woraus die Auswahl besteht: "
        "'Pflegepersonal, Klimafolgen und KI-Diagnostik'. Suchmaschinen lesen "
        "an den Zwischenüberschriften ab, wovon eine Seite handelt; diese hier "
        "ist die einzige, die du schreibst.\n"
        "- beispiele: DREI bis VIER Studien, die für die Leserschaft am "
        "interessantesten sind. Je Beispiel die PMID und EIN Satz, der das "
        "Ergebnis nennt - konkret, mit Zahl, wenn eine da ist. Wähle aus "
        "verschiedenen Hubs.\n"
        "- verwandte_suche: ein bis zwei Suchbegriffe, mit denen sich im "
        "MVF-Archiv frühere Beiträge zu den heutigen Themen finden lassen. Je "
        "ein bis zwei Wörter, so wie ein Fachredakteur suchen würde: "
        "'Pflegepersonaluntergrenzen', 'Hitzewelle', 'Klinikreform'. Nimm die "
        "beiden Themen, die heute am stärksten vertreten sind - nicht "
        "'Versorgungsforschung' oder 'Studien', das ist zu breit und findet "
        "alles.\n"
        "- schluss: ein Satz, der auf die Hubs verweist. Keine Aufforderung "
        "im Werbeton.\n"
        "Verwende keine Adressen und keine Links - die setzt die Redaktion."
    )

    antwort = anthropic.Anthropic(api_key=schluessel).messages.create(
        model=MODELL,
        max_tokens=4000,
        system=SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": auftrag}],
    )
    text = next(b.text for b in antwort.content if b.type == "text")
    news = json.loads(text)
    news["titel"] = titel_kuerzen(news.get("titel", ""), schluessel)
    return news


# Was Google in der Trefferliste noch ganz anzeigt. Darueber wird abgeschnitten,
# und zwar mitten im Wort. Der Prompt nennt die Grenze bereits - eingehalten
# wurde sie trotzdem nicht: Am 26.08.2026 waren von 20 gepruefteten News zwei
# 110 und 127 Zeichen lang. Eine Bitte im Prompt ist keine Pruefung.
TITEL_MAX = 65


def titel_kuerzen(titel: str, schluessel: str) -> str:
    """Einen zu langen Titel EINMAL neu anfragen - sonst bleibt er, wie er ist.

    Bewusst nur ein zweiter Versuch und kein Abbruch: Ein zu langer Titel ist
    ein Schoenheitsfehler, kein Grund, die Meldung des Tages fallenzulassen.
    Bleibt er auch danach zu lang, geht er mit und die Redaktion sieht den
    Hinweis im Lauf-Protokoll.

    Maschinelles Abschneiden waere die schlechtere Loesung - es trifft die
    Wortmitte und wirft gerade die Themen weg, die hinten stehen.
    """
    titel = (titel or "").strip()
    if len(titel) <= TITEL_MAX:
        return titel
    print(f"  Titel ist {len(titel)} Zeichen lang (erlaubt {TITEL_MAX}) - "
          f"wird neu angefragt.")
    import anthropic
    try:
        antwort = anthropic.Anthropic(api_key=schluessel).messages.create(
            model=MODELL, max_tokens=300, system=SYSTEM,
            messages=[{"role": "user", "content": (
                f"Kürze diese Überschrift auf höchstens {TITEL_MAX} Zeichen, "
                f"ohne ihren Sinn zu ändern. Die Themen stehen vorn, die Zahl "
                f"dahinter. Lieber ein Thema weglassen als die Zahl. Antworte "
                f"NUR mit der gekürzten Überschrift, ohne Anführungszeichen:\n\n"
                f"{titel}")}])
        neu = next(b.text for b in antwort.content if b.type == "text").strip()
        neu = neu.strip('"').strip()
    except Exception as fehler:
        print(f"  Kürzen nicht möglich ({fehler}) - Titel bleibt lang.")
        return titel
    if neu and len(neu) <= TITEL_MAX:
        print(f"  Gekürzt auf {len(neu)} Zeichen: {neu}")
        return neu
    print(f"  Auch der zweite Versuch war zu lang ({len(neu)}) - Titel bleibt.")
    return titel


def baue_html(news: dict, studien: list[dict]) -> str:
    """Die Meldung als HTML. Jede Adresse stammt aus der Sammeldatei."""
    nach_pmid = {e["pmid"]: e for e in studien}
    gruppen = nach_hub(studien)

    # Kein Vorspann hier: der steht im Textauszug (siehe textauszug()). Die
    # Meldung faengt mit den Beispielen an.
    #
    # Ueberschriften seit dem 26.08.2026. Bis dahin bestand der ganze Beitrag
    # aus zwei Listen und drei Absaetzen - keine einzige Ueberschrift zwischen
    # dem Titel und dem Seitenende. Suchmaschinen lesen die Gliederung einer
    # Seite an den Ueberschriften ab; ohne sie ist der Beitrag eine flache
    # Textwand, aus der sich kein Thema herauslesen laesst.
    #
    # **h4, nicht h2** - das ist die Hausform: Die Pressemeldungen auf m-vf.de
    # setzen ihre Zwischentitel ebenfalls als h4, und ein Beitrag, der aus der
    # Reihe faellt, sieht im Theme falsch aus. Semantisch waere h2 sauberer
    # (h1 ist der Beitragstitel, h4 ueberspringt zwei Ebenen); praktisch
    # wiegt die einheitliche Darstellung schwerer, und Suchmaschinen werten
    # laengst den Text der Ueberschrift, nicht ihre Nummer.
    teile = []
    if news.get("zwischentitel"):
        teile.append(f"<h4>{escape(news['zwischentitel'])}</h4>")
    teile.append("<ul>")
    for b in news.get("beispiele", []):
        e = nach_pmid.get(b.get("pmid", ""))
        if not e:
            continue                    # erfundene PMID - Beispiel faellt weg
        teile.append(
            f'<li>{escape(b["satz"])} '
            f'<em>({escape(e.get("journal",""))} {escape(e.get("year",""))})</em> — '
            f'<a href="{escape(hub_adresse(e))}" target="_blank" rel="noopener">'
            f'Knowledge-Hub {escape(e["hub"])}</a></li>')
    teile.append("</ul>")

    teile.append(f"<p>{escape(news['schluss'])}</p>")

    # War bis zum 26.08.2026 ein fett gesetzter Absatz. Fett sieht aus wie eine
    # Ueberschrift, ist aber keine - fuer Suchmaschinen und Screenreader bleibt
    # es ein Absatz. Dieselben Woerter als h4 kosten nichts und gliedern.
    teile.append("<h4>Die Hubs im Einzelnen</h4><ul>")
    for hub, liste in gruppen.items():
        e = liste[0]
        anzahl = len(liste)
        wort = "neue Studie" if anzahl == 1 else "neue Studien"
        teile.append(
            f'<li><a href="{escape(hub_adresse(e))}" target="_blank" rel="noopener">'
            f'{escape(hub)}</a> — {anzahl} {wort}</li>')
    teile.append("</ul>")

    teile.append(
        f'<p><a href="{escape(UEBERSICHT + UTM)}" target="_blank" rel="noopener">'
        f"Alle {wortzahl(hub_zahl())} Knowledge-Hubs im Überblick</a> — "
        "kostenfrei, ohne Anmeldung, "
        "mit täglichem Studien-Newsletter je Hub.</p>")

    # Verweise ins eigene Archiv, ganz am Schluss. Bis zum 26.08.2026 fuehrte
    # aus dieser Meldung kein einziger Link auf einen anderen MVF-Beitrag -
    # nur hinaus in die Hubs. Fuer Suchmaschinen war sie damit eine Sackgasse.
    block = verwandtes.html_block(
        verwandtes.finde(news.get("verwandte_suche") or []))
    if block:
        teile.append(block)
    return "\n".join(teile)


# -------------------------------------------------------------- WordPress
def wordpress_entwurf(titel: str, html: str, anzahl: int, vorspann: str,
                      trocken: bool, meta: str = "") -> None:
    nutzer = os.environ.get("WPUSER", "").strip()
    passwort = os.environ.get("WPPASSWORT", "").strip()
    if not (nutzer and passwort):
        print("WPUSER oder WPPASSWORT fehlt - kein Entwurf angelegt.")
        return
    if trocken:
        print(f"[trocken] Entwurf waere angelegt: {titel}")
        return

    koerper = json.dumps({
        "title": titel,
        "content": html,
        "status": "draft",              # NIE veroeffentlichen - das macht die Redaktion
        "categories": [WP_KATEGORIE],
        "excerpt": textauszug(anzahl, vorspann),
        "featured_media": WP_BILD,
    }).encode("utf-8")
    kopf = base64.b64encode(f"{nutzer}:{passwort}".encode()).decode()
    req = urllib.request.Request(
        f"{WP}/posts", data=koerper, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {kopf}",
                 # Ohne eigene Kennung sieht die Anfrage aus wie ein Skript von
                 # der Stange; Schutz-Plugins antworten darauf gern mit 403.
                 "User-Agent": "MVF-Knowledge-Hubs/1.0 (+https://knowledge-hubs.m-vf.de)",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        # Der Wortlaut aus WordPress sagt, woran es lag - ohne ihn raet man nur.
        text = e.read().decode("utf-8", "replace")[:600]
        print(f"WordPress lehnt ab: HTTP {e.code} {e.reason}")
        print(f"  Antwort: {text}")
        raise
    print(f"WordPress-Entwurf angelegt: {d.get('id')} — {d.get('link','')}")
    print(f"  Bearbeiten: https://www.monitor-versorgungsforschung.de/wp-admin/"
          f"post.php?post={d.get('id')}&action=edit")
    yoast_beschreibung(d.get("id"), kopf, meta)


def wordpress_nachtragen(kennung: str, anzahl: int) -> int:
    """Bild und Meta-Beschreibung an einem Beitrag nachziehen, der schon steht.

    Den Textauszug ruehrt das nur an, wenn er leer ist. Seit dem 20.08.2026
    traegt er den Vorspann der Meldung (siehe textauszug()), und den kann
    dieser Aufruf nicht kennen - er bekommt nur die Zahl des Tages. Ihn mit
    dem kurzen Satz zu ueberschreiben, wuerde die Einordnung loeschen.
    """
    nutzer = os.environ.get("WPUSER", "").strip()
    passwort = os.environ.get("WPPASSWORT", "").strip()
    if not (nutzer and passwort):
        print("WPUSER oder WPPASSWORT fehlt.")
        return 1
    kopf = base64.b64encode(f"{nutzer}:{passwort}".encode()).decode()

    felder = {"featured_media": WP_BILD}
    if not vorhandener_auszug(kennung, kopf):
        felder["excerpt"] = auszug(anzahl)
        print("Textauszug war leer - der kurze Satz wird eingetragen.")
    else:
        print("Textauszug steht bereits - bleibt unveraendert.")

    req = urllib.request.Request(
        f"{WP}/posts/{kennung}", method="POST",
        data=json.dumps(felder).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {kopf}",
                 "User-Agent": "MVF-Knowledge-Hubs/1.0 (+https://knowledge-hubs.m-vf.de)",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            json.load(r)
    except urllib.error.HTTPError as e:
        print(f"Nichts nachgetragen: HTTP {e.code}")
        print("  Antwort: " + e.read().decode("utf-8", "replace")[:400])
        return 1
    print(f"Beitragsbild an Beitrag {kennung} gesetzt.")
    yoast_beschreibung(kennung, kopf, auszug(anzahl))
    return 0


def vorhandener_auszug(kennung: str, kopf: str) -> str:
    """Der Textauszug, wie er gerade am Beitrag steht - leer heisst leer.

    Faellt die Abfrage aus, gibt es absichtlich einen nicht-leeren Wert
    zurueck: Im Zweifel lieber nichts ueberschreiben.
    """
    req = urllib.request.Request(
        f"{WP}/posts/{kennung}?context=edit&_fields=excerpt", method="GET",
        headers={"Authorization": f"Basic {kopf}",
                 "User-Agent": "MVF-Knowledge-Hubs/1.0 (+https://knowledge-hubs.m-vf.de)",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  Beitrag nicht gelesen (HTTP {e.code}) - Textauszug bleibt, wie er ist.")
        return "unbekannt"
    return ((d.get("excerpt") or {}).get("raw")
            or (d.get("excerpt") or {}).get("rendered") or "").strip()


def yoast_beschreibung(kennung, kopf: str, text: str) -> None:
    """Meta-Beschreibung nachtragen - ohne den Entwurf zu gefaehrden.

    Yoast gibt sein Feld nicht in jeder Fassung ueber die Schnittstelle frei.
    Deshalb steht das hier als eigener Schritt: Schlaegt er fehl, bleibt der
    Entwurf trotzdem stehen. Yoast greift dann auf den Textauszug zurueck -
    seit dem 20.08.2026 traegt der den Vorspann mit und ist laenger als die
    155 Zeichen, die in der Trefferliste stehen. Yoast kuerzt selbst; der
    Anfang ist derselbe feste Satz, also bleibt der Rueckfall brauchbar.
    """
    if not (kennung and text.strip()):
        return
    req = urllib.request.Request(
        f"{WP}/posts/{kennung}", method="POST",
        data=json.dumps({"meta": {"_yoast_wpseo_metadesc": text.strip()}}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {kopf}",
                 "User-Agent": "MVF-Knowledge-Hubs/1.0 (+https://knowledge-hubs.m-vf.de)",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  Meta-Beschreibung nicht gesetzt (HTTP {e.code}) - Yoast nimmt "
              f"den Textauszug.")
        return
    steht = (d.get("meta") or {}).get("_yoast_wpseo_metadesc")
    print("  Meta-Beschreibung gesetzt." if steht else
          "  Meta-Beschreibung von Yoast nicht uebernommen - er nimmt den Textauszug.")


# --------------------------------------------------------------- Mailchimp
class Mailchimp:
    def __init__(self, schluessel: str):
        self.dc = schluessel.rsplit("-", 1)[1]
        self.basis = f"https://{self.dc}.api.mailchimp.com/3.0"
        self.kopf = {
            "Content-Type": "application/json",
            "Authorization": "Basic " + base64.b64encode(
                f"any:{schluessel}".encode()).decode(),
        }

    def ruf(self, pfad: str, daten: dict | None = None, methode: str = "GET") -> dict:
        req = urllib.request.Request(
            self.basis + pfad, headers=self.kopf, method=methode,
            data=json.dumps(daten).encode() if daten is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                roh = r.read()
        except urllib.error.HTTPError as e:
            # Mailchimp schreibt in den Rumpf, welches Feld nicht stimmt. Ohne
            # ihn steht im Protokoll nur eine nackte Nummer.
            print(f"Mailchimp {methode} {pfad}: HTTP {e.code}")
            print("  Antwort: " + e.read().decode("utf-8", "replace")[:600])
            raise
        return json.loads(roh) if roh else {}

    def gruppe(self, name: str) -> tuple[str, str]:
        """Kennung von Kategorie und Gruppe zum sichtbaren Namen."""
        kats = self.ruf(f"/lists/{MC_LISTE_KENNUNG}/interest-categories?count=60")
        for k in kats.get("categories", []):
            ints = self.ruf(f"/lists/{MC_LISTE_KENNUNG}/interest-categories/"
                            f"{k['id']}/interests?count=60")
            for i in ints.get("interests", []):
                if i.get("name", "").strip().lower() == name.strip().lower():
                    return k["id"], i["id"]
        raise SystemExit(f"Gruppe '{name}' in Mailchimp nicht gefunden.")


# Wer die Tagesliste bekommen soll. Nur zur Kontrolle - eingetragen wird
# niemand vom Skript, das bleibt Sache der Redaktion.
MC_ERWARTET = ["stegmaier@m-vf.de", "heiser@m-vf.de"]


def mailchimp_pruefen() -> int:
    """Sieht nach, wer in der Gruppe steht - schreibt nichts."""
    schluessel = os.environ.get("KNOWLEDGEHUBSMC", "").strip()
    if not schluessel:
        print("KNOWLEDGEHUBSMC fehlt.")
        return 1
    mc = Mailchimp(schluessel)
    kat, interesse = mc.gruppe(MC_GRUPPE_NAME)
    print(f"Gruppe '{MC_GRUPPE_NAME}': Kategorie {kat}, Gruppe {interesse}")

    d = mc.ruf(f"/lists/{MC_LISTE_KENNUNG}/members"
               f"?interest_category_id={kat}&interest_ids={interesse}"
               f"&interest_match=all&count=200&fields=total_items,"
               f"members.email_address,members.status")
    mitglieder = d.get("members", [])
    print(f"In der Gruppe: {d.get('total_items', len(mitglieder))}")
    for m in mitglieder[:20]:
        print(f"  {m['email_address']:<40} {m['status']}")

    print()
    print("Die beiden vorgesehenen Adressen:")
    for adresse in MC_ERWARTET:
        kennung = hashlib.md5(adresse.lower().encode()).hexdigest()
        try:
            m = mc.ruf(f"/lists/{MC_LISTE_KENNUNG}/members/{kennung}")
        except urllib.error.HTTPError:
            print(f"  {adresse:<40} steht nicht in der Liste")
            continue
        drin = bool(m.get("interests", {}).get(interesse))
        print(f"  {adresse:<40} {m.get('status')}, "
              f"Gruppe {'ja' if drin else 'NEIN'}")
    return 0


def mailchimp_liste(studien: list[dict], heute: str, trocken: bool) -> None:
    schluessel = os.environ.get("KNOWLEDGEHUBSMC", "").strip()
    if not schluessel:
        print("KNOWLEDGEHUBSMC fehlt - keine Ausgabe an die Redaktion.")
        return

    gruppen = nach_hub(studien)
    datum = dt.date.fromisoformat(heute).strftime("%d.%m.%Y")
    # Montags stecken Samstag und Sonntag mit drin. Dann nennt die Ausgabe den
    # Zeitraum statt eines Tages - sonst steht "Neuzugaenge 24.08." ueber einer
    # Liste, die zu zwei Dritteln vom Wochenende stammt.
    tage = sorted({e.get("aufgenommen", "") for e in studien if e.get("aufgenommen")})
    spanne = datum
    hinweis = ""
    if len(tage) > 1:
        spanne = f"{dt.date.fromisoformat(tage[0]).strftime('%d.%m.')}–{datum}"
        hinweis = ('<p style="margin:0 0 14px;font:13px/1.5 Arial,sans-serif;color:#777;">'
                   'Ausgabe vom Montag: mit den Studien vom Wochenende.</p>')
    zeilen = [f"<p>{len(studien)} neue Studien in {len(gruppen)} Hubs.</p>{hinweis}"]
    for hub, liste in gruppen.items():
        zeilen.append(f'<h3 style="margin:22px 0 6px;font:700 16px/1.3 Arial,sans-serif;">'
                      f'{escape(hub)} <span style="font-weight:400;color:#777;">'
                      f'({len(liste)})</span></h3><ul style="margin:0;padding-left:20px;">')
        for e in liste:
            zeilen.append(
                f'<li style="margin:0 0 7px;font:14px/1.5 Arial,sans-serif;">'
                f'{escape(e.get("title",""))}<br>'
                f'<span style="color:#777;font-size:12.5px;">'
                f'{escape(e.get("journal",""))} {escape(e.get("year",""))} · '
                f'<a href="https://pubmed.ncbi.nlm.nih.gov/{escape(e["pmid"])}/">'
                f'PMID {escape(e["pmid"])}</a></span></li>')
        zeilen.append("</ul>")
    html = ('<div style="max-width:640px;margin:0 auto;padding:20px;">'
            f'<img src="{BILD_URL}" width="600" alt="Knowledge-Hubs von Monitor '
            f'Versorgungsforschung" style="display:block;width:100%;max-width:600px;'
            f'height:auto;margin:0 0 22px;">'
            f'<h2 style="font:700 20px/1.3 Arial,sans-serif;">Neuzugänge {spanne}</h2>'
            + "".join(zeilen) + "</div>")

    if trocken:
        print(f"[trocken] Mailchimp-Ausgabe waere versendet: "
              f"{len(studien)} Studien, {len(html)} Zeichen HTML.")
        return

    mc = Mailchimp(schluessel)
    kat, interesse = mc.gruppe(MC_GRUPPE_NAME)
    print(f"Empfaenger: Gruppe '{MC_GRUPPE_NAME}' ({interesse}).")
    kampagne = mc.ruf("/campaigns", {
        "type": "regular",
        "recipients": {
            "list_id": MC_LISTE_KENNUNG,
            "segment_opts": {"match": "all", "conditions": [{
                "condition_type": "Interests", "field": f"interests-{kat}",
                "op": "interestcontains", "value": [interesse]}]},
        },
        "settings": {
            "subject_line": f"Neuzugänge {spanne} — {len(studien)} Studien aus {len(gruppen)} Hubs",
            "title": f"Redaktion Tagesliste {datum}",
            "from_name": MC_ABSENDER, "reply_to": MC_ANTWORT,
        },
    }, "POST")
    kid = kampagne["id"]
    mc.ruf(f"/campaigns/{kid}/content", {"html": html}, "PUT")
    mc.ruf(f"/campaigns/{kid}/actions/send", {}, "POST")
    print(f"Tagesliste an '{MC_GRUPPE_NAME}' versendet ({len(studien)} Studien).")


def main() -> int:
    p = argparse.ArgumentParser(description="Tagesnews und Redaktionsliste")
    p.add_argument("--nur-wordpress", action="store_true")
    p.add_argument("--nur-mail", action="store_true")
    p.add_argument("--trocken", action="store_true")
    p.add_argument("--pruefen", action="store_true",
                   help="nur nachsehen, wer die Tagesliste bekaeme")
    p.add_argument("--nachtragen", metavar="ID",
                   help="Beitragsbild und Meta-Beschreibung an einem "
                        "bestehenden Beitrag nachtragen; den Textauszug nur, "
                        "wenn er leer ist")
    a = p.parse_args()

    if a.pruefen:
        return mailchimp_pruefen()
    studien, heute = studien_von_heute()
    if a.nachtragen:
        return wordpress_nachtragen(a.nachtragen, len(studien))
    # Montags kann der Tag selbst leer sein und das Wochenende trotzdem etwas
    # gebracht haben. Dann gibt es zwar keine Tagesliste, aber eine Meldung.
    montag_nachzug = dt.date.today().weekday() == 0 and bool(studien_fuer_meldung())
    if not studien and not montag_nachzug:
        print(f"Keine neuen Studien am {heute} - nichts zu melden.")
        return 0
    print(f"{len(studien)} Studien aus {len(nach_hub(studien))} Hubs.")

    # Am Wochenende entsteht weder Meldung noch Tagesliste. Bis zum 24.08.2026
    # ging die Liste auch samstags und sonntags heraus - sie galt als
    # Arbeitsmittel der Redaktion, nicht als Newsletter. Nur arbeitet an diesen
    # Tagen niemand damit, und montags kam alles ohnehin ein zweites Mal in der
    # Meldung. Jetzt laeuft die Reihe durchgehend werktags, wie die Newsletter
    # der Portale auch.
    wochenende = dt.date.today().weekday() >= 5
    if wochenende:
        print("Wochenende - keine Meldung, keine Tagesliste. "
              "Die Studien laufen am Montag mit.")

    if not a.nur_mail and not wochenende:
        fuer_meldung = studien_fuer_meldung()
        news = schreibe_news(fuer_meldung)
        html = baue_html(news, fuer_meldung)
        studien_der_meldung = fuer_meldung
        print()
        print("=" * 72)
        print("TITEL: " + news["titel"])
        print("=" * 72)
        if a.trocken:
            # Im Trockenlauf den ganzen Entwurf zeigen - sonst laesst sich
            # nicht beurteilen, ob die Meldung taugt. Die beiden WordPress-
            # Felder getrennt, weil sie getrennt gepflegt werden.
            print("TEXTAUSZUG:")
            print(textauszug(len(fuer_meldung), news["vorspann"]))
            print("-" * 72)
            print("HAUPTTEXT:")
            lesbar = html.replace("</li>", "\n").replace("</p>", "\n")
            lesbar = re.sub(r"<[^>]+>", "", lesbar)
            # Die Lesefassung soll lesbar sein - Entitaeten zurueckwandeln.
            import html as _html
            lesbar = _html.unescape(lesbar)
            print(re.sub(r"\n{3,}", "\n\n", lesbar).strip())
            print("-" * 72)
            print("HTML, wie es in WordPress landet:")
            print(html)
        else:
            print(news["vorspann"])
        print()
        wordpress_entwurf(news["titel"], html, len(studien_der_meldung),
                          news["vorspann"], a.trocken,
                          news.get("meta_beschreibung", ""))

    if not a.nur_wordpress and not wochenende:
        # Dieselbe Menge wie die Meldung: montags samt Wochenende. Sonst
        # nennen Mail und Beitrag am selben Morgen zwei verschiedene Zahlen.
        fuer_liste = studien_fuer_meldung()
        if fuer_liste:
            mailchimp_liste(fuer_liste, heute, a.trocken)
        else:
            print("Keine Neuzugaenge - keine Tagesliste an die Redaktion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
