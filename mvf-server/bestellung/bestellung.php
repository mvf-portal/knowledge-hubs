<?php
/**
 * Bestellung einer Evidenzsynthese aus dem Portal Innofonds-Wissen.
 *
 * Nimmt eine Bestellung von innofonds.m-vf.de entgegen, rechnet den
 * Preis auf dem Server aus, legt sie ab und schickt zwei Mails: die
 * Auftragsbestaetigung an den Besteller und die Bestellung an die
 * Rechnungsstelle.
 *
 * WARUM DER PREIS HIER GERECHNET WIRD
 * -----------------------------------
 * Die Seite sendet nur Stufe, Umfang und Nachlassgruppe - nie einen Betrag.
 * Alles, was im Browser steht, kann der Besteller aendern; ein mitgesendeter
 * Preis waere ein Vorschlag, kein Preis. Dieselbe Trennung wie bei den
 * Mailchimp-Gruppen in anmeldung.php: die Seite nennt einen Schluessel, die
 * Bedeutung kennt allein der Server.
 *
 * WARUM KEINE ZAHLUNG
 * -------------------
 * Gekauft wird von Instituten, Kliniken und Kassen. Die zahlen auf Rechnung,
 * ueber Beschaffung und Bestellnummer - ein Bezahlknopf im Browser hilft
 * ihnen nicht, er schliesst sie aus. Der Ablauf ist deshalb: Bestellung,
 * Rechnung, Lieferung des PDF. Ein Freischaltsystem braucht es nicht, weil
 * der kostenpflichtige Teil gar nicht erst in der Portalseite steht.
 *
 * WAS GESPEICHERT WIRD
 * --------------------
 * Anders als bei der Newsletter-Anmeldung muss hier sehr wohl etwas
 * gespeichert werden - eine Bestellung ohne Nachweis ist keine. Die Ablage
 * liegt in daten/ und beginnt wie dort mit `<?php exit; ?>`: MVF laeuft auf
 * nginx, nginx liest keine .htaccess, und eine .json waere im Web abrufbar.
 */

declare(strict_types=1);

$zugang = __DIR__ . '/bestellung-zugang.php';
if (!is_readable($zugang)) {
    antwort(500, ['ok' => false, 'grund' => 'nicht-eingerichtet']);
}
require $zugang;

// ---------------------------------------------------------------------------
// Herkunft. Das Portal liegt auf GitHub Pages, dieser Endpunkt auf
// monitor-versorgungsforschung.de - jede Anfrage ist domainfremd. Die Liste
// ist ausgeschrieben und kein Platzhalter: ein "*.m-vf.de" gaebe auch eine
// Subdomain frei, die uns eines Tages nicht mehr gehoert.
// ---------------------------------------------------------------------------
const HERKUNFT_ERLAUBT = [
    'https://innofonds.m-vf.de',
    'https://knowledge-hubs.m-vf.de',
];

$herkunft = $_SERVER['HTTP_ORIGIN'] ?? '';
if (in_array($herkunft, HERKUNFT_ERLAUBT, true)) {
    header('Access-Control-Allow-Origin: ' . $herkunft);
    header('Vary: Origin');
}
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    header('Access-Control-Max-Age: 86400');
    http_response_code(204);
    exit;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    antwort(405, ['ok' => false, 'grund' => 'nur-post']);
}
if ($herkunft !== '' && !in_array($herkunft, HERKUNFT_ERLAUBT, true)) {
    antwort(403, ['ok' => false, 'grund' => 'herkunft']);
}

taktbremse();

$roh = file_get_contents('php://input') ?: '';
$ein = json_decode($roh, true);
if (!is_array($ein)) {
    antwort(400, ['ok' => false, 'grund' => 'kein-json']);
}

// Honigtopf: ein Feld, das kein Mensch sieht und kein Mensch ausfuellt.
if (trim((string)($ein['website'] ?? '')) !== '') {
    antwort(200, ['ok' => true, 'nummer' => 'ER-0000000']);
}

// ---------------------------------------------------------------------------
// Pruefen
// ---------------------------------------------------------------------------
$pflicht = ['institution', 'name', 'strasse', 'plz', 'ort', 'email',
            'kohorte', 'stufe', 'umfang'];
$fehlt = [];
foreach ($pflicht as $feld) {
    if (trim((string)($ein[$feld] ?? '')) === '') {
        $fehlt[] = $feld;
    }
}
if ($fehlt) {
    antwort(400, ['ok' => false, 'grund' => 'unvollstaendig', 'felder' => $fehlt]);
}

$email = trim((string)$ein['email']);
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    antwort(400, ['ok' => false, 'grund' => 'email-ungueltig']);
}

$stufe  = (int)($ein['stufe'] ?? 0);
$umfang = (string)($ein['umfang'] ?? '');
$gruppe = (string)($ein['nachlass'] ?? 'keiner');
if (!isset(PREISE[$stufe][$umfang])) {
    antwort(400, ['ok' => false, 'grund' => 'unbekannte-leistung']);
}
if (!isset(NACHLAESSE[$gruppe])) {
    antwort(400, ['ok' => false, 'grund' => 'unbekannter-nachlass']);
}
if (!(bool)($ein['einverstanden'] ?? false)) {
    antwort(400, ['ok' => false, 'grund' => 'zustimmung-fehlt']);
}

// ---------------------------------------------------------------------------
// Rechnen. Kaufmaennisch auf Cent, nicht auf das, was der Browser anzeigt.
// ---------------------------------------------------------------------------
// Zweite und dritte Kohorte kosten die Haelfte, weil sich die Kohorten
// ueberschneiden: Ein Projekt traegt mehrere Versorgungsthemen und steht
// dann in mehreren Synthesen. Mehr als zwei weitere gibt es nicht, ab
// der vierten ist der Jahreszugang guenstiger.
$weitere = (int)($ein['weitere'] ?? 0);
if ($umfang === 'jahr') {
    $weitere = 0;
}
if ($weitere < 0 || $weitere > 2) {
    antwort(400, ['ok' => false, 'grund' => 'unzulaessige-stueckzahl']);
}
$einzeln = PREISE[$stufe][$umfang];
$grund   = $einzeln + $weitere * $einzeln / 2;
$prozent = NACHLAESSE[$gruppe];
$abzug   = round($grund * $prozent / 100, 2);
$netto   = round($grund - $abzug, 2);
$steuer  = round($netto * STEUERSATZ / 100, 2);
$brutto  = round($netto + $steuer, 2);

$felder = [];
foreach (['institution', 'name', 'abteilung', 'strasse', 'plz', 'ort', 'land',
          'ustid', 'bestellnummer', 'telefon', 'bemerkung', 'kohorte'] as $f) {
    $felder[$f] = saeubere((string)($ein[$f] ?? ''));
}
$felder['email'] = $email;

$nummer = nummer_bilden();
$jetzt  = date('d.m.Y');

$vorgang = [
    'nummer'    => $nummer,
    'zeitpunkt' => gmdate('c'),
    'leistung'  => ['stufe' => $stufe, 'umfang' => $umfang,
                    'kohorte' => $felder['kohorte'],
                    'weitere' => $weitere],
    'preis'     => ['grund' => $grund, 'nachlass' => $gruppe,
                    'prozent' => $prozent, 'abzug' => $abzug,
                    'netto' => $netto, 'steuersatz' => STEUERSATZ,
                    'steuer' => $steuer, 'brutto' => $brutto],
    'besteller' => $felder,
];
merken($vorgang);

// ---------------------------------------------------------------------------
// Mails
// ---------------------------------------------------------------------------
$bezeichnung = leistungstext($stufe, $umfang, $felder['kohorte'], $weitere);
$tafel = preistafel($bezeichnung, $grund, $gruppe, $prozent, $abzug,
                    $netto, $steuer, $brutto);

$anKunde = brief(
    'Auftragsbestätigung ' . $nummer,
    $felder, $nummer, $jetzt, $tafel,
    '<p>vielen Dank für Ihre Bestellung. Wir haben sie wie folgt aufgenommen '
    . 'und senden Ihnen die Rechnung sowie die Synthese in den nächsten '
    . 'Werktagen an ' . e($felder['email']) . '.</p>'
    . ($stufe === 2
        ? '<p><b>Falls diese Synthese für Sie neu erstellt wird:</b> Der '
          . 'Vorlauf beträgt etwa eine Woche. Sie erhalten sie dann vier '
          . 'Wochen lang exklusiv, erst danach steht sie anderen zur '
          . 'Verfügung.</p>'
        : '')
    . ($weitere > 0
        ? '<p><b>Welche weiteren Kohorten Sie möchten,</b> sagen Sie uns '
          . 'bitte formlos per Antwort auf diese Mail, falls es nicht '
          . 'schon in Ihrer Bemerkung steht.</p>'
        : '')
    . '<p><b>Sie erhalten die Synthese als PDF und als Word-Datei, die '
    . 'Evidenztabelle zusätzlich als Excel- und als CSV-Datei.</b> '
    . 'Die Tabelle ist damit sortier- und filterbar und lässt sich in '
    . 'eigene Auswertungen übernehmen — in einem PDF wäre sie das '
    . 'nicht.</p>',
    '<p style="margin-top:18px">Zahlbar innerhalb von 14 Tagen ohne Abzug '
    . 'nach Rechnungserhalt. Bitte geben Sie bei der Überweisung die '
    . 'Auftragsnummer an.</p>'
);
$anUns = brief(
    'Bestellung ' . $nummer . ' – ' . $bezeichnung,
    $felder, $nummer, $jetzt, $tafel,
    '<p><b>Neue Bestellung über innofonds.m-vf.de.</b></p>',
    bemerkungsblock($felder)
);

$kopf = "MIME-Version: 1.0\r\n"
      . "Content-Type: text/html; charset=UTF-8\r\n"
      . 'From: ' . ABSENDER_NAME . ' <' . ABSENDER . ">\r\n"
      . 'Reply-To: ' . EMPFAENGER . "\r\n";

$gesendet = @mail($email, 'Auftragsbestätigung ' . $nummer, $anKunde, $kopf);
@mail(EMPFAENGER, 'Bestellung ' . $nummer . ' – ' . $bezeichnung, $anUns,
      $kopf . 'Cc: ' . EMPFAENGER_KOPIE . "\r\n");

antwort(200, ['ok' => true, 'nummer' => $nummer,
              'brutto' => $brutto, 'netto' => $netto,
              'bestaetigung' => $gesendet]);

// ===========================================================================
// Darstellung - im Stil der eRelation-Angebote
// ===========================================================================

function leistungstext(int $stufe, string $umfang, string $kohorte,
                       int $weitere = 0): string
{
    $s = 'Evidenzsynthese Stufe ' . $stufe;
    if ($umfang === 'jahr') {
        return $s . ', Jahreszugang alle Kohorten';
    }
    $t = $s . ': ' . ($kohorte !== '' ? $kohorte : 'eine Kohorte');
    if ($weitere === 1) {
        $t .= ' sowie eine weitere Kohorte nach Wahl zum halben Preis';
    } elseif ($weitere === 2) {
        $t .= ' sowie zwei weitere Kohorten nach Wahl zum halben Preis';
    }
    return $t;
}

function geld(float $b): string
{
    return number_format($b, 2, ',', '.') . ' €';
}

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function preistafel(string $bezeichnung, float $grund, string $gruppe,
                    float $prozent, float $abzug, float $netto,
                    float $steuer, float $brutto): string
{
    $nachlassNamen = ['abo' => 'MVF-Abonnenten',
                      'beirat' => 'Mitglied des MVF-Beirats'];
    $z = '<table cellpadding="6" cellspacing="0" style="width:100%;'
       . 'border-collapse:collapse;font-size:14px">'
       . '<tr style="border-bottom:1px solid #333">'
       . '<th align="left">Pos</th><th align="left">Beschreibung</th>'
       . '<th align="right">Summe</th></tr>'
       . '<tr><td valign="top">1</td><td>' . e($bezeichnung)
       . '<br><span style="color:#666;font-size:12.5px">'
       . 'Lieferung als PDF und Word-Datei, Evidenztabelle zusätzlich als '
       . 'Excel- und CSV-Datei · Nutzung innerhalb der bestellenden '
       . 'Einrichtung'
       . '</span></td><td align="right">' . geld($grund) . '</td></tr>';
    if ($abzug > 0) {
        $z .= '<tr><td valign="top">2</td><td>Nachlass '
            . e($nachlassNamen[$gruppe] ?? $gruppe) . ' '
            . rtrim(rtrim(number_format($prozent, 1, ',', '.'), '0'), ',')
            . ' %</td><td align="right">−' . geld($abzug) . '</td></tr>';
    }
    return $z
        . '<tr style="border-top:1px solid #333"><td></td>'
        . '<td align="right">Summe</td><td align="right">' . geld($netto)
        . '</td></tr>'
        . '<tr><td></td><td align="right">Mehrwertsteuer '
        . number_format(STEUERSATZ, 2, ',', '.') . ' %</td>'
        . '<td align="right">' . geld($steuer) . '</td></tr>'
        . '<tr style="font-weight:bold"><td></td><td align="right">Endbetrag'
        . '</td><td align="right">' . geld($brutto) . '</td></tr></table>';
}

function bemerkungsblock(array $f): string
{
    if (trim($f['bemerkung']) === '') {
        return '';
    }
    return '<p style="margin-top:18px"><b>Bemerkung des Bestellers:</b><br>'
         . nl2br(e($f['bemerkung'])) . '</p>';
}

/** Der Brief traegt denselben Aufbau wie ein eRelation-Angebot. */
function brief(string $titel, array $f, string $nummer, string $datum,
               string $tafel, string $vorspann, string $nachspann): string
{
    $anschrift = e($f['institution']) . '<br>'
        . ($f['abteilung'] !== '' ? e($f['abteilung']) . '<br>' : '')
        . e($f['name']) . '<br>'
        . e($f['strasse']) . '<br>'
        . e($f['plz']) . ' ' . e($f['ort'])
        . ($f['land'] !== '' && strtolower($f['land']) !== 'deutschland'
           ? '<br>' . e($f['land']) : '');

    $zeilen = '';
    foreach (['ustid' => 'USt-IdNr.', 'bestellnummer' => 'Ihre Bestellnummer',
              'telefon' => 'Telefon'] as $k => $l) {
        if ($f[$k] !== '') {
            $zeilen .= '<tr><td style="color:#666">' . $l . '</td><td>'
                     . e($f[$k]) . '</td></tr>';
        }
    }

    return '<!DOCTYPE html><html lang="de"><body style="margin:0;padding:24px;'
        . 'background:#f6f7f9"><div style="max-width:660px;margin:0 auto;'
        . 'background:#fff;padding:32px 34px;font-family:Arial,Helvetica,'
        . 'sans-serif;color:#19212b;font-size:14px;line-height:1.55">'
        . '<p style="font-size:10.5px;color:#666;border-bottom:1px solid #ccc;'
        . 'padding-bottom:5px;margin:0 0 22px">eRelation AG · '
        . 'Johannes-von-Hanstein-Str. 2 · 53115 Bonn</p>'
        . '<p style="margin:0 0 22px">' . $anschrift . '</p>'
        . '<table cellpadding="0" cellspacing="0" style="width:100%;'
        . 'font-size:13px;margin-bottom:18px"><tr>'
        . '<td><h2 style="margin:0;font-size:17px">' . e($titel) . '</h2></td>'
        . '<td align="right" style="color:#666">' . $datum . '</td></tr></table>'
        . '<table cellpadding="2" cellspacing="0" style="font-size:13px;'
        . 'margin-bottom:18px">'
        . '<tr><td style="color:#666;padding-right:14px">Objekt</td>'
        . '<td>Innofonds-Wissen – Wissensportal zum Innovationsfonds</td></tr>'
        . '<tr><td style="color:#666">Auftragsnummer</td><td>' . e($nummer)
        . '</td></tr>' . $zeilen . '</table>'
        . $vorspann . $tafel . $nachspann
        . '<p style="margin-top:26px;font-size:12px;color:#666;'
        . 'border-top:1px solid #ccc;padding-top:14px">'
        . '<b>eRelation AG</b><br>'
        . 'Johannes-von-Hanstein-Str. 2 · 53115 Bonn<br>'
        . 'Tel.: +49 228 76368-30 · Fax: +49 228 76368-01<br>'
        . 'E-Mail: rechnung@erelation.org<br><br>'
        . 'USt-IdNr.: DE 215 393 582 · Steuer-Nr.: 205/5715/0717<br>'
        . 'Handelsregister: AG Bonn HRB 9392<br>'
        . 'Vorstand: Peter Stegmaier · Aufsichtsratsvorsitz: Bernhard Stegmaier'
        . '<br><br>Commerzbank Bonn · IBAN: DE77 3708 0040 0264 5324 02 · '
        . 'BIC: DRESDEFF</p></div></body></html>';
}

// ===========================================================================
// Werkzeug
// ===========================================================================

function antwort(int $code, array $daten): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($daten, JSON_UNESCAPED_UNICODE);
    exit;
}

/**
 * Steuerzeichen und Kopfzeilen-Einschleusung raus, Laenge begrenzen.
 *
 * Ohne mbstring wuerde ein blosses substr() ein Zeichen mitten in seinen
 * Bytes abschneiden und die Mail mit einem Fragezeichen enden lassen -
 * deshalb der Umweg ueber preg_split, der auch ohne die Erweiterung laeuft.
 */
function saeubere(string $s): string
{
    $s = trim(preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $s) ?? '');
    if (function_exists('mb_substr')) {
        return mb_substr($s, 0, 500);
    }
    $zeichen = preg_split('//u', $s, -1, PREG_SPLIT_NO_EMPTY) ?: [];
    return implode('', array_slice($zeichen, 0, 500));
}

/**
 * Auftragsnummer im Haus-Schema: ER-JJJJ + laufende Nummer des Jahres.
 * Der Zaehler steht in daten/, damit zwei Bestellungen in derselben Minute
 * nicht dieselbe Nummer bekommen.
 */
function nummer_bilden(): string
{
    $verzeichnis = __DIR__ . '/daten';
    if (!is_dir($verzeichnis)) {
        @mkdir($verzeichnis, 0775, true);
    }
    $datei = $verzeichnis . '/zaehler.json.php';
    $jahr = date('Y');
    $stand = ['jahr' => $jahr, 'nr' => 0];
    $fh = @fopen($datei, 'c+');
    if ($fh && flock($fh, LOCK_EX)) {
        $inhalt = stream_get_contents($fh) ?: '';
        $d = json_decode(substr($inhalt, 15), true);
        if (is_array($d) && ($d['jahr'] ?? '') === $jahr) {
            $stand = $d;
        }
        $stand['nr'] = (int)$stand['nr'] + 1;
        $stand['jahr'] = $jahr;
        ftruncate($fh, 0);
        rewind($fh);
        fwrite($fh, '<?php exit; ?>' . "\n"
                  . json_encode($stand, JSON_UNESCAPED_UNICODE));
        fflush($fh);
        flock($fh, LOCK_UN);
        fclose($fh);
    } else {
        $stand['nr'] = random_int(9000, 9999);
    }
    return sprintf('ER-IW-%s-%04d', $jahr, $stand['nr']);
}

/** Bestellungen monatsweise ablegen - nachweisbar, aber nicht im Web lesbar. */
function merken(array $vorgang): void
{
    $verzeichnis = __DIR__ . '/daten';
    if (!is_dir($verzeichnis)) {
        @mkdir($verzeichnis, 0775, true);
    }
    $datei = $verzeichnis . '/bestellungen-' . date('Y-m') . '.json.php';
    $liste = [];
    if (is_readable($datei)) {
        $d = json_decode(substr((string)file_get_contents($datei), 15), true);
        if (is_array($d)) {
            $liste = $d;
        }
    }
    $liste[] = $vorgang;
    $temp = $datei . '.' . getmypid() . '.tmp';
    @file_put_contents($temp, '<?php exit; ?>' . "\n"
        . json_encode($liste, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
    @rename($temp, $datei);
}

/**
 * Taktbremse wie in anmeldung.php: gespeichert wird nur ein Hashwert mit
 * taeglich wechselndem Salz, nie eine IP-Adresse.
 */
function taktbremse(): void
{
    $verzeichnis = __DIR__ . '/daten';
    if (!is_dir($verzeichnis)) {
        @mkdir($verzeichnis, 0775, true);
    }
    $heute = gmdate('Y-m-d');
    $salzDatei = $verzeichnis . '/salz.json.php';
    $salz = '';
    if (is_readable($salzDatei)) {
        $d = json_decode(substr((string)file_get_contents($salzDatei), 15), true);
        if (is_array($d) && ($d['tag'] ?? '') === $heute) {
            $salz = (string)($d['salz'] ?? '');
        }
    }
    if ($salz === '') {
        $salz = bin2hex(random_bytes(16));
        @file_put_contents($salzDatei, '<?php exit; ?>' . "\n"
            . json_encode(['tag' => $heute, 'salz' => $salz]));
    }
    $kennung = hash('sha256', $salz . ($_SERVER['REMOTE_ADDR'] ?? ''));
    $taktDatei = $verzeichnis . '/takt-' . $heute . '.json.php';
    $takt = [];
    if (is_readable($taktDatei)) {
        $d = json_decode(substr((string)file_get_contents($taktDatei), 15), true);
        if (is_array($d)) {
            $takt = $d;
        }
    }
    $takt[$kennung] = ($takt[$kennung] ?? 0) + 1;
    @file_put_contents($taktDatei, '<?php exit; ?>' . "\n"
        . json_encode($takt, JSON_UNESCAPED_UNICODE));
    foreach (glob($verzeichnis . '/takt-*.json.php') ?: [] as $alt) {
        if (basename($alt) !== 'takt-' . $heute . '.json.php') {
            @unlink($alt);
        }
    }
    if ($takt[$kennung] > TAKT_JE_TAG) {
        antwort(429, ['ok' => false, 'grund' => 'zu-oft']);
    }
}
