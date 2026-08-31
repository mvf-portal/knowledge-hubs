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
// 2. Die Zielgruppe ("Audience"). Leer lassen genuegt, solange es genau EINE
//    gibt - dann sucht anmeldung.php sie sich selbst und merkt sie in
//    daten/liste.json.php. Gibt es einmal zwei, bricht der Endpunkt mit einer
//    klaren Meldung ab und die Kennung gehoert hierher.
//    Zu finden in Mailchimp unter Zielgruppe -> Einstellungen -> "Audience ID".
// ---------------------------------------------------------------------------
const LISTE = '';

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
//    DIE KENNUNGEN MUESSEN EINGETRAGEN WERDEN, sonst weist der Endpunkt jede
//    Bestellung mit "unbekannter-hub" ab. Das ist Absicht: Ein Endpunkt im
//    offenen Netz darf nur in Gruppen eintragen, die hier ausdruecklich
//    stehen.
//
//    Woher die Kennungen kommen: den Bericht aus Punkt 3 aufrufen. Er listet
//    jede Gruppe mit Namen und Kennung, fertig zum Abschreiben. Die Kennung
//    ist eine Folge aus Ziffern und Buchstaben wie "a1b2c3d4e5" - NICHT die
//    Zahlen aus "group[16135][512]", die zum alten Formular gehoerten.
// ---------------------------------------------------------------------------
const INTERESSEN = [
    'wissen'         => '',   // Studien-Newsletter Versorgungsforschung
    'klima'          => '',   // Hitze, Klima & Gesundheit
    'ki'             => '',   // Digitalisierung, KI & Gesundheit
    'pflege'         => '',   // Pflege & Langzeitversorgung
    'longevity'      => '',   // Gesundes Altern & Longevity
    'healthliteracy' => '',   // Gesundheitskompetenz
    'impfen'         => '',   // Impfen & Impfpraevention
    'ncd'            => '',   // Nicht uebertragbare Krankheiten
    'gender'         => '',   // Geschlechtersensible Medizin
    'adipositas'     => '',   // Adipositas
    'safety'         => '',   // Patientensicherheit
    'mental'         => '',   // Psychische Gesundheit
    'mvf'            => '',   // MVF-Newsletter (redaktionell)
    'datenschutz'    => '',   // "Datenschutzerklaerung gelesen" - wird immer mitgesetzt
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
const TAKT_JE_TAG = 200;
