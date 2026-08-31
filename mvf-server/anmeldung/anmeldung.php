<?php
/**
 * Newsletter- und Gewinnspielanmeldung fuer die Knowledge-Hubs.
 *
 * Nimmt eine Anmeldung von einer Hub-Seite entgegen und traegt sie ueber die
 * Mailchimp-API ein. Der API-Schluessel liegt in anmeldung-zugang.php neben
 * dieser Datei und verlaesst den Server nie.
 *
 * WARUM ES DAS GIBT
 * -----------------
 * Bis zum 31.08.2026 sendeten die Hub-Seiten unmittelbar an Mailchimps
 * Formularadresse /subscribe/post. Das funktioniert nicht mehr: Diese Adresse
 * ist inzwischen mit reCAPTCHA und Akamais Bot Manager geschuetzt. Eine
 * Einsendung von fremder Domain bringt weder das eine noch das andere mit,
 * wird mit HTTP 200 angenommen - und verworfen. Keine Anmeldung, keine
 * Bestaetigungsmail, kein Hinweis. Belegt am 31.08.2026 mit zwei echten
 * Adressen; der Gewinnspiel-Tag zaehlte danach null Kontakte.
 *
 * Zwei weitere Dinge heilt dieser Weg mit:
 *
 *  - Die Formularadresse verwarf bei einem BEREITS eingetragenen Kontakt
 *    alles Mitgeschickte. Wer schon Abonnent war, konnte ueber die Hub-Seite
 *    keinen weiteren Newsletter dazunehmen. Die API kann das.
 *  - Die Seite sendete in einen unsichtbaren Rahmen, dessen Inhalt sie nicht
 *    lesen darf, und meldete deshalb IMMER Erfolg. Hier kommt eine echte
 *    Antwort zurueck.
 *
 * WAS HIER NICHT PASSIERT
 * -----------------------
 * Es wird nichts gespeichert, was auf eine Person zeigt: keine E-Mail-Adresse,
 * kein Name, keine IP-Adresse. Die Taktbremse merkt sich nur einen nicht
 * umkehrbaren Hashwert mit taeglich wechselndem Salz - dasselbe Verfahren wie
 * im Zaehler.
 */

declare(strict_types=1);

$zugang = __DIR__ . '/anmeldung-zugang.php';
if (!is_readable($zugang)) {
    antwort(500, ['ok' => false, 'grund' => 'nicht-eingerichtet']);
}
require $zugang;

// ---------------------------------------------------------------------------
// Herkunft. Die Hub-Seiten liegen auf GitHub Pages unter *.m-vf.de, dieser
// Endpunkt auf monitor-versorgungsforschung.de - jede Anfrage ist also
// domainfremd und braucht die Freigabe im Kopf. Die Liste ist bewusst
// vollstaendig ausgeschrieben und kein Platzhalter: Ein "*.m-vf.de" wuerde
// auch eine Subdomain freigeben, die uns eines Tages nicht mehr gehoert.
// ---------------------------------------------------------------------------
const HERKUNFT_ERLAUBT = [
    'https://knowledge-hubs.m-vf.de',
    'https://wissen.m-vf.de',
    'https://klima.m-vf.de',
    'https://ki.m-vf.de',
    'https://pflege.m-vf.de',
    'https://longevity.m-vf.de',
    'https://healthliteracy.m-vf.de',
    'https://impfen.m-vf.de',
    'https://ncd.m-vf.de',
    'https://gender.m-vf.de',
    'https://adipositas.m-vf.de',
    'https://safety.m-vf.de',
    'https://mental.m-vf.de',
];

$herkunft = $_SERVER['HTTP_ORIGIN'] ?? '';
if (in_array($herkunft, HERKUNFT_ERLAUBT, true)) {
    header('Access-Control-Allow-Origin: ' . $herkunft);
    header('Vary: Origin');
}

// Der Vorabflug des Browsers. Ohne diese Antwort kommt die eigentliche
// Anfrage nie an.
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    header('Access-Control-Max-Age: 86400');
    http_response_code(204);
    exit;
}

// ---------------------------------------------------------------------------
// Der Bericht: listet die Interessen der Zielgruppe mit ihren Kennungen.
// Braucht man genau einmal, um INTERESSEN in anmeldung-zugang.php zu fuellen.
// Steht vor der Methodenpruefung, damit er sich im Browser aufrufen laesst.
// ---------------------------------------------------------------------------
if (isset($_GET['bericht'])) {
    if (BERICHT_SCHLUESSEL === '' || !hash_equals(BERICHT_SCHLUESSEL, (string)($_GET['schluessel'] ?? ''))) {
        antwort(403, ['ok' => false, 'grund' => 'schluessel']);
    }
    bericht();
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    antwort(405, ['ok' => false, 'grund' => 'methode']);
}

// ---------------------------------------------------------------------------
// Die Eingaben. Die Seite sendet JSON; Formularkodierung wird der Einfachheit
// halber auch angenommen.
// ---------------------------------------------------------------------------
$roh = file_get_contents('php://input') ?: '';
$ein = json_decode($roh, true);
if (!is_array($ein)) {
    $ein = $_POST;
}

$email  = trim((string)($ein['email']  ?? ''));
$vorname = mb_substr(trim((string)($ein['vorname']  ?? '')), 0, 60);
$nachname = mb_substr(trim((string)($ein['nachname'] ?? '')), 0, 60);
$hubs   = is_array($ein['hubs'] ?? null) ? $ein['hubs'] : [];
$tags   = is_array($ein['tags'] ?? null) ? $ein['tags'] : [];
$falle  = trim((string)($ein['falle'] ?? ''));

// Der Honigtopf. Menschen sehen das Feld nicht; Formularroboter fuellen es.
// Wir antworten trotzdem freundlich - wer merkt, dass er erkannt wurde,
// probiert es anders.
if ($falle !== '') {
    antwort(200, ['ok' => true, 'zustand' => 'neu']);
}

if ($email === '' || !filter_var($email, FILTER_VALIDATE_EMAIL) || mb_strlen($email) > 200) {
    antwort(400, ['ok' => false, 'grund' => 'email']);
}
if (!$hubs && !$tags) {
    antwort(400, ['ok' => false, 'grund' => 'nichts-gewaehlt']);
}

// ---------------------------------------------------------------------------
// Zulassungslisten. Ohne sie waere dieser Endpunkt ein offenes Tor, um
// beliebige Tags in die Zielgruppe zu schreiben - er steht schliesslich im
// offenen Netz und die Hub-Seiten sind fuer jeden lesbar.
// ---------------------------------------------------------------------------
// isset() laesst sich auf eine Konstante nicht anwenden - erst in eine
// Variable, sonst bricht PHP mit einem Syntaxfehler ab.
$tabelle = INTERESSEN;
$interessen = [];
foreach ($hubs as $schluessel) {
    $schluessel = (string)$schluessel;
    if (!isset($tabelle[$schluessel]) || $tabelle[$schluessel] === '') {
        antwort(400, ['ok' => false, 'grund' => 'unbekannter-hub']);
    }
    $interessen[$tabelle[$schluessel]] = true;
}
// MVF vermerkt die gelesene Datenschutzerklaerung als eigene Gruppe. Das tat
// das alte Formular bei jeder Anmeldung, und es soll dabei bleiben - sonst
// waeren Anmeldungen von den Hubs schlechter dokumentiert als die von m-vf.de.
if (($tabelle['datenschutz'] ?? '') !== '') {
    $interessen[$tabelle['datenschutz']] = true;
}
$tagNamen = [];
foreach ($tags as $t) {
    $t = (string)$t;
    if (!in_array($t, TAGS_ERLAUBT, true)) {
        antwort(400, ['ok' => false, 'grund' => 'unbekannter-tag']);
    }
    $tagNamen[] = ['name' => $t, 'status' => 'active'];
}

taktbremse();

// ---------------------------------------------------------------------------
// Eintragen. PUT legt an oder ergaenzt - genau der Unterschied zur
// Formularadresse. status_if_new sorgt dafuer, dass ein NEUER Kontakt erst
// bestaetigen muss (Double-Opt-in); ein bestehender behaelt seinen Zustand,
// bekommt also keine zweite Bestaetigungsmail und wird auch nicht wieder auf
// "ausstehend" zurueckgeworfen.
// ---------------------------------------------------------------------------
$hash = md5(strtolower($email));
$rumpf = [
    'email_address' => $email,
    'status_if_new' => 'pending',
];
if ($interessen) {
    $rumpf['interests'] = $interessen;
}
$merge = [];
if ($vorname !== '')  { $merge['FNAME'] = $vorname; }
if ($nachname !== '') { $merge['LNAME'] = $nachname; }
if ($merge) {
    $rumpf['merge_fields'] = $merge;
}

[$code, $antwort] = mailchimp('PUT', 'lists/' . liste() . '/members/' . $hash, $rumpf);

if ($code === 400 && ($antwort['title'] ?? '') === 'Member In Compliance State') {
    // Wer sich einmal abgemeldet oder eine Beschwerde geschickt hat, darf von
    // uns nicht wieder eingetragen werden - nur er selbst kann das. Das ist
    // kein Fehler, sondern geltendes Recht, und die Seite sagt es auch so.
    antwort(409, ['ok' => false, 'grund' => 'abgemeldet']);
}
if ($code < 200 || $code >= 300) {
    fehler_merken($code, (string)($antwort['title'] ?? ''), (string)($antwort['detail'] ?? ''));
    antwort(502, ['ok' => false, 'grund' => 'mailchimp']);
}

$zustand = ($antwort['status'] ?? '') === 'pending' ? 'bestaetigung-noetig' : 'eingetragen';

// Tags gehen ueber eine eigene Adresse und ueber ihren NAMEN - eine Nummer
// braucht es nicht, und ein noch nicht vorhandener Tag wird angelegt.
if ($tagNamen) {
    [$tcode, $tantwort] = mailchimp('POST', 'lists/' . liste() . '/members/' . $hash . '/tags',
                                    ['tags' => $tagNamen]);
    if ($tcode < 200 || $tcode >= 300) {
        // Der Kontakt steht schon; nur die Kennzeichnung fehlt. Das darf nicht
        // still bleiben - beim Gewinnspiel entscheidet genau dieser Tag ueber
        // die Teilnahme.
        fehler_merken($tcode, (string)($tantwort['title'] ?? ''), 'tags');
        antwort(502, ['ok' => false, 'grund' => 'tag']);
    }
}

antwort(200, ['ok' => true, 'zustand' => $zustand]);


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

/** Das Rechenzentrum steht als Nachsilbe im Schluessel: ...-us6 */
function rechenzentrum(): string
{
    $teile = explode('-', SCHLUESSEL);
    $dc = end($teile);
    if (!preg_match('/^[a-z]{2}\d+$/', $dc)) {
        antwort(500, ['ok' => false, 'grund' => 'schluessel-ohne-rechenzentrum']);
    }
    return $dc;
}

function mailchimp(string $verfahren, string $pfad, ?array $rumpf = null): array
{
    $ch = curl_init('https://' . rechenzentrum() . '.api.mailchimp.com/3.0/' . $pfad);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST  => $verfahren,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 15,
        CURLOPT_USERPWD        => 'mvf:' . SCHLUESSEL,
        CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
    ]);
    if ($rumpf !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($rumpf, JSON_UNESCAPED_UNICODE));
    }
    $roh  = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($roh === false) {
        return [0, []];
    }
    $daten = json_decode((string)$roh, true);
    return [$code, is_array($daten) ? $daten : []];
}

/**
 * Die Kennung der Zielgruppe. Steht sie in der Zugangsdatei, wird sie
 * genommen; sonst wird die einzige vorhandene Zielgruppe gesucht und
 * gemerkt. Das erspart beim Einrichten eine Stelle, an der man sich vertun
 * kann - und wenn es je zwei Zielgruppen gibt, faellt es hier auf.
 */
function liste(): string
{
    if (LISTE !== '') {
        return LISTE;
    }
    static $gemerkt = null;
    if ($gemerkt !== null) {
        return $gemerkt;
    }
    $datei = __DIR__ . '/daten/liste.json.php';
    if (is_readable($datei)) {
        $d = json_decode(substr((string)file_get_contents($datei), 15), true);
        if (is_array($d) && !empty($d['id'])) {
            return $gemerkt = (string)$d['id'];
        }
    }
    [$code, $a] = mailchimp('GET', 'lists?count=20&fields=lists.id,lists.name');
    if ($code !== 200 || count($a['lists'] ?? []) !== 1) {
        antwort(500, ['ok' => false, 'grund' => 'zielgruppe-unklar']);
    }
    $gemerkt = (string)$a['lists'][0]['id'];
    schreibe($datei, ['id' => $gemerkt, 'name' => $a['lists'][0]['name'] ?? '']);
    return $gemerkt;
}

/**
 * Taktbremse. Kein Schutz gegen einen entschlossenen Angreifer, aber sie
 * verhindert, dass ein einzelner Rechner die Zielgruppe volllaeuft.
 * Gespeichert wird nur ein Hashwert mit taeglich wechselndem Salz.
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
        schreibe($salzDatei, ['tag' => $heute, 'salz' => $salz]);
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
    schreibe($taktDatei, $takt);

    // Gestrige Dateien wegraeumen - der Hashwert ist mit dem Salz ohnehin wertlos.
    foreach (glob($verzeichnis . '/takt-*.json.php') ?: [] as $alt) {
        if (basename($alt) !== 'takt-' . $heute . '.json.php') {
            @unlink($alt);
        }
    }

    if ($takt[$kennung] > TAKT_JE_TAG) {
        antwort(429, ['ok' => false, 'grund' => 'zu-oft']);
    }
}

/**
 * Jede Datei in daten/ beginnt mit `<?php exit; ?>`. MVF laeuft auf nginx,
 * und nginx liest keine .htaccess - eine .json waere im Web abrufbar. Eine
 * .php wird nicht ausgeliefert, sondern ausgefuehrt, und bricht sofort ab.
 * Dasselbe Verfahren wie im Zaehler; wer die erste Zeile entfernt, oeffnet
 * das Verzeichnis.
 */
function schreibe(string $datei, array $daten): void
{
    $temp = $datei . '.' . getmypid() . '.tmp';
    @file_put_contents($temp, '<?php exit; ?>' . "\n" . json_encode($daten, JSON_UNESCAPED_UNICODE));
    @rename($temp, $datei);
}

/** Fehler von Mailchimp werden gemerkt - ohne alles, was auf eine Person zeigt. */
function fehler_merken(int $code, string $titel, string $wo): void
{
    $datei = __DIR__ . '/daten/fehler.json.php';
    $liste = [];
    if (is_readable($datei)) {
        $d = json_decode(substr((string)file_get_contents($datei), 15), true);
        if (is_array($d)) {
            $liste = $d;
        }
    }
    $liste[] = ['zeit' => gmdate('c'), 'code' => $code, 'titel' => $titel, 'wo' => $wo];
    schreibe($datei, array_slice($liste, -200));
}

/** Listet Interessen samt Kennung - einmal beim Einrichten gebraucht. */
function bericht(): void
{
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    $l = liste();
    echo "Zielgruppe: $l\n\n";
    [$code, $kat] = mailchimp('GET', "lists/$l/interest-categories?count=60");
    if ($code !== 200) {
        echo "Kategorien nicht lesbar (HTTP $code)\n";
        exit;
    }
    foreach ($kat['categories'] ?? [] as $k) {
        echo "== " . ($k['title'] ?? '?') . " ==\n";
        [$c2, $ints] = mailchimp('GET', "lists/$l/interest-categories/{$k['id']}/interests?count=100");
        foreach ($ints['interests'] ?? [] as $i) {
            printf("  %-42s %s\n", $i['name'] ?? '?', $i['id'] ?? '?');
        }
        echo "\n";
    }
    $datei = __DIR__ . '/daten/fehler.json.php';
    if (is_readable($datei)) {
        echo "== letzte Fehler ==\n" . substr((string)file_get_contents($datei), 15) . "\n";
    }
    exit;
}
