# Neues WordPress-Anwendungspasswort fuer den Benutzer knowledge-hubs setzen.
#
# Muss in einem EIGENEN PowerShell-Fenster laufen: Read-Host fragt nichts ab,
# wenn das Skript ueber den Ausfuehren-Knopf im Chat gestartet wird - es
# bricht dann still ab und setzt nichts.
#
# Das Passwort wandert an zwei Stellen und nirgendwo sonst:
#   1. Benutzervariable WPPASSWORT  - dafuer laeuft die Aufgabe "MVF Pressemeldungen"
#   2. Repo-Secret WPPASSWORT       - dafuer laufen die Tagesnews in GitHub Actions
# Es wird nicht angezeigt, nicht protokolliert, nicht in eine Datei geschrieben.

$ErrorActionPreference = 'Stop'
$Benutzer = 'knowledge-hubs'
$Repo     = 'mvf-portal/knowledge-hubs'
$Seite    = 'https://www.monitor-versorgungsforschung.de'

Write-Host "Anwendungspasswort fuer $Benutzer eingeben (die Leerzeichen duerfen bleiben)."
$Geheim = Read-Host -AsSecureString 'Anwendungspasswort'
$Klar = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
          [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Geheim))
if (-not $Klar) { Write-Host 'Nichts eingegeben - abgebrochen.'; exit 1 }

# WordPress nimmt das Passwort mit oder ohne Leerzeichen; hier bleibt es, wie
# WordPress es anzeigt.
$Klar = $Klar.Trim()

# --- 1. Erst pruefen, dann speichern -------------------------------------
$Kopf = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($Benutzer + ':' + $Klar)))
try {
    $Ich = Invoke-RestMethod -Uri "$Seite/wp-json/wp/v2/users/me?context=edit" `
             -Headers @{ Authorization = "Basic $Kopf"
                         'User-Agent'  = 'MVF-Pressemeldung/1.0' }
} catch {
    Write-Host "WordPress nimmt das Passwort nicht an: $($_.Exception.Message)"
    Write-Host 'Nichts gespeichert.'
    exit 1
}
if (-not $Ich.capabilities.edit_posts) {
    Write-Host "Angemeldet als $($Ich.slug), aber ohne das Recht, Beitraege anzulegen."
    Write-Host 'Nichts gespeichert.'
    exit 1
}
Write-Host "Angemeldet als $($Ich.name) (Rolle: $($Ich.roles -join ', ')) - Passwort gilt."

# --- 2. Benutzervariable -------------------------------------------------
[Environment]::SetEnvironmentVariable('WPPASSWORT', $Klar, 'User')
[Environment]::SetEnvironmentVariable('WPUSER', $Benutzer, 'User')
$env:WPPASSWORT = $Klar
$env:WPUSER = $Benutzer
Write-Host 'Benutzervariable WPPASSWORT gesetzt.'

# --- 3. Repo-Secret ------------------------------------------------------
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $Klar | gh secret set WPPASSWORT -R $Repo
    if ($LASTEXITCODE -eq 0) { Write-Host "Repo-Secret WPPASSWORT in $Repo gesetzt." }
    else { Write-Host 'Repo-Secret NICHT gesetzt - bitte von Hand nachholen.' }
} else {
    Write-Host 'gh nicht gefunden - Repo-Secret bitte von Hand setzen.'
}

Remove-Variable Klar, Kopf, Geheim
Write-Host ''
Write-Host 'Fertig. Die Aufgabe "MVF Pressemeldungen" greift beim naechsten Lauf darauf zu.'
