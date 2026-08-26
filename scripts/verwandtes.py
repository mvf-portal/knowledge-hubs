#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thematisch passende Altbeitraege auf m-vf.de finden - fuer "Mehr zum Thema".

Warum es das gibt: Am 26.08.2026 wurden die letzten zwanzig Beitraege der
Kategorie News ausgelesen. **Neunzehn davon enthielten keinen einzigen Link auf
einen anderen MVF-Beitrag.** Fuer Suchmaschinen ist jede Meldung damit eine
Sackgasse, und das Archiv - der eigentliche Wert eines Fachmagazins mit
zwanzig Jahrgaengen - bleibt unverbunden liegen. Interne Verweise sind der
billigste SEO-Hebel, den es gibt: Sie kosten keine Redaktionszeit, verteilen
Autoritaet im Bestand und halten die Leserschaft auf der Seite.

Gesucht wird ueber die WordPress-Suche, nicht ueber ein Sprachmodell. Ein
Modell, das Beitragsadressen nennen darf, erfindet sie irgendwann - dieselbe
Regel wie bei den Studienverweisen in tagesnews.py. Das Modell liefert nur die
Suchbegriffe, die Adressen kommen aus der Schnittstelle.

Aufruf zum Ausprobieren:
    python scripts/verwandtes.py Pflegepersonal Klinikschliessung
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import escape, unescape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WP = "https://www.monitor-versorgungsforschung.de/wp-json/wp/v2"
# Die MVF-Seite beantwortet Standard-Skriptkennungen mit HTTP 403. Jede Anfrage
# braucht eine eigene - dieselbe Falle wie in tagesnews.py und pressemeldung.py.
UA = "MVF-Knowledge-Hubs/1.0 (+https://knowledge-hubs.m-vf.de)"

# Mehr als drei Verweise lesen sich wie eine Linkliste und verwaessern jeden
# einzelnen. Drei sind genug, um das Archiv anzubinden.
HOECHSTENS = 3


def _suche(begriff: str, ausser: int | None = None) -> list[dict]:
    """Beitraege zu einem Begriff, nach Relevanz. Leere Liste statt Ausnahme.

    Ein fehlgeschlagener Verweisblock darf die Meldung nicht aufhalten - sie
    ist auch ohne ihn vollstaendig.
    """
    ziel = (f"{WP}/posts?search={urllib.parse.quote(begriff)}&per_page=6"
            f"&orderby=relevance&_fields=id,title,link,date")
    try:
        req = urllib.request.Request(ziel, headers={"User-Agent": UA,
                                                    "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            treffer = json.load(r)
    except (urllib.error.URLError, ValueError, TimeoutError) as fehler:
        print(f"  Suche nach '{begriff}' fehlgeschlagen: {fehler}")
        return []
    # Der eigene Beitrag ist bei einer Suche nach seinem eigenen Thema fast
    # immer der erste Treffer. Ohne diesen Filter verlinkt die Meldung auf
    # sich selbst.
    return [t for t in treffer if t.get("id") != ausser]


def finde(begriffe: list[str], ausser: int | None = None,
          hoechstens: int = HOECHSTENS) -> list[dict]:
    """Zu mehreren Begriffen die besten Treffer, ohne Dubletten.

    Reihum je ein Treffer pro Begriff, nicht erst alle zum ersten: Sonst
    stammen bei zwei Begriffen alle drei Verweise vom ersten, und der zweite
    Themenstrang taucht gar nicht auf.
    """
    listen = [_suche(b, ausser) for b in begriffe if b and b.strip()]
    gefunden: list[dict] = []
    gesehen: set[int] = set()
    for runde in range(6):
        for liste in listen:
            if len(gefunden) >= hoechstens:
                return gefunden
            if runde < len(liste) and liste[runde]["id"] not in gesehen:
                gesehen.add(liste[runde]["id"])
                gefunden.append(liste[runde])
    return gefunden


def html_block(beitraege: list[dict], ueberschrift: str = "Mehr zum Thema") -> str:
    """Der fertige Abschnitt - oder nichts, wenn es nichts zu verlinken gibt.

    h4 wie die uebrigen Zwischentitel im Haus. Kein target=_blank: Das hier
    fuehrt auf dieselbe Seite, ein neuer Reiter waere nur laestig - anders als
    bei den Verweisen in die Hubs, die auf eine andere Domain gehen.
    """
    if not beitraege:
        return ""
    zeilen = [f"<h4>{escape(ueberschrift)}</h4>", "<ul>"]
    for b in beitraege:
        titel = unescape(b.get("title", {}).get("rendered", "")).strip()
        jahr = (b.get("date") or "")[:4]
        zeilen.append(f'<li><a href="{escape(b["link"])}">{escape(titel)}</a>'
                      f'{f" ({jahr})" if jahr else ""}</li>')
    zeilen.append("</ul>")
    return "\n".join(zeilen)


def main() -> int:
    begriffe = sys.argv[1:]
    if not begriffe:
        print(__doc__)
        return 1
    treffer = finde(begriffe)
    print(f"{len(treffer)} Treffer zu {', '.join(begriffe)}:\n")
    for t in treffer:
        print(f"  {t['date'][:10]}  {unescape(t['title']['rendered'])}")
        print(f"    {t['link']}")
    print("\nHTML:\n" + html_block(treffer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
