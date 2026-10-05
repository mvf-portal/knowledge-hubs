<?php
/**
 * Freiwillige Zusendung einer Projektidee aus dem Ideencheck.
 *
 * WARUM ES DIESEN ENDPUNKT UEBERHAUPT GIBT
 * ----------------------------------------
 * Der Ideencheck rechnet im Browser, und ueber dem Eingabefeld steht:
 * "Ihre Beschreibung verlaesst Ihren Rechner nicht." Das ist eine Zusage
 * und kein Marketingsatz. Sie bleibt wahr, weil hier nichts ankommt, was
 * nicht jemand ausdruecklich geschickt hat: Ohne gesetztes Haekchen und
 * ohne Absenderklick passiert gar nichts, und die Seite sendet auch dann
 * nur, was in diesem einen Kasten steht.
 *
 * WAS GESPEICHERT WIRD
 * --------------------
 * Die Beschreibung, die Adresse und, falls angegeben, Name und
 * Einrichtung. Dazu Datum und die Trefferliste, die der Check dazu
 * ausgerechnet hat - ohne sie waere die Zuschrift spaeter nicht mehr
 * einzuordnen. Keine IP-Adresse: Die Taktbremse rechnet mit einem
 * Hashwert und taeglich wechselndem Salz, wie in anmeldung.php.
 *
 * Die Ablage liegt in daten/ und beginnt mit `<?php exit; ?>`, weil MVF
 * auf nginx laeuft und nginx keine .htaccess liest. Eine .json waere im
 * Web abrufbar, und hier stehen unveroeffentlichte Projektideen. Das
 * waere der denkbar groesste Vertrauensbruch.
 */

declare(strict_types=1);

$zugang = __DIR__ . '/ideen-zugang.php';
if (!is_readable($zugang)) {
    antwort(500, ['ok' => false, 'grund' => 'nicht-eingerichtet']);
}
require $zugang;

// ---------------------------------------------------------------------------
// Herkunft. Ausgeschrieben und kein Platzhalter: ein "*.m-vf.de" gaebe auch
// eine Subdomain frei, die uns eines Tages nicht mehr gehoert.
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

// ---------------------------------------------------------------------------
// Eingang
// ---------------------------------------------------------------------------
$roh = file_get_contents('php://input') ?: '';
$f = json_decode($roh, true);
if (!is_array($f)) {
    antwort(400, ['ok' => false, 'grund' => 'kein-json']);
}

// ---------------------------------------------------------------------------
// Zwei weitere Betriebsarten neben der Zusendung.
// ---------------------------------------------------------------------------

/**
 * Die Strichliste. Sie bekommt das Themenfeld und die Bausteine, die der
 * Check im Browser ausgerechnet hat, nie den eingegebenen Text. Gespeichert
 * wird je Tag eine Summe, keine einzelne Anfrage: Aus "am 22.09. dreimal
 * Long Covid" laesst sich niemand herausloesen.
 */
if (($f['art'] ?? '') === 'zaehlung') {
    zaehle(
        saeubere((string)($f['themenfeld'] ?? ''), 120),
        array_slice(array_map(
            static fn($b) => saeubere((string)$b, 120),
            is_array($f['bausteine'] ?? null) ? $f['bausteine'] : []), 0, 3),
        (string)($f['bereich'] ?? '')
    );
    antwort(200, ['ok' => true]);
}

/**
 * Die Strichliste wieder herausgeben. Sie liegt in daten/ und ist im Web
 * nicht lesbar, deshalb dieser Weg mit Schluessel aus der Zugangsdatei.
 *
 *   curl -X POST .../ideen.php -H "Content-Type: application/json" \
 *        -d '{"art":"bericht","schluessel":"...","monat":"2026-09"}'
 */
if (($f['art'] ?? '') === 'bericht') {
    if (!defined('BERICHT_SCHLUESSEL') || BERICHT_SCHLUESSEL === ''
        || !hash_equals(BERICHT_SCHLUESSEL, (string)($f['schluessel'] ?? ''))) {
        antwort(403, ['ok' => false, 'grund' => 'schluessel']);
    }
    $monat = preg_match('/^\d{4}-\d{2}$/', (string)($f['monat'] ?? ''))
        ? (string)$f['monat'] : date('Y-m');
    $datei = __DIR__ . '/daten/themen-' . $monat . '.json.php';
    $d = is_readable($datei)
        ? json_decode(substr((string)file_get_contents($datei), 15), true) : [];
    antwort(200, ['ok' => true, 'monat' => $monat,
                  'zaehlung' => is_array($d) ? $d : []]);
}

// Das Haekchen ist die Rechtsgrundlage. Ohne ein ausdrueckliches true
// wird nichts gespeichert und nichts verschickt.
if (($f['einverstanden'] ?? false) !== true) {
    antwort(400, ['ok' => false, 'grund' => 'keine-einwilligung']);
}

$beschreibung = saeubere((string)($f['beschreibung'] ?? ''), 20000);
$email        = saeubere((string)($f['email'] ?? ''), 200);
$name         = saeubere((string)($f['name'] ?? ''), 200);
$einrichtung  = saeubere((string)($f['einrichtung'] ?? ''), 300);
$treffer      = saeubere((string)($f['treffer'] ?? ''), 1000);

if (mb_strlen_sicher($beschreibung) < 100) {
    antwort(400, ['ok' => false, 'grund' => 'zu-kurz']);
}
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    antwort(400, ['ok' => false, 'grund' => 'adresse']);
}

// ---------------------------------------------------------------------------
// Ablegen und weitergeben
// ---------------------------------------------------------------------------
$eingang = gmdate('c');
merken([
    'eingang'      => $eingang,
    'email'        => $email,
    'name'         => $name,
    'einrichtung'  => $einrichtung,
    'treffer'      => $treffer,
    'beschreibung' => $beschreibung,
]);

$kopf = "From: " . ABSENDER_NAME . " <" . ABSENDER . ">\r\n"
      . "Reply-To: " . $email . "\r\n"
      . "Content-Type: text/plain; charset=UTF-8\r\n"
      . "X-Mailer: ideen.php";

$anRedaktion = "Eine Projektidee aus dem Ideencheck, mit Einwilligung.\n\n"
    . "Absender:    " . ($name !== '' ? $name : 'ohne Namen') . "\n"
    . "Einrichtung: " . ($einrichtung !== '' ? $einrichtung : 'ohne Angabe') . "\n"
    . "Adresse:     " . $email . "\n"
    . "Eingang:     " . $eingang . "\n\n"
    . ($treffer !== '' ? "Naechste Projekte laut Check:\n" . $treffer . "\n\n" : '')
    . "Beschreibung:\n" . str_repeat('-', 60) . "\n" . $beschreibung . "\n";

@mail(EMPFAENGER, 'Ideencheck: eine Projektidee zur Durchsicht',
      $anRedaktion, $kopf);

// Bestaetigung an den Absender: Sie belegt, dass die Adresse stimmt, und
// sie sagt noch einmal, was gespeichert wurde und wie man es loeschen
// laesst. Beides gehoert zusammen.
$kopfAn = "From: " . ABSENDER_NAME . " <" . ABSENDER . ">\r\n"
        . "Reply-To: " . EMPFAENGER . "\r\n"
        . "Content-Type: text/plain; charset=UTF-8\r\n"
        . "X-Mailer: ideen.php";
$anAbsender = "Guten Tag,\n\n"
    . "vielen Dank, Ihre Projektidee ist bei uns angekommen. Wir sehen sie "
    . "uns an und melden uns bei Ihnen.\n\n"
    . "Gespeichert haben wir Ihre Beschreibung, Ihre Adresse und, soweit "
    . "angegeben, Namen und Einrichtung. Wir geben nichts davon weiter und "
    . "verwenden es ausschliesslich fuer diesen Zweck. Eine Zeile an "
    . EMPFAENGER . " genuegt, und wir loeschen alles.\n\n"
    . "Was Sie im Ideencheck selbst eingeben, bleibt weiterhin auf Ihrem "
    . "Rechner. Zu uns gelangt nur, was Sie hier ausdruecklich geschickt "
    . "haben.\n\n"
    . "Mit freundlichen Gruessen\n"
    . ABSENDER_NAME . "\n";
@mail($email, 'Ihre Projektidee ist angekommen', $anAbsender, $kopfAn);

antwort(200, ['ok' => true]);

// ---------------------------------------------------------------------------
// Werkzeug
// ---------------------------------------------------------------------------
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
 * Bytes abschneiden; deshalb der Umweg ueber preg_split, der auch ohne
 * die Erweiterung laeuft.
 */
function saeubere(string $s, int $grenze): string
{
    $s = trim(preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $s) ?? '');
    if (function_exists('mb_substr')) {
        return mb_substr($s, 0, $grenze);
    }
    $zeichen = preg_split('//u', $s, -1, PREG_SPLIT_NO_EMPTY) ?: [];
    return implode('', array_slice($zeichen, 0, $grenze));
}

function mb_strlen_sicher(string $s): int
{
    if (function_exists('mb_strlen')) {
        return mb_strlen($s);
    }
    return count(preg_split('//u', $s, -1, PREG_SPLIT_NO_EMPTY) ?: []);
}

/**
 * Strichliste je Tag. Bewusst ohne Zeitstempel unterhalb des Tages und
 * ohne jede Kennung: Was hier steht, sind Summen, und Summen lassen sich
 * nicht auf eine Person zurueckrechnen.
 */
function zaehle(string $thema, array $bausteine, string $bereich): void
{
    $verzeichnis = __DIR__ . '/daten';
    if (!is_dir($verzeichnis)) {
        @mkdir($verzeichnis, 0775, true);
    }
    $datei = $verzeichnis . '/themen-' . date('Y-m') . '.json.php';
    $stand = [];
    if (is_readable($datei)) {
        $d = json_decode(substr((string)file_get_contents($datei), 15), true);
        if (is_array($d)) {
            $stand = $d;
        }
    }
    $tag = date('Y-m-d');
    $stand[$tag] ??= ['anfragen' => 0, 'themen' => [], 'bausteine' => [],
                      'bereiche' => []];
    $stand[$tag]['anfragen']++;
    if ($thema !== '') {
        $stand[$tag]['themen'][$thema] = ($stand[$tag]['themen'][$thema] ?? 0) + 1;
    }
    foreach ($bausteine as $b) {
        if ($b !== '') {
            $stand[$tag]['bausteine'][$b] = ($stand[$tag]['bausteine'][$b] ?? 0) + 1;
        }
    }
    if ($bereich !== '') {
        $stand[$tag]['bereiche'][$bereich] =
            ($stand[$tag]['bereiche'][$bereich] ?? 0) + 1;
    }
    $temp = $datei . '.' . getmypid() . '.tmp';
    @file_put_contents($temp, '<?php exit; ?>' . "\n"
        . json_encode($stand, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
    @rename($temp, $datei);
}

function merken(array $vorgang): void
{
    $verzeichnis = __DIR__ . '/daten';
    if (!is_dir($verzeichnis)) {
        @mkdir($verzeichnis, 0775, true);
    }
    $datei = $verzeichnis . '/ideen-' . date('Y-m') . '.json.php';
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
    /* Die Zusendung ist knapp getaktet, das blosse Zaehlen nicht: Wer
       zwanzigmal prueft, ist ein gruendlicher Nutzer und kein
       Missbrauch. Erst weit oberhalb wird abgeriegelt. */
    $roh = file_get_contents('php://input') ?: '';
    $nurZaehlung = str_contains($roh, '"zaehlung"');
    $grenze = $nurZaehlung ? TAKT_JE_TAG * 20 : TAKT_JE_TAG;
    if ($takt[$kennung] > $grenze) {
        antwort(429, ['ok' => false, 'grund' => 'zu-oft']);
    }
}
