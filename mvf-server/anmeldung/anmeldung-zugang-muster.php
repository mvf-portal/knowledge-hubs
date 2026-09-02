<?php
/**
 * Zugangsdaten fuer anmeldung.php.
 *
 * Diese Datei umbenennen in  anmeldung-zugang.php  und ausfuellen.
 * Sie gehoert NICHT ins Repository und wird auch nie dorthin zurueckgespielt.
 *
 * Sie liegt im Web-Verzeichnis, wird aber nie ausgeliefert: nginx reicht jede
 * .php-Datei an PHP weiter, und diese hier gibt nichts aus.
 */

declare(strict_types=1);

// ---------------------------------------------------------------------------
// 1. Der Mailchimp-API-Schluessel.
//    In Mailchimp: Konto -> Extras -> API-Schluessel -> "Einen Schluessel
//    erstellen". Er endet auf das Rechenzentrum, hier "-us6" - anmeldung.php
//    liest daran ab, welche Serveradresse anzusprechen ist.
// ---------------------------------------------------------------------------
const SCHLUESSEL = 'HIER-DEN-API-SCHLUESSEL-EINTRAGEN-us6';

// ---------------------------------------------------------------------------
// 2. Die Zielgruppe ("Audience"). Sie MUSS hier stehen: Das Konto fuehrt 37
//    Zielgruppen - Altlasten aus Kongressen und Preisausschreiben seit 2015 -
//    und der Hausverteiler ist eine davon. Die Selbstsuche in anmeldung.php
//    greift nur bei genau einer Zielgruppe und bricht sonst ab.
// ---------------------------------------------------------------------------
const LISTE = '1c8fc10ec7';   // eRelation GESAMT

// ---------------------------------------------------------------------------
// 3. Ein selbst gewaehltes langes Kennwort fuer den Bericht. Damit laesst sich
//    im Browser nachsehen, welche Interessen die Zielgruppe hat und welche
//    Fehler zuletzt auftraten:
//
//      https://www.monitor-versorgungsforschung.de/anmeldung/anmeldung.php?bericht=1&schluessel=DAS_KENNWORT
//
//    Bleibt es leer, ist der Bericht abgeschaltet.
// ---------------------------------------------------------------------------
const BERICHT_SCHLUESSEL = '';

// ---------------------------------------------------------------------------
// 4. Die Newsletter. Links steht der kurze Name, den die Hub-Seiten senden,
//    rechts die Kennung des Interesses in Mailchimp.
//
//    Die Kennungen sind am 31.08.2026 aus der API ausgelesen und eingetragen.
//    Eine leere Zeile heisst: Dieser Newsletter kann nicht bestellt werden -
//    der Endpunkt weist ihn mit "unbekannter-hub" ab. Das ist Absicht: Ein
//    Endpunkt im offenen Netz darf nur in Gruppen eintragen, die hier
//    ausdruecklich stehen.
//
//    Kommt ein Hub dazu, liefert  py scripts/anmeldung_gruppen.py  im Repo
//    knowledge-hubs den Block neu.
//
//    Die Kennung ist eine Folge aus Ziffern und Buchstaben wie "8cb31ce0ef" -
//    NICHT die Zahlen aus "group[16135][512]", die zum alten Formular
//    gehoerten. Sie steht nirgends in der Mailchimp-Oberflaeche.
// ---------------------------------------------------------------------------
const INTERESSEN = [
    'wissen'         => '8cb31ce0ef',   // Studien Newsletter VF
    'klima'          => '401f8a686e',   // Studien Newsletter Klima
    'ki'             => 'b1f1b80f23',   // Studien Newsletter KI
    'pflege'         => 'e5860dc351',   // Studien Newsletter Pflege
    'longevity'      => 'b68ccf358b',   // Studien Newsletter Longevity
    'healthliteracy' => '44eda2dbac',   // Studien Newsletter HealthLiteracy
    'impfen'         => '771a8ede2a',   // Studien Newsletter Impfen
    'ncd'            => '7465643def',   // Studien Newsletter NCD
    'gender'         => '4c2d1464e8',   // Studien Newsletter Gender
    'adipositas'     => '469cb7b600',   // Studien Newsletter Adipositas
    'safety'         => '5d3b807f19',   // Studien Newsletter Safety
    'mental'         => '7791f837a9',   // Studien Newsletter MentalHealth
    'mvf'            => 'e77b605c5e',   // Monitor Versorgungsforschung Newsletter
    // Die Sonderaussendungen der Verlagspartner - Nachfolger des eBlast.
    // Eigener Schluessel, weil es eine eigene Einwilligung ist: Werbung
    // ist nicht vom Haekchen fuer einen Newsletter gedeckt.
    'sonderaussendungen' => ''          ,   // Sonderaussendungen unserer Verlagspartner
    'datenschutz'    => 'c19f3e28e4',   // Datenschutzerklaerung gelesen - wird immer mitgesetzt
];

// ---------------------------------------------------------------------------
// 5. Erlaubte Tags. Auch hier gilt: Was nicht dasteht, kann ueber diesen
//    Endpunkt nicht gesetzt werden. Der Tag wird ueber seinen NAMEN gesetzt;
//    eine Nummer braucht es nicht.
// ---------------------------------------------------------------------------
const TAGS_ERLAUBT = [
    'Gewinnspiel DKVF 2026',
];

// ---------------------------------------------------------------------------
// 6. Wie viele Anmeldungen ein einzelner Anschluss am Tag schicken darf.
//    Am Messestand teilen sich viele Menschen ein WLAN und damit eine
//    IP-Adresse - deshalb nicht zu knapp.
// ---------------------------------------------------------------------------
// Der Tag fuer die Dankesmail an bereits bekannte Abonnenten.
//
// Der Endpunkt setzt ihn, wenn eine Bestellung von einer Adresse kommt, die
// schon Abonnent ist - dann schickt Mailchimp von sich aus nichts. In
// Mailchimp haengt daran eine Customer Journey:
//
//     Ausloeser : Tag hinzugefuegt -> Nachbestellung
//     Aktion 1  : E-Mail senden
//     Aktion 2  : Tag entfernen -> Nachbestellung
//     Journey   : Wiedereintritt erlauben
//
// LEER LASSEN, solange diese Journey nicht steht. "Tag hinzugefuegt" feuert
// nur beim Uebergang; wer den Tag schon traegt, loest sie nie aus.
//
// Zum Einschalten hier den Namen eintragen - auf das Zeichen genau so, wie er
// in Mailchimp heisst - und die Datei neu hochladen.
// ---------------------------------------------------------------------------
const TAG_NACHBESTELLUNG = '';

// ---------------------------------------------------------------------------
const TAKT_JE_TAG = 200;
