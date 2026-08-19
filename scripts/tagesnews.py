#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Die Tagesnews: ein WordPress-Entwurf und die Liste an die Redaktion.

Aus der Sammeldatei von `studien_sammeln.py` entsteht taeglich zweierlei:

1. Ein **Entwurf auf m-vf.de** in der Kategorie News - kurze Meldung mit ein
   paar Beispielen und Verweisen in die Hubs. Freigegeben wird er von Hand;
   das Skript veroeffentlicht nichts. Der WordPress-Benutzer hat deshalb die
   Rolle Autor und kann gar nicht veroeffentlichen, selbst wenn es wollte.
2. Eine **Mailchimp-Ausgabe an die Redaktion** mit allen Neuzugaengen des Tages,
   nach Hub gruppiert.

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
import json
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
WP_KATEGORIE = 1000            # "News" - am 19.08.2026 nachgesehen
UEBERSICHT = "https://knowledge-hubs.m-vf.de/"
UTM = "?utm_source=mvf-news&utm_medium=referral&utm_campaign=tagesnews"

MC_GRUPPE = "group[16144][65536]"      # Redaktion Tagesliste
MC_GRUPPE_NAME = "Redaktion Tagesliste"
MC_LISTE_KENNUNG = "1c8fc10ec7"
MC_ABSENDER = "Monitor Versorgungsforschung"
MC_ANTWORT = "redaktion@m-vf.de"

MODELL = os.environ.get("MODEL", "claude-opus-5")

SYSTEM = (
    "Du schreibst kurze Meldungen fuer die Nachrichtenseite von Monitor "
    "Versorgungsforschung, einem Fachmagazin fuer Versorgungsforschung. "
    "Deine Leserschaft arbeitet im deutschen Gesundheitswesen: Kliniken, "
    "Praxen, Kostentraeger, Selbstverwaltung, Politik. Sie ist fachkundig und "
    "hat wenig Zeit. Schreibe knapp, konkret und ohne Werbesprache. Siezen. "
    "Keine Ausrufezeichen, keine Superlative, keine leeren Wendungen wie "
    "'spannende Einblicke' oder 'wertvolle Erkenntnisse'."
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["titel", "vorspann", "beispiele", "schluss"],
    "properties": {
        "titel": {"type": "string"},
        "vorspann": {"type": "string"},
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
        "schluss": {"type": "string"},
    },
}


# ------------------------------------------------------------------- Daten
def studien_von_heute() -> tuple[list[dict], str]:
    pfad = pathlib.Path("studien.json")
    if not pfad.exists():
        raise SystemExit("studien.json fehlt - erst scripts/studien_sammeln.py laufen lassen.")
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    heute = dt.date.today().isoformat()
    return [e for e in daten.get("studien", []) if e.get("aufgenommen") == heute], heute


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
        f"Heute sind in den acht Knowledge-Hubs {len(studien)} neue Studien "
        f"aufgenommen worden, verteilt auf {len(gruppen)} Hubs.\n"
        f"{chr(10).join(material)}\n\n"
        "Schreibe daraus eine kurze Meldung:\n"
        "- titel: eine Zeile, sachlich, nennt die Zahl. Kein Doppelpunkt-Zusatz.\n"
        "- vorspann: zwei bis drei Saetze. Nennt die Zahl der Studien und der "
        "Hubs und sagt, was die Leserschaft davon hat.\n"
        "- beispiele: DREI bis VIER Studien, die fuer die Leserschaft am "
        "interessantesten sind. Je Beispiel die PMID und EIN Satz, der das "
        "Ergebnis nennt - konkret, mit Zahl, wenn eine da ist. Waehle aus "
        "verschiedenen Hubs.\n"
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
    return json.loads(text)


def baue_html(news: dict, studien: list[dict]) -> str:
    """Die Meldung als HTML. Jede Adresse stammt aus der Sammeldatei."""
    nach_pmid = {e["pmid"]: e for e in studien}
    gruppen = nach_hub(studien)

    teile = [f"<p><strong>{escape(news['vorspann'])}</strong></p>"]

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

    teile.append("<p><strong>Die Hubs im Einzelnen:</strong></p><ul>")
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
        "Alle acht Knowledge-Hubs im Überblick</a> — kostenfrei, ohne Anmeldung, "
        "mit täglichem Studien-Newsletter je Hub.</p>")
    return "\n".join(teile)


# -------------------------------------------------------------- WordPress
def wordpress_entwurf(titel: str, html: str, trocken: bool) -> None:
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
        with urllib.request.urlopen(req, timeout=60) as r:
            roh = r.read()
        return json.loads(roh) if roh else {}


def mailchimp_liste(studien: list[dict], heute: str, trocken: bool) -> None:
    schluessel = os.environ.get("KNOWLEDGEHUBSMC", "").strip()
    if not schluessel:
        print("KNOWLEDGEHUBSMC fehlt - keine Ausgabe an die Redaktion.")
        return

    gruppen = nach_hub(studien)
    datum = dt.date.fromisoformat(heute).strftime("%d.%m.%Y")
    zeilen = [f"<p>{len(studien)} neue Studien in {len(gruppen)} Hubs.</p>"]
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
            f'<h2 style="font:700 20px/1.3 Arial,sans-serif;">Neuzugänge {datum}</h2>'
            + "".join(zeilen) + "</div>")

    if trocken:
        print(f"[trocken] Mailchimp-Ausgabe waere versendet: "
              f"{len(studien)} Studien, {len(html)} Zeichen HTML.")
        return

    mc = Mailchimp(schluessel)
    kampagne = mc.ruf("/campaigns", {
        "type": "regular",
        "recipients": {
            "list_id": MC_LISTE_KENNUNG,
            "segment_opts": {"match": "all", "conditions": [{
                "condition_type": "Interests", "field": "interests-" + MC_GRUPPE,
                "op": "interestcontains", "value": [MC_GRUPPE]}]},
        },
        "settings": {
            "subject_line": f"Neuzugänge {datum} — {len(studien)} Studien aus {len(gruppen)} Hubs",
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
    a = p.parse_args()

    studien, heute = studien_von_heute()
    if not studien:
        print(f"Keine neuen Studien am {heute} - nichts zu melden.")
        return 0
    print(f"{len(studien)} Studien aus {len(nach_hub(studien))} Hubs.")

    if not a.nur_mail:
        news = schreibe_news(studien)
        html = baue_html(news, studien)
        print()
        print("=" * 72)
        print("TITEL: " + news["titel"])
        print("=" * 72)
        if a.trocken:
            # Im Trockenlauf den ganzen Entwurf zeigen - sonst laesst sich
            # nicht beurteilen, ob die Meldung taugt.
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
        wordpress_entwurf(news["titel"], html, a.trocken)

    if not a.nur_wordpress:
        mailchimp_liste(studien, heute, a.trocken)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
