#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Meta-Beschreibungen fuer den Altbestand der News nachtragen.

Am 26.08.2026 wurde der News-Bestand von m-vf.de gepruoft: In einer Stichprobe
von 120 Beitraegen quer durch die Jahrgaenge 2020 bis 2026 hatten **117 keine
Meta-Beschreibung**. Die drei Ausnahmen waren die Tagesnews, die den Schritt
seit jeher gehen. Hochgerechnet auf 8.579 News fehlt sie also fast ueberall.

Was das heisst: Google baut sich das Schnipsel in der Trefferliste selbst
zusammen, meist aus den ersten Zeilen des Fliesstextes. Das ist selten der
Satz, der zum Klicken bringt - und bei Pressemeldungen oft die Absenderzeile.

**Dieses Skript aendert veroeffentlichte Beitraege.** Deshalb:
  - Ohne --scharf passiert nichts. Der Trockenlauf zeigt, was geschehen wuerde.
  - Beitraege, die schon eine Meta-Beschreibung haben, werden nie angefasst.
  - --anzahl begrenzt den Lauf, damit sich das Ergebnis erst an zwanzig
    Beitraegen ansehen laesst, bevor achttausend folgen.

Aufruf:
    python scripts/meta_nachtragen.py                     # Trockenlauf, 20 Stueck
    python scripts/meta_nachtragen.py --anzahl 200        # Trockenlauf, 200
    python scripts/meta_nachtragen.py --anzahl 20 --scharf
    python scripts/meta_nachtragen.py --seit 2024 --scharf --anzahl 500
    python scripts/meta_nachtragen.py --zaehlen           # nur messen, nichts erzeugen

Geheimnisse in der Umgebung:
    KNOWLEDGEHUBS    Anthropic-Schluessel
    WPUSER           WordPress-Benutzer (Rolle Autor genuegt nicht - zum
                     Bearbeiten fremder Beitraege braucht es Redakteur)
    WPPASSWORT       dessen Anwendungspasswort
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WP = "https://www.monitor-versorgungsforschung.de/wp-json/wp/v2"
UA = "MVF-Knowledge-Hubs/1.0 (+https://knowledge-hubs.m-vf.de)"
KATEGORIE_NEWS = 1000

# Opus 5 ist der Hausstandard. Fuer diesen Lauf ist die Aufgabe einfach - ein
# Satz aus einem Text, den das Modell vor sich hat -, und die Menge macht den
# Unterschied spuerbar: Bei 8.400 Beitraegen kostet Opus 5 ueber die Batch-API
# rund 13 Dollar, Haiku 4.5 rund 2,50. Die Wahl trifft der Herausgeber, nicht
# dieses Skript; MODEL setzt sie um.
MODELL = os.environ.get("MODEL", "claude-opus-5")

# Wie viel Fliesstext dem Modell gezeigt wird. Der erste Teil einer Meldung
# traegt fast immer die Nachricht - mehr Text kostet nur Tokens.
TEXT_ZEICHEN = 1200

SYSTEM = (
    "Du schreibst Meta-Beschreibungen für die Trefferliste von Google, für "
    "die Nachrichtenseite von Monitor Versorgungsforschung, einem Fachmagazin "
    "für Versorgungsforschung. Die Leserschaft arbeitet im deutschen "
    "Gesundheitswesen. Schreibe knapp, konkret und ohne Werbesprache. Siezen. "
    "Keine Ausrufezeichen, keine Superlative, keine leeren Wendungen wie "
    "'spannende Einblicke'. Schreibe durchgehend korrekte deutsche "
    "Rechtschreibung mit Umlauten (ä, ö, ü, ß) - niemals ae, oe, ue, ss."
)

AUFTRAG = (
    "Schreibe die Meta-Beschreibung für diesen Beitrag.\n\n"
    "Regeln:\n"
    "- EIN Satz, 120 bis 155 Zeichen. Über 155 schneidet Google mitten im "
    "Wort ab.\n"
    "- Nennt das Ergebnis, die Entscheidung oder die Forderung - nicht die "
    "Gattung. Also nicht 'Eine Studie beschäftigt sich mit...', sondern was "
    "dabei herauskam.\n"
    "- Enthält die wichtigsten Suchwörter des Beitrags.\n"
    "- Für sich allein verständlich: Sie steht in der Trefferliste ohne den "
    "Beitrag daneben.\n"
    "- Wiederhole nicht wörtlich die Überschrift.\n"
    "Antworte NUR mit dem Satz, ohne Anführungszeichen.\n\n"
    "ÜBERSCHRIFT: {titel}\n\nTEXT: {text}"
)


def kopfzeilen(auth: str | None = None) -> dict:
    k = {"User-Agent": UA, "Accept": "application/json"}
    if auth:
        k["Authorization"] = f"Basic {auth}"
    return k


def text_aus_html(html: str) -> str:
    """Fliesstext ohne Markup - das Modell braucht keine Tags."""
    ohne = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    ohne = re.sub(r"<[^>]+>", " ", ohne)
    return re.sub(r"\s+", " ", unescape(ohne)).strip()


def sammeln(hoechstens: int, seit: int | None, auth: str) -> list[dict]:
    """News ohne Meta-Beschreibung, neueste zuerst.

    Geprueft wird ueber das Yoast-Feld selbst (context=edit), nicht ueber
    yoast_head_json: Letzteres zeigt bei manchen Konfigurationen einen
    errechneten Rueckfallwert an und verschweigt damit, dass das Feld leer ist.
    """
    offen: list[dict] = []
    seite = 1
    gesehen = 0
    while len(offen) < hoechstens and seite <= 200:
        ziel = (f"{WP}/posts?categories={KATEGORIE_NEWS}&per_page=50&page={seite}"
                f"&context=edit&orderby=date&order=desc"
                f"&_fields=id,date,title,content,excerpt,meta,link")
        if seit:
            ziel += f"&after={seit}-01-01T00:00:00"
        try:
            req = urllib.request.Request(ziel, headers=kopfzeilen(auth))
            with urllib.request.urlopen(req, timeout=60) as r:
                posts = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 400:      # hinter der letzten Seite
                break
            raise
        if not posts:
            break
        for p in posts:
            gesehen += 1
            steht = ((p.get("meta") or {}).get("_yoast_wpseo_metadesc") or "").strip()
            if steht:
                continue
            offen.append(p)
            if len(offen) >= hoechstens:
                break
        seite += 1
    print(f"{gesehen} Beiträge angesehen, {len(offen)} ohne Meta-Beschreibung.")
    return offen


def anfragen_bauen(posts: list[dict]) -> list[dict]:
    """Je Beitrag eine Batch-Anfrage. custom_id ist die Beitragsnummer."""
    anfragen = []
    for p in posts:
        titel = unescape((p.get("title") or {}).get("raw")
                         or (p.get("title") or {}).get("rendered") or "")
        roh = ((p.get("content") or {}).get("raw")
               or (p.get("content") or {}).get("rendered") or "")
        text = text_aus_html(roh)[:TEXT_ZEICHEN]
        if len(text) < 80:          # zu duenn, um etwas Sinnvolles zu schreiben
            continue
        anfragen.append({
            "custom_id": str(p["id"]),
            "params": {
                "model": MODELL,
                "max_tokens": 300,
                "system": SYSTEM,
                "messages": [{"role": "user",
                              "content": AUFTRAG.format(titel=titel, text=text)}],
            },
        })
    return anfragen


def batch_laufen_lassen(anfragen: list[dict]) -> dict[str, str]:
    """Batch abschicken, warten, Ergebnisse als {beitragsnummer: satz}.

    Die Batch-API kostet die Haelfte und ist fuer einen Lauf dieser Groesse
    der richtige Weg - sie darf sich bis zu 24 Stunden Zeit lassen, braucht
    hier aber meist Minuten.
    """
    import anthropic
    schluessel = os.environ.get("KNOWLEDGEHUBS", "").strip()
    if not schluessel:
        raise SystemExit("KNOWLEDGEHUBS ist nicht gesetzt.")
    client = anthropic.Anthropic(api_key=schluessel)

    stapel = client.messages.batches.create(requests=anfragen)
    print(f"Batch {stapel.id} mit {len(anfragen)} Anfragen abgeschickt.")
    while True:
        stapel = client.messages.batches.retrieve(stapel.id)
        if stapel.processing_status == "ended":
            break
        z = stapel.request_counts
        print(f"  ... {z.succeeded} fertig, {z.processing} laufen, "
              f"{z.errored} fehlerhaft")
        time.sleep(20)

    ergebnisse: dict[str, str] = {}
    fehler = 0
    for zeile in client.messages.batches.results(stapel.id):
        if zeile.result.type != "succeeded":
            fehler += 1
            continue
        satz = next((b.text for b in zeile.result.message.content
                     if b.type == "text"), "").strip().strip('"').strip()
        if satz:
            ergebnisse[zeile.custom_id] = satz
    print(f"{len(ergebnisse)} Beschreibungen erzeugt, {fehler} fehlgeschlagen.")
    return ergebnisse


def setzen(kennung: str, satz: str, auth: str) -> bool:
    req = urllib.request.Request(
        f"{WP}/posts/{kennung}", method="POST",
        data=json.dumps({"meta": {"_yoast_wpseo_metadesc": satz}}).encode("utf-8"),
        headers={**kopfzeilen(auth), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  {kennung}: HTTP {e.code} - nicht gesetzt")
        return False
    return bool((d.get("meta") or {}).get("_yoast_wpseo_metadesc"))


def main() -> int:
    p = argparse.ArgumentParser(description="Meta-Beschreibungen nachtragen")
    p.add_argument("--anzahl", type=int, default=20,
                   help="wie viele Beiträge höchstens (Vorgabe 20)")
    p.add_argument("--seit", type=int,
                   help="nur Beiträge ab diesem Jahr, z. B. 2024")
    p.add_argument("--scharf", action="store_true",
                   help="wirklich schreiben - ohne das passiert nichts")
    p.add_argument("--zaehlen", action="store_true",
                   help="nur messen, kein Modell und kein Schreiben")
    a = p.parse_args()

    nutzer = os.environ.get("WPUSER", "").strip()
    passwort = os.environ.get("WPPASSWORT", "").strip()
    if not (nutzer and passwort):
        print("WPUSER oder WPPASSWORT fehlt.")
        return 1
    auth = base64.b64encode(f"{nutzer}:{passwort}".encode()).decode()

    posts = sammeln(a.anzahl, a.seit, auth)
    if not posts:
        print("Nichts nachzutragen.")
        return 0
    if a.zaehlen:
        for x in posts[:10]:
            print(f"  {x['date'][:10]}  {unescape(x['title']['rendered'])[:70]}")
        return 0

    anfragen = anfragen_bauen(posts)
    print(f"{len(anfragen)} Beiträge mit genug Text.")
    if not anfragen:
        return 0

    ergebnisse = batch_laufen_lassen(anfragen)

    nach_id = {str(x["id"]): x for x in posts}
    geschrieben = 0
    for kennung, satz in ergebnisse.items():
        titel = unescape(nach_id[kennung]["title"]["rendered"])[:60]
        marke = " " if 120 <= len(satz) <= 155 else "!"
        print(f"{marke} {kennung} ({len(satz)}) {titel}\n    {satz}")
        if a.scharf and setzen(kennung, satz, auth):
            geschrieben += 1

    if a.scharf:
        print(f"\n{geschrieben} von {len(ergebnisse)} eingetragen.")
    else:
        print(f"\n[Trockenlauf] Nichts geschrieben. Mit --scharf eintragen.")
        print("Das '!' markiert Sätze außerhalb von 120 bis 155 Zeichen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
