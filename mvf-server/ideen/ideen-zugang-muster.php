<?php
/**
 * Muster fuer ideen-zugang.php - die echte Datei liegt NICHT im Repo.
 *
 * Auf dem Server als ideen-zugang.php daneben legen. Sie enthaelt nichts
 * Geheimes im Sinne eines Schluessels, aber sie bestimmt, wohin die
 * Zuschriften gehen, und das gehoert nicht in ein Repo.
 */

declare(strict_types=1);

// Wohin die Projektideen gehen.
const EMPFAENGER    = 'redaktion@m-vf.de';
const ABSENDER      = 'redaktion@m-vf.de';
const ABSENDER_NAME = 'Monitor Versorgungsforschung';

/**
 * Hoechstens so viele Zusendungen je Rechner und Tag. Niedriger als bei
 * der Bestellung: Wer an einem Tag mehr als drei Projektideen einreicht,
 * reicht keine ein.
 */
const TAKT_JE_TAG = 3;

/**
 * Schluessel, mit dem sich die anonyme Strichliste abrufen laesst. Frei
 * waehlbar, lang genug, und nicht derselbe wie irgendwo sonst. Bleibt er
 * leer, ist der Abruf gesperrt.
 */
const BERICHT_SCHLUESSEL = 'vCcXGFOBzi9OSpQ5eNpRg2FhUk0vmDV-';
