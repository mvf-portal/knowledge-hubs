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
import pathlib
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
    # erzeugt aus portale.json von portale_pflegen.py - nicht von Hand aendern
    ("Versorgungsforschung", "mvf-portal/versorgungsforschung-portal"),
    ("Hitze, Klima & Gesundheit", "mvf-portal/klima-gesundheit-portal"),
    ("Digitalisierung, KI & Gesundheit", "mvf-portal/ki-gesundheit-portal"),
    ("Pflege & Langzeitversorgung", "mvf-portal/pflege-portal"),
    ("Gesundes Altern & Longevity", "mvf-portal/longevity-portal"),
    ("Gesundheitskompetenz", "mvf-portal/healthliteracy-portal"),
    ("Impfen & Impfprävention", "mvf-portal/impfen-portal"),
    ("Nicht übertragbare Krankheiten", "mvf-portal/ncd-portal"),
    ("Geschlechtersensible Medizin", "mvf-portal/gender-portal"),
    ("Adipositas", "mvf-portal/adipositas-portal"),
    ("Patientensicherheit", "mvf-portal/safety-portal"),
    ("Psychische Gesundheit", "mvf-portal/mental-portal"),
]
ROH = "https://raw.githubusercontent.com/{repo}/main/versand-status.json"
ROH_ARCHIV = "https://raw.githubusercontent.com/{repo}/main/studien-archiv.json"
# Der Ausschreibungsradar laeuft nicht in jedem Hub, sondern einmal zentral im
# Versorgungsforschungs-Portal und teilt sein Ergebnis nach Themengebieten auf.
# Deshalb genuegt hier eine Datei statt zwoelf.
ROH_RADAR = ("https://raw.githubusercontent.com/"
             "mvf-portal/versorgungsforschung-portal/main/ausschreibungen.json")
BERICHT_REPO = "mvf-portal/knowledge-hubs"
# Wem die Meldung zugewiesen wird - ohne das kommt sie nicht im Postfach an.
#
# Bis zum 30.08.2026 kam kein einziger Sammelbericht als E-Mail an, obwohl
# alles richtig eingestellt war: Das Repo wurde mit "All Activity" beobachtet,
# der E-Mail-Kanal fuer "Watching" war an, die Adresse bestaetigt, und
# Actions-Mails aus demselben Repo kamen an. Die Issues #10 bis #17 legt aber
# `github-actions[bot]` mit dem GITHUB_TOKEN des Workflows an, und fuer solche
# Bot-Aktivitaet verschickt GitHub keine Watching-Benachrichtigung.
#
# Zugewiesene benachrichtigt GitHub ueber den Kanal "Participating" - und der
# greift auch dann, wenn ein Bot zuweist. Das ist der Weg, der hier
# funktioniert; das Beobachten des Repos allein genuegt nicht.
BERICHT_ZUSTAENDIG = "mvf-portal"

# Samstag und Sonntag terminiert kein Portal - `WOCHENENDE_AUS` in deren
# mailchimp_entwurf.py bricht vor dem Entwurf ab und schreibt deshalb auch keine
# Statusdatei. Ohne diese Kenntnis meldete der Bericht dann neun Mal "keine
# Statusdatei" und las sich wie ein Ausfall, obwohl es die Absicht ist.
RUHETAGE = (5, 6)


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


def letzter_zugang(repo: str) -> str | None:
    """Der juengste Aufnahmetag im Archiv des Hubs - oder None.

    Zweite Quelle neben versand-status.json, und zwar mit Absicht: Der
    Versandstatus sagt, was hinausging, nicht ob ueberhaupt noch etwas
    nachkommt. Am 26.08.2026 meldete der Gesundheitskompetenz-Hub zwei Tage
    lang erfolgreiche Laeufe - und lieferte dabei null neue Studien, weil das
    Modell aus einem unveraenderten Pool jedes Mal dieselben Arbeiten waehlte
    und das Archiv sie als Doppel verwarf. Im Bericht stand nur "Status ist
    vom 24.08., nicht von heute", was nach einem ruhigen Tag aussieht. Diese
    Zeile macht daraus eine Zahl.
    """
    try:
        req = urllib.request.Request(ROH_ARCHIV.format(repo=repo),
                                     headers={"User-Agent": "mvf-versandbericht"})
        with urllib.request.urlopen(req, timeout=30) as r:
            eintraege = json.load(r)
    except Exception:  # noqa: BLE001 - eine fehlende Datei ist kein Grund abzubrechen
        return None
    tage = [e.get("aufgenommen") for e in eintraege if e.get("aufgenommen")]
    return max(tage) if tage else None


def radarbericht() -> str:
    """Was der Ausschreibungsradar heute gefunden hat - und was ihm fehlt.

    Der Radar schweigt von sich aus, wenn er nichts findet; bei eng gefassten
    Themengebieten ist das der Normalfall und steht so auf der Seite ("Derzeit
    gibt es keine von uns recherchierbaren Fördermaßnahmen in diesem
    Themenbereich."). Faellt aber eine
    Quelle aus - geaenderte Feed-Adresse, neues Seitenlayout bei der DFG,
    abgeschaltete Schnittstelle -, sieht ihr Schweigen von aussen genauso aus.
    `ausschreibungen.py` vergleicht deshalb jeden Lauf mit dem vorigen und legt
    seine Zweifel in `warnungen` ab. Hier stehen sie, und nur hier: Auf der
    Seite haetten sie nichts zu suchen.
    """
    try:
        req = urllib.request.Request(
            ROH_RADAR, headers={"User-Agent": "mvf-versandbericht",
                                "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=30) as r:
            daten = json.load(r)
    except Exception:  # noqa: BLE001 - fehlt die Datei, entfaellt der Abschnitt
        return ""
    quellen = daten.get("quellen") or {}
    gebiete = daten.get("themen") or []
    zahl = sum(len(g.get("ausschreibungen") or []) for g in gebiete)
    # Wie viele Gebiete heute leer ausgehen, ist die Zahl, an der ein zu eng
    # geratener Zuschnitt auffaellt - eine einzelne Null ist Normalfall, acht
    # Nullen sind es nicht.
    leer = [g.get("name", "?") for g in gebiete
            if not (g.get("ausschreibungen") or [])]
    kopf = (f"**Ausschreibungsradar** — Stand {daten.get('stand', '?')}, "
            f"{zahl} Zuordnung(en) über {len(gebiete)} Themengebiete")
    if quellen:
        kopf += " (" + ", ".join(f"{n}: {z}" for n, z in quellen.items()) + ")"
    zeilen = [kopf + "."]
    # Der Radar sucht montags und donnerstags. Ist sein Stand aelter als fuenf
    # Tage, ist mindestens ein Lauf ausgefallen - und das faellt sonst
    # niemandem auf, weil eine veraltete Liste genauso aussieht wie eine
    # aktuelle: Die Fristen rechnet die Seite im Browser nach, es verschwinden
    # also nur Eintraege, statt dass falsche erscheinen.
    try:
        stand = dt.datetime.strptime(daten.get("stand", ""), "%d.%m.%Y").date()
        alter = (dt.date.today() - stand).days
    except ValueError:
        alter = None
    if alter is not None and alter > 5:
        zeilen.append(f"- ⚠️ Der Radar-Stand ist {alter} Tage alt. Er sucht "
                      f"montags und donnerstags; mindestens ein Lauf ist "
                      f"ausgefallen. [Actions ansehen]"
                      f"(https://github.com/mvf-portal/"
                      f"versorgungsforschung-portal/actions)")
    if leer:
        zeilen.append(f"- Ohne Treffer: {', '.join(leer)}.")
    # Die Warnungen stehen bewusst als eigene Zeilen und nicht in Klammern
    # hinter der Zahl: Sie sind der Grund, warum es diesen Abschnitt gibt.
    for w in daten.get("warnungen") or []:
        zeilen.append(f"- ⚠️ {w}")
    return chr(10).join(zeilen)


def poolzeile(s: dict) -> str:
    """Was zwischen PubMed und Ausgabe verlorenging - als Zahl statt als Ahnung.

    Der Ausfall vom 26.08.2026 (zwei Tage lang null neue Studien im
    Gesundheitskompetenz-Hub) waere hier sofort sichtbar gewesen: Pool 51,
    gewaehlt 6, neu 0.
    """
    z = s.get("pool") or {}
    if not z:
        return ""
    return (f"  \n  <sub>Pool {z.get('pool', '?')} aus {z.get('geholt', '?')} Treffern "
            f"({z.get('bekannt', 0)} schon im Archiv) &middot; gewählt {z.get('gewaehlt', '?')} "
            f"&middot; neu {z.get('neu', '?')}</sub>")


def frische(repo: str, heute: str) -> str:
    """Warnt, wenn seit Tagen nichts Neues mehr ankommt."""
    letzter = letzter_zugang(repo)
    if not letzter:
        return ""
    try:
        alter = (dt.date.fromisoformat(heute) - dt.date.fromisoformat(letzter)).days
    except ValueError:
        return ""
    if alter <= 1:
        return ""
    zeichen = "⚠️" if alter >= 3 else "•"
    return (f"  \n  <sub>{zeichen} Letzter neuer Studienzugang: {letzter} "
            f"(vor {alter} Tagen). Bleibt das so, die Abfrage nachmessen: "
            f"`py machbarkeit.py themen/&lt;slug&gt;.json`</sub>")


def zeile(name: str, repo: str, s: dict | None, heute: str, ruhetag: bool = False) -> str:
    # Ein Portal, das am Wochenende doch etwas terminiert hat, wird normal
    # gemeldet - die Ruhetag-Auskunft gilt nur fuer die fehlende Statusdatei.
    if ruhetag and (s is None or s.get("datum") != heute):
        return f"- 🗓 **{name}** — planmäßig kein Versand."
    if s is None:
        return (f"- **{name}** — keine Statusdatei. Der Lauf ist entweder noch nicht "
                f"durch oder abgebrochen. [Actions ansehen](https://github.com/{repo}/actions)")
    if s.get("datum") != heute:
        return (f"- **{name}** — Status ist vom {s.get('datum')}, nicht von heute. "
                f"Der nächtliche Lauf hat nichts Neues gefunden." + frische(repo, heute))
    if s.get("stand") == "terminiert":
        uhr = ortszeit(s.get("termin_utc"))
        # Die Empfaengerzahl steht bewusst im Bericht: Sie ist die einzige
        # Zahl, an der ein verrutschtes Segment taeglich auffaellt.
        wer = ""
        if s.get("empfaenger"):
            wer = f" an {s['empfaenger']} Empfänger"
            if s.get("listengroesse"):
                wer += f" von {s['listengroesse']}"
        return (f"- ✅ **{name}** — {s['anzahl']} Studien, geht um {uhr}{wer} raus. "
                f"[Ansehen oder absagen]({s['kampagne']})  \n"
                f"  <sub>{s.get('betreff', '')}</sub>{_aussortiert(s)}"
                + poolzeile(s) + frische(repo, heute))
    gruende = "; ".join(s.get("beanstandungen", [])) or "unbekannt"
    return (f"- ⛔ **{name}** — **gestoppt**, nichts wird versendet. "
            f"[Entwurf ansehen]({s['kampagne']})  \n"
            f"  <sub>Grund: {gruende}</sub>{_aussortiert(s)}"
            + poolzeile(s) + frische(repo, heute))


def _aussortiert(s: dict) -> str:
    """Welche Studien die Vorpruefung des Torwaechters aus der Ausgabe nahm.

    Steht bewusst auch unter einer terminierten Ausgabe: Aussortieren ist der
    stille Fall - ohne diese Zeile faellt nicht auf, wenn es taeglich passiert.
    """
    weg = s.get("aussortiert") or []
    if not weg:
        return ""
    zeilen = "".join(f"  \n  <sub>↳ {x}</sub>" for x in weg)
    return f"  \n  <sub>**{len(weg)} Studie(n) aussortiert:**</sub>{zeilen}"


def tageszusammenfassung(heute: str) -> str:
    """Was heute in der ganzen Reihe erschienen ist - kurz, mit Verweis.

    Gedacht als Lesestueck fuer die Redaktion: Die Meldung geht als
    GitHub-Issue heraus und landet damit ohnehin im Postfach. Ein eigener
    Newsletter dafuer waere eine zweite Zustellung fuer dieselbe Sache.

    Grundlage ist die Sammeldatei von studien_sammeln.py. Fehlt sie, entfaellt
    der Abschnitt - der Bericht selbst haengt nicht daran.
    """
    pfad = pathlib.Path("studien.json")
    if not pfad.exists():
        return ""
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return ""
    heutige = [e for e in daten.get("studien", []) if e.get("aufgenommen") == heute]
    if not heutige:
        return ""

    zeilen = [f"<details><summary><b>Die {len(heutige)} Studien von heute</b> "
              f"— aus allen Hubs, zum Nachlesen</summary>", ""]
    letzter = None
    for e in heutige:
        if e.get("hub") != letzter:
            letzter = e.get("hub")
            zeilen.append(f"**{letzter}**")
        zeilen.append(f"- [{e.get('title','(ohne Titel)')}]"
                      f"(https://pubmed.ncbi.nlm.nih.gov/{e.get('pmid','')}/) — "
                      f"*{e.get('journal','')} {e.get('year','')}*")
    zeilen += ["", "</details>"]
    return chr(10).join(zeilen)


def doppelungen(gesammelt: dict[str, list[str]]) -> str:
    """Welche Studie erscheint heute in mehr als einem Hub?

    Die Statusdatei jedes Portals nennt die PMIDs seiner Ausgabe - der Vergleich
    kostet also keinen zusaetzlichen Abruf. Gemessen wurde am 19.08.2026: Von 113
    ausgelieferten Studien erschien genau eine in zwei Hubs. Die Ueberschneidung
    der Suchraeume liegt weit hoeher (5 bis 28 Prozent); dass davon so wenig
    ankommt, liegt an den Auswahlregeln. Diese Zeile prueft nach, ob das so
    bleibt - eine harte Sperre ueber die Schwesterarchive lohnt erst, wenn es
    nicht mehr stimmt.
    """
    wo: dict[str, list[str]] = {}
    for name, pmids in gesammelt.items():
        for p in pmids:
            wo.setdefault(p, []).append(name)
    mehrfach = {p: n for p, n in wo.items() if len(n) > 1}
    if not mehrfach:
        return "Keine Studie erscheint heute in mehr als einem Hub."
    zeilen = [f"**{len(mehrfach)} Studie(n) heute in mehreren Hubs:**"]
    for p, n in sorted(mehrfach.items()):
        zeilen.append(f"- PMID [{p}](https://pubmed.ncbi.nlm.nih.gov/{p}/) — "
                      + ", ".join(n))
    return chr(10).join(zeilen)


def main() -> int:
    trocken = "--trocken" in sys.argv
    heute = dt.date.today().isoformat()
    ruhetag = dt.date.fromisoformat(heute).weekday() in RUHETAGE
    zeilen, terminiert, gestoppt, offen, ruhend = [], 0, 0, 0, 0
    gesammelt: dict[str, list[str]] = {}
    for name, repo in PORTALE:
        s = hole(repo)
        zeilen.append(zeile(name, repo, s, heute, ruhetag))
        if s and s.get("datum") == heute and s.get("pmids"):
            gesammelt[name] = s["pmids"]
        if s is None or s.get("datum") != heute:
            if ruhetag:
                ruhend += 1
            else:
                offen += 1
        elif s.get("stand") == "terminiert":
            terminiert += 1
        else:
            gestoppt += 1

    # Am Ruhetag ohne jede Terminierung fuehrt "0 terminiert" in die Irre - dann
    # ist der Ruhetag die ganze Nachricht.
    if ruhetag and ruhend == len(PORTALE):
        teile = ["Wochenende, planmäßig kein Versand"]
        # Neun gleichlautende Zeilen wären nur Lärm: Zu veto'en gibt es nichts.
        zeilen = [f"Alle {len(PORTALE)} Hubs ruhen."]
    else:
        teile = [f"{terminiert} terminiert"]
        if gestoppt:
            teile.append(f"{gestoppt} gestoppt")
        if ruhend:
            teile.append(f"{ruhend} planmäßig ohne Versand")
        if offen:
            teile.append(f"{offen} ohne Meldung")
    titel = (f"Newsletter {dt.date.fromisoformat(heute).strftime('%d.%m.%Y')} — "
             + ", ".join(teile))

    if terminiert:
        kopf = [
            "Die terminierten Ausgaben gehen **automatisch** raus. Sie müssen nichts tun.",
            "",
            "Wollen Sie eine verhindern: Kampagnenlink öffnen und in Mailchimp auf "
            "*Unschedule* drücken — das geht bis zur letzten Minute vor dem Versand.",
        ]
    elif ruhetag:
        kopf = ["Wochenende: Es wird heute **nichts versendet**. Die Portale sind "
                "trotzdem aktualisiert; die Studien laufen am Montag im Newsletter mit."]
    else:
        kopf = ["Heute ist **keine** Ausgabe terminiert. Sie müssen nichts tun — "
                "es geht aber auch nichts raus."]

    rumpf = "\n".join([
        *kopf,
        "",
        *zeilen,
        "",
        doppelungen(gesammelt),
        "",
        radarbericht(),
        "",
        tageszusammenfassung(heute),
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
    befehl = ["gh", "issue", "create", "-R", BERICHT_REPO,
              "--title", titel, "--body", rumpf]
    if BERICHT_ZUSTAENDIG:
        befehl += ["--assignee", BERICHT_ZUSTAENDIG]
    ergebnis = subprocess.run(befehl)
    if ergebnis.returncode and BERICHT_ZUSTAENDIG:
        # Lieber eine Meldung ohne Zuweisung als gar keine: Ein unbekannter
        # oder nicht berechtigter Name darf den Bericht nicht verschlucken.
        print("Zuweisung an %s fehlgeschlagen - Issue ohne Assignee." % BERICHT_ZUSTAENDIG)
        subprocess.run(["gh", "issue", "create", "-R", BERICHT_REPO,
                        "--title", titel, "--body", rumpf], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
