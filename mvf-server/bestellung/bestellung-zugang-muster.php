<?php
/**
 * Muster fuer bestellung-zugang.php - die echte Datei liegt NICHT im Repo.
 *
 * Auf dem Server als bestellung-zugang.php daneben legen und ausfuellen.
 * Sie enthaelt nichts Geheimes im Sinne eines Schluessels, aber sie
 * bestimmt Preise und Empfaenger - und die gehoeren nicht in ein Repo,
 * das jemand versehentlich oeffentlich stellt.
 */

declare(strict_types=1);

// Wohin die Bestellung geht.
const EMPFAENGER      = 'rechnung@erelation.org';
const EMPFAENGER_KOPIE = 'stegmaier@erelation.org';
const ABSENDER        = 'redaktion@m-vf.de';
const ABSENDER_NAME   = 'Monitor Versorgungsforschung';

// Steuersatz in Prozent. 19 ist der Regelsatz; ob fuer eine elektronische
// Publikation 7 gilt (Paragraph 12 Abs. 2 Nr. 14 UStG), klaert der
// Steuerberater - die Zahl steht deshalb hier und nicht im Code.
const STEUERSATZ = 19.0;

/**
 * Preise in Euro, netto. Die Seite sendet nur Stufe und Umfang, nie einen
 * Betrag - sonst koennte jeder im Browser seinen eigenen Preis setzen.
 * Dasselbe Vorgehen wie bei den Mailchimp-Gruppen in anmeldung.php.
 */
const PREISE = [
    1 => ['einzeln' => 490.0,  'jahr' => 1900.0],
    2 => ['einzeln' => 1900.0, 'jahr' => 4900.0],
];

/** Nachlaesse in Prozent. Schluessel ist das, was die Seite sendet. */
const NACHLAESSE = [
    'keiner' => 0.0,
    'abo'    => 25.0,   // MVF-Abonnenten
    'beirat' => 50.0,   // Mitglieder des MVF-Beirats
];

/** Hoechstens so viele Bestellungen je Rechner und Tag. */
const TAKT_JE_TAG = 10;
