<?php
/**
 * MUSTER - kopieren nach `wecker-zugang.php` und ausfuellen.
 *
 * Die echte Datei wird NICHT in dieses Repository aufgenommen (.gitignore) und
 * geht nur per FTP auf den Server.
 *
 * Warum eine .php und keine .json: MVF laeuft auf nginx, .htaccess wird dort
 * nicht gelesen. Eine wecker-zugang.json waere unter ihrer Adresse schlicht
 * abrufbar - mitsamt Token. Eine .php fuehrt der Server aus und gibt nichts
 * preis. Dieselbe Lehre wie beim Zaehler (daten/*.json.php).
 */
return [
    // Fein granuliertes GitHub-Token: Contents "Read and write",
    // NUR fuer mvf-portal/knowledge-hubs. Mehr braucht repository_dispatch nicht.
    'token' => 'github_pat_HIER_EINSETZEN',

    // Nur noetig, wenn das Skript ueber das Netz aufgerufen wird (kein Cron).
    // Frei gewaehlt, mindestens 24 Zufallszeichen. Bei reinem Cron-Betrieb
    // leer lassen - dann ist der Aufruf ueber das Netz gesperrt.
    'schluessel' => '',

    // Nur aendern, wenn das Repo oder der Ereignisname umbenannt wird; der
    // Name muss zu `types: [morgenlauf]` in dirigent.yml passen.
    'repo'     => 'mvf-portal/knowledge-hubs',
    'ereignis' => 'morgenlauf',
];
