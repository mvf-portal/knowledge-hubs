<?php
/**
 * Der Wecker der Knowledge-Hubs - Fassung fuer den MVF-Server.
 *
 * Einmal am Morgen ein einziger Aufruf an GitHub. Er loest im Repo
 * knowledge-hubs das Ereignis "morgenlauf" aus; der Workflow "Dirigent"
 * stoesst daraufhin die zwoelf Portale und den Sammelbericht an.
 *
 * Warum ueberhaupt: GitHubs Cron ist ausdruecklich "best effort". Am 27. und
 * 28.08.2026 hat er zwei Naechte hintereinander gar nichts gestartet - kein
 * fehlgeschlagener Lauf, sondern gar keiner -, obwohl alle Workflows aktiv
 * waren und jeder Start von Hand sofort lief. Die AUSFUEHRUNG bei GitHub ist
 * verlaesslich, die AUSLOESUNG nicht.
 *
 * Warum auf diesem Server: Die Aufgabenplanung auf dem Redaktionsrechner tut
 * dasselbe, aber nur, solange dieser Rechner laeuft. Der MVF-Server laeuft
 * ohnehin durch - und der Schluessel bleibt im Haus.
 *
 * Zwei Wege, dieses Skript zu starten:
 *
 *   1. Cron des Hosters (bevorzugt):
 *        php /pfad/zu/wecker/wecker.php
 *      Auf der Kommandozeile braucht es kein Geheimnis - dort kommt niemand
 *      von aussen hin.
 *
 *   2. Aufruf ueber das Netz, wenn der Hoster keinen Cron kann:
 *        https://www.monitor-versorgungsforschung.de/wecker/wecker.php?schluessel=...
 *      Ohne den richtigen Schluessel antwortet das Skript 404 und tut nichts -
 *      sonst koennte jeder, der die Adresse kennt, dreizehn Laeufe ausloesen.
 *
 * Einrichten: siehe LIESMICH.md in diesem Ordner.
 */

// ---------------------------------------------------------------- Einstellungen
// Die Zugangsdaten stehen in einer eigenen Datei NEBEN dieser - und zwar als
// .php, nicht als .json oder .txt: MVF laeuft auf nginx, .htaccess wird dort
// nicht gelesen, und eine .json waere unter ihrer Adresse einfach abrufbar.
// Dieselbe Lehre wie beim Zaehler (daten/*.json.php).
// Der Protokollpfad steht VOR der ersten moeglichen Fehlermeldung: Sonst
// schriebe fehler() beim fehlenden Zugang ins Leere.
//
// **Die Endung .php ist Absicht, keine Verwechslung.** Am 28.08.2026 lag das
// Protokoll als wecker.log auf dem Server und war unter seiner Adresse
// abrufbar - MVF laeuft auf nginx, .htaccess wird dort nicht gelesen. Es stand
// zwar nichts Geheimes darin, aber es verriet Zeitpunkte und Fehlerbilder.
// Dieselbe Lehre wie beim Zaehler, dessen Datendateien deshalb *.json.php
// heissen. Die erste Zeile der Datei bricht die Ausfuehrung ab.
$PROTOKOLL = __DIR__ . '/wecker.log.php';

$einstellungen = __DIR__ . '/wecker-zugang.php';
if (!is_file($einstellungen)) {
    fehler('wecker-zugang.php fehlt - siehe LIESMICH.md', 500);
}
$zugang = require $einstellungen;

$REPO      = $zugang['repo']      ?? 'mvf-portal/knowledge-hubs';
$EREIGNIS  = $zugang['ereignis']  ?? 'morgenlauf';
$TOKEN     = $zugang['token']     ?? '';
$SCHLUESSEL = $zugang['schluessel'] ?? '';

$vonHand = PHP_SAPI !== 'cli';

// ------------------------------------------------------------------ Torwaechter
if ($vonHand) {
    // hash_equals vergleicht in gleichbleibender Zeit - ein einfaches ===
    // verraet ueber die Laufzeit, wie viele Zeichen stimmen.
    $mitgegeben = $_GET['schluessel'] ?? '';
    if ($SCHLUESSEL === '' || !hash_equals($SCHLUESSEL, $mitgegeben)) {
        http_response_code(404);
        header('Content-Type: text/plain; charset=utf-8');
        echo "Nichts zu sehen.\n";
        exit;
    }
}

if ($TOKEN === '') {
    fehler('In wecker-zugang.php fehlt das Token.', 500);
}

// ------------------------------------------------------------------- Weckruf
$rumpf = json_encode([
    'event_type'    => $EREIGNIS,
    'client_payload' => [
        'quelle' => $vonHand ? 'mvf-server-hand' : 'mvf-server-cron',
        'zeit'   => gmdate('c'),
    ],
], JSON_UNESCAPED_SLASHES);

$ch = curl_init("https://api.github.com/repos/{$REPO}/dispatches");
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => $rumpf,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT        => 30,
    CURLOPT_HTTPHEADER     => [
        // Ohne eigenen User-Agent antwortet GitHub mit 403.
        'User-Agent: mvf-knowledge-hubs-wecker',
        'Accept: application/vnd.github+json',
        'X-GitHub-Api-Version: 2022-11-28',
        'Authorization: Bearer ' . $TOKEN,
        'Content-Type: application/json',
    ],
]);
$antwort = curl_exec($ch);
$status  = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$curlFehler = curl_error($ch);
curl_close($ch);

// 204 ohne Rumpf ist der Erfolgsfall von repository_dispatch.
$gut = ($status === 204);
$meldung = $gut
    ? 'Weckruf abgesetzt.'
    : ($curlFehler !== '' ? "Netzfehler: {$curlFehler}" : "GitHub antwortete {$status}: " . substr((string)$antwort, 0, 300));

protokoll(($gut ? 'OK  ' : 'FEHL ') . $meldung);

if (!$gut) {
    fehler($meldung, 502);
}

if ($vonHand) {
    header('Content-Type: text/plain; charset=utf-8');
}
echo $meldung . "\n";
exit(0);


// ------------------------------------------------------------------ Werkzeug
function protokoll(string $zeile): void
{
    // Kurz halten: Der Hoster raeumt nichts weg, und eine Zeile am Tag ergibt
    // in zehn Jahren 3.650 Zeilen - das traegt eine Datei.
    global $PROTOKOLL;
    $datei = $PROTOKOLL ?: (__DIR__ . '/wecker.log.php');
    // Neu angelegt bekommt die Datei zuerst den Riegel - danach ist sie ueber
    // das Netz nicht mehr lesbar, egal wie sie heisst.
    $riegel = is_file($datei) ? '' : "<?php exit; ?>
";
    @file_put_contents(
        $datei,
        $riegel . date('Y-m-d H:i:s') . '  ' . $zeile . PHP_EOL,
        FILE_APPEND | LOCK_EX
    );
}

function fehler(string $meldung, int $code): void
{
    protokoll('FEHL ' . $meldung);
    if (PHP_SAPI !== 'cli') {
        http_response_code($code);
        header('Content-Type: text/plain; charset=utf-8');
    }
    fwrite(PHP_SAPI === 'cli' ? STDERR : STDOUT, $meldung . "\n");
    // Ein Exit-Code ungleich 0 laesst den Cron des Hosters die Stoerung melden.
    exit(1);
}
