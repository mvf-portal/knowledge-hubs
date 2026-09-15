#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Der monatliche Sponsorenbericht eines Hubs - eine Seite als PDF.

    py scripts/sponsorenbericht.py adipositas                 # Vormonat
    py scripts/sponsorenbericht.py adipositas --monat 2026-08
    py scripts/sponsorenbericht.py --alle --monat 2026-08     # jeder Hub, der einen hat

Was der Bericht beantwortet, ist die Frage, die ein Sponsor stellt: Wie oft
wurde mein Logo gezeigt, und wie lebendig ist das Angebot, an dem es haengt.

**Die Logo-Ausspielung wird nicht eigens gezaehlt - sie muss es auch nicht.**
Das Sponsorenfeld steht auf der Startseite; jeder Aufruf der Startseite ist
eine Ausspielung. Und im Newsletter wird eine Oeffnung ueber ein geladenes
Bild gemessen: Wer als Oeffnung zaehlt, hat die Bilder geladen und damit das
Logo gesehen. Zwei Zahlen, die es schon gibt, statt einer neuen Zaehlung.

Klicks auf das Logo zaehlt der Bericht bewusst **nicht**. Auf einer
Rechercheseite klickt kaum jemand auf ein Logo - eine solche Zahl waere
richtig und trotzdem irrefuehrend, weil sie neben den Ausspielungen wie ein
Misserfolg aussaehe. (Entscheidung Peter Stegmaier, 15.09.2026.)

Drei Quellen:

  1. `zaehler/bericht.php?...&monat=JJJJ-MM` auf dem MVF-Server - Aufrufe,
     Besucher, Suchen, Herkunft, Geraete, Suchbegriffe des Monats.
  2. Mailchimp - die Ausgaben des Hub-Newsletters in diesem Monat mit
     Zustellung und Oeffnungen.
  3. Die Sponsorenliste des Portals selbst, ueber `sponsoren.py` in
     hub-scripts - damit im Bericht derselbe Name und dieselbe Art steht wie
     auf der Seite. Zwei Listen waeren eine zu viel.

Geheimnisse in der Umgebung:
    ZAEHLERSCHLUESSEL   der Schluessel aus bericht.php
    MAILCHIMP_API_KEY   bzw. KNOWLEDGEHUBSMC

Gesetzt wird das PDF mit Edge (`--headless --print-to-pdf`), wie die Banner
auch - kein zusaetzlicher Baustein, und das Ergebnis sieht auf jedem Rechner
gleich aus.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BERLIN = ZoneInfo("Europe/Berlin")
KENNUNG = "MVF-Sponsorenbericht/1.0 (Redaktion Monitor Versorgungsforschung)"
ZAEHLER = "https://www.monitor-versorgungsforschung.de/zaehler/bericht.php"

HIER = pathlib.Path(__file__).resolve().parent
REPO = HIER.parent                       # knowledge-hubs
VORLAGE = REPO.parent / "portal-vorlage"
HUBSKRIPTE = REPO.parent / "hub-scripts"
AUSGABE = REPO / "berichte"

EDGE = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

MONATSNAME = ["", "Januar", "Februar", "M\u00e4rz", "April", "Mai", "Juni", "Juli",
              "August", "September", "Oktober", "November", "Dezember"]
SUCHARTEN = {"suche": "eingetippt", "chip": "Schnellwahl",
             "metasuche": "Treffer direkt"}


# --------------------------------------------------------------- Werkzeug

def edge() -> str:
    for p in EDGE:
        if pathlib.Path(p).exists():
            return p
    raise SystemExit("Microsoft Edge nicht gefunden - ohne ihn kein PDF.")


def zahl(n: int | float, nach: int = 0) -> str:
    return f"{n:,.{nach}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def monat_davor(heute: dt.date) -> str:
    davor = heute.replace(day=1) - dt.timedelta(days=1)
    return f"{davor.year}-{davor.month:02d}"


def portale() -> list[dict]:
    datei = VORLAGE / "portale.json"
    if not datei.exists():
        raise SystemExit(f"{datei} fehlt - der Bericht braucht die Portalliste.")
    return json.loads(datei.read_text(encoding="utf-8"))["portale"]


def portal(kennwort: str) -> dict:
    """Ein Portal anhand von hub, Domain oder Name - in dieser Reihenfolge."""
    for p in portale():
        if kennwort in (p.get("hub"), p.get("domain"), p.get("name")):
            return p
    raise SystemExit(f"Kein Portal zu '{kennwort}'. Bekannt sind: "
                     + ", ".join(sorted(p["hub"] for p in portale())))


def portalordner(p: dict) -> pathlib.Path:
    return (VORLAGE / p["pfad"]).resolve()


def portalwerte(p: dict) -> dict:
    datei = portalordner(p) / "portal.json"
    return json.loads(datei.read_text(encoding="utf-8")) if datei.exists() else {}


def unterstuetzer(p: dict) -> list[dict]:
    """Die Sponsorenliste des Portals - gelesen mit dem Modul, das auch
    Newsletter und Downloads liest. Staende der Name hier anders als auf der
    Seite, waere einer von beiden falsch; das darf gar nicht moeglich sein."""
    if str(HUBSKRIPTE) not in sys.path:
        sys.path.insert(0, str(HUBSKRIPTE))
    import sponsoren                                   # noqa: E402
    return sponsoren.lade(portalordner(p))


# --------------------------------------------------------------- Quellen

def zaehlstand(monat: str, domain: str) -> dict:
    schluessel = (os.environ.get("ZAEHLERSCHLUESSEL")
                  or os.environ.get("ZAEHLER_SCHLUESSEL", "")).strip()
    if not schluessel:
        raise SystemExit("ZAEHLERSCHLUESSEL fehlt - ohne ihn gibt bericht.php nichts heraus.")
    adresse = ZAEHLER + "?" + urllib.parse.urlencode(
        {"schluessel": schluessel, "monat": monat, "hub": domain})
    # Die MVF-Seite weist Standard-Skriptkennungen mit 403 ab.
    anfrage = urllib.request.Request(adresse, headers={"User-Agent": KENNUNG})
    try:
        with urllib.request.urlopen(anfrage, timeout=120) as antwort:
            d = json.loads(antwort.read())
    except urllib.error.HTTPError as fehler:
        if fehler.code == 404:
            raise SystemExit("bericht.php antwortet 404 - falscher Schluessel, oder die "
                             "Fassung auf dem Server kennt &monat= noch nicht.")
        raise
    stand = dict(d.get("hubs", {}).get(domain, {}))
    stand["_tage"] = d.get("tage", {})
    return stand


def mc(pfad: str, params: dict | None = None) -> dict:
    schluessel = (os.environ.get("MAILCHIMP_API_KEY")
                  or os.environ.get("KNOWLEDGEHUBSMC", "")).strip()
    if not schluessel:
        raise SystemExit("MAILCHIMP_API_KEY fehlt - ohne ihn keine Newsletter-Zahlen.")
    rz = schluessel.rsplit("-", 1)[-1]
    adresse = f"https://{rz}.api.mailchimp.com/3.0{pfad}"
    if params:
        adresse += "?" + urllib.parse.urlencode(params)
    anfrage = urllib.request.Request(adresse)
    anfrage.add_header("Authorization", "Basic " + base64.b64encode(
        f"any:{schluessel}".encode()).decode())
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:
        return json.loads(antwort.read())


def newsletterzahlen(monat: str, praefix: str) -> list[dict]:
    """Die Ausgaben dieses Hubs im Monat, mit Zustellung und Oeffnungen.

    Gefiltert wird ueber den Kampagnentitel, nicht ueber die Zielgruppe: Der
    Titel ist das, was die Redaktion selbst vergibt (MC_PRAEFIX), und er bleibt
    auch dann richtig, wenn eine Ausgabe einmal an ein anderes Segment ging.
    """
    if not praefix:
        return []
    jahr, m = (int(x) for x in monat.split("-"))
    von = dt.datetime(jahr, m, 1, tzinfo=BERLIN)
    bis = dt.datetime(jahr + (m == 12), (m % 12) + 1, 1, tzinfo=BERLIN)
    d = mc("/campaigns", {"status": "sent", "count": 200,
                          "since_send_time": von.isoformat(),
                          "before_send_time": bis.isoformat(),
                          "sort_field": "send_time", "sort_dir": "ASC"})
    raus = []
    for k in d.get("campaigns", []):
        titel = (k.get("settings") or {}).get("title", "")
        if not titel.startswith(praefix):
            continue
        b = mc(f"/reports/{k['id']}")
        versandt = int(b.get("emails_sent", 0))
        prellt = b.get("bounces") or {}
        unzustellbar = int(prellt.get("hard_bounces", 0)) + int(prellt.get("soft_bounces", 0))
        geoeffnet = b.get("opens") or {}
        raus.append({
            "titel": titel,
            "gesendet": (k.get("send_time") or "")[:10],
            "versandt": versandt,
            "zugestellt": max(0, versandt - unzustellbar),
            "oeffnungen": int(geoeffnet.get("unique_opens", 0)),
        })
    return raus


# --------------------------------------------------------------- Satz

def balken(werte: list[tuple[str, int]], hoehe: int = 54) -> str:
    """Ein Tagesverlauf als Saeulen - ohne Bibliothek, ohne geladenes Bild."""
    if not werte:
        return '<p class="leer">F\u00fcr diesen Monat liegen keine Tageswerte vor.</p>'
    groesst = max(n for _, n in werte) or 1
    saeulen = "".join(
        f'<span class="saeule"><i style="height:{max(2, round(n / groesst * hoehe))}px"></i></span>'
        for _, n in werte)
    return (f'<div class="verlauf" style="height:{hoehe + 4}px">{saeulen}</div>'
            f'<p class="achse"><span>{escape(werte[0][0][-5:])}</span>'
            f'<span>Spitze: {zahl(groesst)} Aufrufe an einem Tag</span>'
            f'<span>{escape(werte[-1][0][-5:])}</span></p>')


def reihe(titel: str, paare: list[tuple[str, int]], summe: int, grenze: int = 6) -> str:
    if not paare:
        return ""
    oben = sorted(paare, key=lambda x: -x[1])[:grenze]
    zeilen = "".join(
        f'<tr><td>{escape(str(k))}</td><td class="z">{zahl(n)}</td>'
        f'<td class="z leise">{zahl(n / summe * 100, 1) if summe else "0,0"} %</td></tr>'
        for k, n in oben)
    return f'<h3>{escape(titel)}</h3><table class="liste">{zeilen}</table>'


def bericht_html(p: dict, monat: str, z: dict, nl: list[dict],
                 traeger: list[dict]) -> str:
    jahr, m = (int(x) for x in monat.split("-"))
    aufrufe = int(z.get("aufrufe", 0))
    besucher = int(z.get("besucher", 0))
    seiten = {k: int(v) for k, v in (z.get("seiten") or {}).items()}
    start = seiten.get("/", 0) + seiten.get("/index.html", 0)
    ereignisse = {k: int(v) for k, v in (z.get("ereignisse") or {}).items()}
    suchen = sum(ereignisse.values())
    tage = [(t, int((v.get(p["domain"]) or {}).get("aufrufe", 0)))
            for t, v in sorted((z.get("_tage") or {}).items())]

    zugestellt = sum(n["zugestellt"] for n in nl)
    oeffnungen = sum(n["oeffnungen"] for n in nl)

    art = "Medienpartner" if any(s.get("art") == "koop" for s in traeger) else "Sponsor"
    namen = ", ".join(s["n"] for s in traeger) or "\u2014 noch kein Eintrag \u2014"

    # Die Logos liegen im Portal und werden als Datei eingebettet: Ein Pfad in
    # einem PDF, das verschickt wird, ist beim Empfaenger ein leeres Kaestchen.
    logos = ""
    for s in traeger:
        datei = portalordner(p) / s["logo"]
        if datei.exists():
            typ = "image/svg+xml" if datei.suffix == ".svg" else f"image/{datei.suffix[1:]}"
            logos += (f'<img src="data:{typ};base64,'
                      f'{base64.b64encode(datei.read_bytes()).decode()}" '
                      f'alt="{escape(s["n"])}">')

    kacheln = [
        ("Logo-Ausspielungen", zahl(start), "Aufrufe der Startseite"),
        ("Aufrufe gesamt", zahl(aufrufe), "alle Seiten des Hubs"),
        ("Besucher", zahl(besucher), "tages-eindeutig, aufsummiert"),
        ("Suchen", zahl(suchen), "abgesendete Recherchen"),
    ]
    if nl:
        kacheln += [
            ("Newsletter zugestellt", zahl(zugestellt),
             f"{len(nl)} Ausgabe{'n' if len(nl) != 1 else ''} im Monat"),
            ("Logo im Newsletter gesehen", zahl(oeffnungen),
             (f"{zahl(oeffnungen / zugestellt * 100, 1)} % der Zustellungen"
              if zugestellt else "keine Zustellung")),
        ]
    kachelhtml = "".join(
        f'<div class="kachel"><b>{w}</b><span class="k-titel">{escape(t)}</span>'
        f'<span class="k-fuss">{escape(f)}</span></div>' for t, w, f in kacheln)

    nlzeilen = "".join(
        f'<tr><td>{escape(n["gesendet"])}</td><td>{escape(n["titel"])}</td>'
        f'<td class="z">{zahl(n["zugestellt"])}</td>'
        f'<td class="z">{zahl(n["oeffnungen"])}</td>'
        f'<td class="z leise">'
        f'{zahl(n["oeffnungen"] / n["zugestellt"] * 100, 1) if n["zugestellt"] else "0,0"} %'
        f'</td></tr>' for n in nl)
    nlblock = (f'<h3>Die Ausgaben im Einzelnen</h3><table class="liste">'
               f'<tr><th>Versandt</th><th>Ausgabe</th><th class="z">Zugestellt</th>'
               f'<th class="z">Ge\u00f6ffnet</th><th class="z">Quote</th></tr>'
               f'{nlzeilen}</table>' if nl else
               '<p class="leer">In diesem Monat ist keine Ausgabe des Hub-Newsletters '
               'versandt worden.</p>')

    sucharten = "".join(
        f'<tr><td>{escape(b)}</td><td class="z">{zahl(ereignisse.get(a, 0))}</td>'
        f'<td class="z leise">'
        f'{zahl(ereignisse.get(a, 0) / suchen * 100, 1) if suchen else "0,0"} %</td></tr>'
        for a, b in SUCHARTEN.items())

    begriffe = {k: int(v) for k, v in (z.get("begriffe") or {}).items()}
    begriffliste = "".join(
        f'<tr><td>{escape(b)}</td><td class="z">{zahl(n)}</td></tr>'
        for b, n in sorted(begriffe.items(), key=lambda x: -x[1])[:12] if n >= 5)
    begriffblock = (f'<h3>Wonach gesucht wurde</h3><table class="liste">'
                    f'{begriffliste}</table>' if begriffliste else
                    '<p class="leer">Kein Begriff hat in diesem Monat f\u00fcnf Suchen '
                    'erreicht.</p>')

    lato = (VORLAGE / "vorlage" / "fonts").resolve()
    schriften = "".join(
        f"@font-face{{font-family:'Lato';font-style:normal;font-weight:{g};"
        f"src:url('{(lato / f'lato-{g}.woff2').as_uri()}') format('woff2');}}"
        for g in (300, 400, 700) if (lato / f"lato-{g}.woff2").exists())

    quellen = reihe("Woher die Aufrufe kamen", list((z.get("quellen") or {}).items()), aufrufe)
    geraete = reihe("Ger\u00e4t", list((z.get("geraete") or {}).items()), aufrufe, 4)

    return f"""<!doctype html>
<meta charset="utf-8">
<title>Sponsorenbericht {escape(p['name'])} {monat}</title>
<style>
  {schriften}
  @page{{ size:A4; margin:16mm 15mm 14mm; }}
  html,body{{ margin:0; padding:0; font-family:'Lato',Helvetica,Arial,sans-serif;
             color:#1a1a1a; font-size:10.5pt; line-height:1.45; }}
  h1{{ font-size:19pt; margin:0 0 2px; color:#00529e; }}
  h2{{ font-size:12pt; margin:20px 0 8px; color:#00529e;
      border-bottom:2px solid #B4975B; padding-bottom:3px; }}
  h3{{ font-size:10.5pt; margin:13px 0 5px; color:#333; }}
  .kopf{{ border-top:4px solid #B4975B; padding-top:12px; }}
  .zeitraum{{ color:#6b7178; font-size:10pt; margin:0; }}
  .traeger{{ margin:13px 0 0; padding:11px 14px; background:#f3f6fa;
            border-left:4px solid #00529e; display:flex; align-items:center; gap:14px; }}
  .traeger img{{ height:38px; width:auto; max-width:180px; }}
  .traeger b{{ display:block; font-size:12pt; }}
  .traeger span{{ font-size:9.5pt; color:#6b7178; }}
  .kacheln{{ display:flex; flex-wrap:wrap; gap:8px; margin:13px 0 0; }}
  .kachel{{ flex:1 1 30%; min-width:150px; border:1px solid #e3e7ec;
           border-radius:5px; padding:9px 11px; }}
  .kachel b{{ display:block; font-size:17pt; color:#00529e; line-height:1.1; }}
  .k-titel{{ display:block; font-size:9.5pt; font-weight:700; margin-top:2px; }}
  .k-fuss{{ display:block; font-size:8.5pt; color:#6b7178; }}
  table.liste{{ width:100%; border-collapse:collapse; font-size:9.5pt; }}
  table.liste th{{ text-align:left; font-size:8.5pt; text-transform:uppercase;
                  letter-spacing:.05em; color:#6b7178;
                  border-bottom:1px solid #e3e7ec; padding:3px 6px 3px 0; }}
  table.liste td{{ padding:3px 6px 3px 0; border-bottom:1px solid #f0f2f5; }}
  table.liste td.z, table.liste th.z{{ text-align:right; white-space:nowrap; }}
  .leise{{ color:#6b7178; }}
  .leer{{ font-size:9.5pt; color:#6b7178; margin:6px 0 0; }}
  /* Die Saeulen fuellen die Breite - aber nur bis 24 Pixel je Tag. Ein Monat
     mit drei Tagen Daten (der erste Monat eines Hubs) haette sonst drei
     handbreite Balken und saehe aus wie ein Fehler. */
  .verlauf{{ display:flex; align-items:flex-end; justify-content:flex-start;
            gap:2px; margin:6px 0 2px; }}
  .saeule{{ flex:1 1 0; max-width:24px; display:flex; align-items:flex-end; }}
  .saeule i{{ display:block; width:100%; background:#00529e; border-radius:1px; }}
  .achse{{ display:flex; justify-content:space-between; font-size:8.5pt;
          color:#6b7178; margin:0; }}
  .spalten{{ display:flex; gap:22px; }}
  .spalten > div{{ flex:1; min-width:0; }}
  .fuss{{ margin-top:18px; padding-top:9px; border-top:1px solid #e3e7ec;
         font-size:8.5pt; color:#6b7178; }}
  .fuss p{{ margin:0 0 5px; }}
  .fuss b{{ color:#333; }}
</style>

<div class="kopf">
  <h1>{escape(p['name'])}</h1>
  <p class="zeitraum">Sponsorenbericht {MONATSNAME[m]} {jahr} &middot; {escape(p['domain'])}</p>
</div>

<div class="traeger">
  {logos}
  <div><b>{escape(namen)}</b><span>{art} dieses Knowledge-Hubs</span></div>
</div>

<div class="kacheln">{kachelhtml}</div>

<h2>Die Seite</h2>
{balken(tage)}
<div class="spalten">
  <div>{quellen}</div>
  <div>{geraete}<h3>Suche</h3><table class="liste">{sucharten}</table></div>
</div>
{begriffblock}

<h2>Der Newsletter</h2>
{nlblock}

<div class="fuss">
  <p><b>Wie gemessen wird.</b> Die Reichweite der Seite z\u00e4hlt ein eigener
  Server von <i>Monitor Versorgungsforschung</i>; ein Dritter ist nicht
  beteiligt. Es werden keine Cookies gesetzt und keine IP-Adressen gespeichert.
  \u201eBesucher\u201c ist <b>tages-eindeutig</b>: Die Wiedererkennung endet jede
  Nacht, der Monatswert ist die Summe der Tage und nicht die Zahl der Personen.
  Aufrufe von Browsern mit <i>Do Not Track</i> oder <i>Global Privacy
  Control</i> werden gar nicht erst gez\u00e4hlt \u2014 alle Zahlen sind eher zu
  niedrig als zu hoch.</p>
  <p><b>Logo-Ausspielungen</b> sind die Aufrufe der Startseite, auf der das
  Sponsorenfeld steht. <b>Logo im Newsletter gesehen</b> sind die \u00d6ffnungen:
  Eine \u00d6ffnung wird \u00fcber ein geladenes Bild gemessen \u2014 wer als
  \u00d6ffnung z\u00e4hlt, hat die Bilder der E-Mail geladen.</p>
  <p><b>Suchbegriffe</b> erscheinen ab f\u00fcnf Suchen im Monat. Begriffe, die
  eine Krankheit oder Diagnose benennen, werden nicht gespeichert; die Suche
  selbst z\u00e4hlt trotzdem mit.</p>
  <p>Erstellt am {dt.datetime.now(BERLIN).strftime('%d.%m.%Y')} &middot;
  \u201eMonitor Versorgungsforschung\u201c, eRelation AG \u2013 Content in Health, Bonn</p>
</div>
"""


def pdf(html: str, ziel: pathlib.Path) -> None:
    ziel.parent.mkdir(parents=True, exist_ok=True)
    quelle = ziel.with_suffix(".html")
    quelle.write_text(html, encoding="utf-8")
    subprocess.run([edge(), "--headless=new", "--disable-gpu",
                    "--no-pdf-header-footer", f"--print-to-pdf={ziel}",
                    quelle.as_uri()], capture_output=True, timeout=180)
    for _ in range(30):
        if ziel.exists() and ziel.stat().st_size > 0:
            break
        time.sleep(0.5)
    if not ziel.exists():
        raise SystemExit("Edge hat kein PDF geschrieben.")
    quelle.unlink()


# --------------------------------------------------------------- Ablauf

def einer(kennwort: str, monat: str, trocken: bool) -> pathlib.Path | None:
    p = portal(kennwort)
    traeger = unterstuetzer(p)
    if not traeger:
        print(f"  {p['name']}: kein Eintrag in der Sponsorenliste - "
              f"der Bericht entsteht trotzdem, aber ohne Namen.")
    z = zaehlstand(monat, p["domain"])
    nl = newsletterzahlen(monat, portalwerte(p).get("MC_PRAEFIX", ""))
    seiten = z.get("seiten") or {}
    print(f"  {p['name']:<34}{zahl(int(z.get('aufrufe', 0))):>8} Aufrufe, "
          f"{zahl(int(seiten.get('/', 0))):>8} auf der Startseite, "
          f"{len(nl)} Newsletter-Ausgabe(n)")
    if trocken:
        return None
    ziel = AUSGABE / f"Sponsorenbericht-{p['hub']}-{monat}.pdf"
    pdf(bericht_html(p, monat, z, nl, traeger), ziel)
    print(f"      {ziel}")
    return ziel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("hub", nargs="?", help="hub, Domain oder Name des Portals")
    ap.add_argument("--monat", help="JJJJ-MM; ohne Angabe der Vormonat")
    ap.add_argument("--alle", action="store_true",
                    help="jedes Portal, das einen Unterstuetzer eingetragen hat")
    ap.add_argument("--trocken", action="store_true", help="nur zeigen, kein PDF")
    a = ap.parse_args()

    monat = a.monat or monat_davor(dt.datetime.now(BERLIN).date())
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", monat):
        raise SystemExit("--monat bitte als JJJJ-MM.")
    if not a.alle and not a.hub:
        raise SystemExit("Welcher Hub? Oder --alle.")

    print(f"Sponsorenbericht {monat}")
    if a.alle:
        gefunden = 0
        for p in portale():
            if unterstuetzer(p):
                gefunden += 1
                einer(p["hub"], monat, a.trocken)
        if not gefunden:
            print("  Kein Portal hat derzeit einen Sponsor oder Medienpartner.")
        return 0
    einer(a.hub, monat, a.trocken)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
