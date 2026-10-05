# -*- coding: utf-8 -*-
"""
Aus einem Pressebild ein Kopfbild machen - wenn eines drin ist.

WOZU
----
In der Rubrik Personalien steht neben jeder Meldung das Bild aus dem Beitrag.
Angeliefert wird, was die Pressestelle schickt: mal ein Portraet, oft aber ein
Mensch vor einer Stellwand oder quer durch einen Konferenzraum. Im Newsletter
laeuft das Bild 170 Punkte breit - da sieht man dann den Raum und nicht die
Person.

Dieses Modul schneidet solche Bilder auf denselben Gesichtsausschnitt, den die
Autorenportraets auf m-vf.de haben.

DIE HAUSREGEL
-------------
Nicht "Gesicht finden und drumherum schneiden" - das ergibt bei jedem Bild
einen anderen Eindruck. Stattdessen zwei feste Verhaeltniszahlen, aus denen
sich der Ausschnitt rechnet: Die Gesichtshoehe nimmt einen festen Anteil der
Bildhoehe ein, die Augenlinie sitzt auf einer festen Hoehe. Die Zahlen sind
gemessen, nicht gegriffen - sie stammen aus dem Portraet von Dr. Lewin Eisele.

DIESELBE REGEL STEHT AN ZWEI STELLEN
------------------------------------
Das Original ist `mvf-einreichungssite/server/portrait-zuschnitt.py` auf dem
MVF-Server (Autorenprofile). Hier liegt sie ein zweites Mal, weil die beiden
Programme in verschiedenen Haeusern laufen und nichts voneinander wissen.
Zwei Fassungen derselben Regel laufen irgendwann auseinander - deshalb gibt es
`python kopfbild.py --abgleich`: Liegt die andere Datei auf demselben Rechner,
werden die Zahlen verglichen und Abweichungen gemeldet.

WAS ES NICHT TUT
----------------
Es entscheidet nicht allein. Kein Gesicht, mehrere Gesichter, Bild zu klein
fuer den Ausschnitt: Dann bleibt das Bild **unveraendert** und das Programm
sagt warum. Ein Verbandslogo hat kein Gesicht und geht deshalb von selbst
unangetastet durch - das ist der ganze Schutz, mehr braucht es nicht.

Und es vergroessert nie. Aus einem kleinen Gesicht wird kein grosses Kopfbild,
sondern eine Meldung.

OHNE OPENCV
-----------
Auf dem Rechner der Redaktion ist OpenCV moeglicherweise nicht installiert.
Dann faellt der Zuschnitt aus - und sonst nichts: `zuschneiden()` gibt
`(None, Grund)` zurueck, die Meldung geht mit dem Originalbild hinaus wie
bisher. Nachinstallieren mit

    pip install "opencv-python-headless<5"

Fassung 5 liefert die Haar-Kaskaden nicht mehr mit; ohne die geht es nicht.

AUFRUF VON HAND
---------------
    python kopfbild.py bild1.jpg bild2.jpg     schneidet neben die Originale
    python kopfbild.py --abgleich              vergleicht die Hausregel
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

# --- Die Hausregel ---------------------------------------------------------

SEITE = (4, 5)          # Breite zu Hoehe - Hochformat, wie im Heft
GESICHT_ANTEIL = 0.58   # Gesichtshoehe im Verhaeltnis zur Bildhoehe
AUGEN_HOEHE = 0.42      # Augenlinie, von oben gemessen
TOLERANZ = 0.04         # so viel darf das Bild am Rand fehlen
MINDESTBREITE = 354     # 30 mm bei 300 dpi; darunter wird nicht geschnitten
MAX_BREITE = 1200       # darueber kostet es nur Rechenzeit

ORIGINAL = pathlib.Path(
    r"C:\Users\Stegmaier\Documents\Claude-Daten\mvf-einreichungssite"
    r"\server\portrait-zuschnitt.py")


def verfuegbar() -> tuple[bool, str]:
    """Laeuft der Zuschnitt auf diesem Rechner? Sonst: warum nicht."""
    try:
        import cv2                                    # noqa: F401
    except ImportError:
        return False, ('OpenCV fehlt - pip install "opencv-python-headless<5"')
    import cv2
    if not hasattr(cv2, "data"):
        return False, "OpenCV ohne Haar-Kaskaden (Fassung 5?)"
    pfad = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not os.path.exists(pfad):
        return False, "Haar-Kaskaden nicht gefunden unter " + cv2.data.haarcascades
    return True, "OpenCV " + cv2.__version__


def _gesicht_finden(bild):
    """(x, y, b, h) des Gesichts und wie es gefunden wurde - oder (None, None).

    Erst frontal, dann im Profil. Mehrere Treffer sind ein Abbruchgrund und
    kein Anlass zum Raten - es sei denn, einer ist deutlich groesser als alle
    anderen; dann ist es die Person im Vordergrund.
    """
    import cv2
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    grau = cv2.equalizeHist(grau)
    for name in ("haarcascade_frontalface_default.xml",
                 "haarcascade_profileface.xml"):
        finder = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        treffer = finder.detectMultiScale(grau, scaleFactor=1.1,
                                          minNeighbors=6, minSize=(60, 60))
        if len(treffer) == 1:
            return tuple(int(v) for v in treffer[0]), name
        if len(treffer) > 1:
            nach = sorted(treffer, key=lambda t: t[2] * t[3], reverse=True)
            if nach[0][2] * nach[0][3] > 2.2 * nach[1][2] * nach[1][3]:
                return (tuple(int(v) for v in nach[0]),
                        "%s (groesstes von %d)" % (name, len(treffer)))
            return None, "%d Gesichter - keines deutlich im Vordergrund" % len(treffer)
    return None, None


def _augenlinie(bild, gesicht):
    """Augenhoehe im Gesicht - gemessen, wenn moeglich; sonst geschaetzt."""
    import cv2
    x, y, b, h = gesicht
    feld = cv2.cvtColor(bild[y:y + h, x:x + b], cv2.COLOR_BGR2GRAY)
    augen = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_eye.xml").detectMultiScale(
            feld, scaleFactor=1.1, minNeighbors=6)
    if len(augen) >= 2:
        nach = sorted(augen, key=lambda t: t[2] * t[3], reverse=True)[:2]
        mitte = sum(a[1] + a[3] / 2.0 for a in nach) / 2.0
        return y + mitte, "Augen gemessen"
    return y + 0.40 * h, "Augen geschaetzt"


def zuschneiden(rohdaten: bytes) -> tuple[bytes | None, str]:
    """Kopfbild aus den Rohdaten - oder (None, Grund), wenn nicht.

    Das Original wird nicht angefasst; es kommt als Bytes herein und bleibt,
    was es ist. Zurueck kommt ein neues JPEG oder nichts.
    """
    geht, auskunft = verfuegbar()
    if not geht:
        return None, auskunft

    import cv2
    import numpy as np

    bild = cv2.imdecode(np.frombuffer(rohdaten, dtype=np.uint8),
                        cv2.IMREAD_COLOR)
    if bild is None:
        return None, "nicht als Bild lesbar"
    H, B = bild.shape[:2]

    gesicht, wie = _gesicht_finden(bild)
    if gesicht is None:
        return None, wie or "kein Gesicht erkannt"
    gx, gy, gb, gh = gesicht

    augen_y, augen_wie = _augenlinie(bild, gesicht)

    hoehe = gh / GESICHT_ANTEIL
    breite = hoehe * SEITE[0] / SEITE[1]
    oben = augen_y - AUGEN_HOEHE * hoehe
    links = gx + gb / 2.0 - breite / 2.0

    knapp = ""
    if hoehe > H:
        if hoehe <= H * (1 + TOLERANZ):
            knapp = "Hoehe auf das Bildmass gekuerzt"
            hoehe = H
            breite = hoehe * SEITE[0] / SEITE[1]
        else:
            return None, ("Bild zu klein fuer den Ausschnitt (%dx%d, gebraucht %dx%d)"
                          % (B, H, round(breite), round(hoehe)))
    if breite > B:
        if breite <= B * (1 + TOLERANZ):
            knapp = (knapp + "; " if knapp else "") + "Breite auf das Bildmass gekuerzt"
            breite = B
            hoehe = breite * SEITE[1] / SEITE[0]
        else:
            return None, ("Bild zu schmal fuer den Ausschnitt (%dx%d, gebraucht %dx%d)"
                          % (B, H, round(breite), round(hoehe)))

    links = max(0, min(links, B - breite))
    oben = max(0, min(oben, H - hoehe))
    l, o = int(round(links)), int(round(oben))
    b, h = int(round(breite)), int(round(hoehe))
    aus = bild[o:o + h, l:l + b]

    if aus.shape[1] < MINDESTBREITE:
        return None, ("Ausschnitt waere nur %d px breit - unter %d; nicht "
                      "vergroessert" % (aus.shape[1], MINDESTBREITE))

    verkleinert = ""
    if aus.shape[1] > MAX_BREITE:
        neue_hoehe = int(round(aus.shape[0] * MAX_BREITE / aus.shape[1]))
        aus = cv2.resize(aus, (MAX_BREITE, neue_hoehe),
                         interpolation=cv2.INTER_AREA)
        verkleinert = "auf %d px verkleinert" % MAX_BREITE

    erfolg, puffer = cv2.imencode(".jpg", aus,
                                  [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not erfolg:
        return None, "liess sich nicht als JPEG schreiben"

    zusatz = [x for x in (wie, augen_wie, knapp, verkleinert) if x]
    return (puffer.tobytes(),
            "%dx%d -> %dx%d (%s)" % (B, H, aus.shape[1], aus.shape[0],
                                     ", ".join(zusatz)))


def abgleich() -> int:
    """Stimmt die Hausregel hier noch mit der auf dem MVF-Server ueberein?"""
    if not ORIGINAL.exists():
        print("Die Vorlage liegt auf diesem Rechner nicht:", ORIGINAL)
        print("Nichts zu vergleichen - das ist kein Fehler.")
        return 0
    text = ORIGINAL.read_text(encoding="utf-8")
    hier = {"GESICHT_ANTEIL": GESICHT_ANTEIL, "AUGEN_HOEHE": AUGEN_HOEHE,
            "TOLERANZ": TOLERANZ, "MINDESTBREITE": MINDESTBREITE,
            "MAX_BREITE": MAX_BREITE}
    schlecht = 0
    for name, wert in hier.items():
        t = re.search(r"^%s\s*=\s*([0-9.]+)" % name, text, re.M)
        if not t:
            print("%-16s in der Vorlage nicht gefunden" % name)
            schlecht += 1
            continue
        dort = float(t.group(1))
        gleich = abs(dort - float(wert)) < 1e-9
        print("%-16s hier %-8s Vorlage %-8s %s"
              % (name, wert, t.group(1), "ok" if gleich else "WEICHT AB"))
        if not gleich:
            schlecht += 1
    t = re.search(r"^SEITE\s*=\s*\((\d+),\s*(\d+)\)", text, re.M)
    if t:
        dort = (int(t.group(1)), int(t.group(2)))
        print("%-16s hier %-8s Vorlage %-8s %s"
              % ("SEITE", "%d:%d" % SEITE, "%d:%d" % dort,
                 "ok" if dort == SEITE else "WEICHT AB"))
        if dort != SEITE:
            schlecht += 1
    print()
    print("Alles gleich." if not schlecht
          else "%d Abweichung(en) - eine der beiden Dateien ist aelter." % schlecht)
    return 1 if schlecht else 0


def main() -> int:
    if "--abgleich" in sys.argv:
        return abgleich()
    quellen = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not quellen:
        print(__doc__.strip().splitlines()[0])
        print("Aufruf: python kopfbild.py <bild> [<bild> ...] | --abgleich")
        return 2
    geht, auskunft = verfuegbar()
    print("Zuschnitt:", auskunft)
    if not geht:
        return 1
    for q in quellen:
        p = pathlib.Path(q)
        neu, wie = zuschneiden(p.read_bytes())
        if neu is None:
            print("%-28s unberuehrt - %s" % (p.name, wie))
            continue
        ziel = p.with_name(p.stem + "-kopf.jpg")
        if ziel.resolve() == p.resolve():
            print("%-28s ABBRUCH: Ziel gleich Quelle" % p.name)
            continue
        ziel.write_bytes(neu)
        print("%-28s %s -> %s" % (p.name, wie, ziel.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
