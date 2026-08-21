# Richtet die Aufgabe "MVF Pressemeldungen" ein: Alle 15 Minuten sieht sie im
# Outlook-Posteingang nach Pressemitteilungen und legt daraus WordPress-
# Entwuerfe an. Einmal ausfuehren, dann laeuft es.
#
#   powershell -ExecutionPolicy Bypass -File "scripts\Zeitplan-einrichten.ps1"
#
# Entfernen laesst sich das jederzeit mit:
#   Unregister-ScheduledTask -TaskName "MVF Pressemeldungen" -Confirm:$false

$skript = "$env:USERPROFILE\Documents\knowledge-hubs\scripts\pressemeldung.py"
if (-not (Test-Path $skript)) { throw "Skript nicht gefunden: $skript" }

# pyw.exe statt py.exe: startet Python ohne Fenster, damit nicht alle 15
# Minuten ein schwarzer Kasten aufblitzt. Das Protokoll schreibt das Skript
# selbst nach OneDrive\Pressemeldungen\pressemeldung.log.
$pyw = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pyw.exe"

$aktion = New-ScheduledTaskAction -Execute $pyw `
    -Argument "-3 `"$skript`" postfach --hoechstens 5" `
    -WorkingDirectory "$env:USERPROFILE\Documents\knowledge-hubs"

# Alle 15 Minuten, dazu einmal bei jeder Anmeldung.
$takt = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$start = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$optionen = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew

# Interactive: Nur so kommt die Aufgabe an das laufende Outlook heran.
$wer = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "MVF Pressemeldungen" -Action $aktion `
    -Trigger $takt, $start -Settings $optionen -Principal $wer -Force `
    -Description "Prueft alle 15 Minuten den Outlook-Posteingang auf Pressemitteilungen und legt WordPress-Entwuerfe an." |
    Select-Object TaskName, State

Write-Output ""
Write-Output "Eingerichtet. Ein Probelauf von Hand:"
Write-Output "  Start-ScheduledTask -TaskName 'MVF Pressemeldungen'"
