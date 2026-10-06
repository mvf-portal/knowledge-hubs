# Richtet die Aufgabe "MVF Kloepfer" ein: Sie sieht stuendlich im
# Outlook-Ordner KloepfersInput nach. Kommt eine Lieferung an, erntet und
# sichtet sie die PDFs - und oeffnet danach die Entscheidungsseite im
# Browser. Liegt nichts Neues vor, passiert nichts.
#
#   powershell -ExecutionPolicy Bypass -File "scripts\Zeitplan-Kloepfer.ps1"
#
# Entfernen:
#   Unregister-ScheduledTask -TaskName "MVF Kloepfer" -Confirm:$false

$skript = "$env:USERPROFILE\Documents\Claude-Daten\knowledge-hubs\scripts\kloepfer.py"
if (-not (Test-Path $skript)) { throw "Skript nicht gefunden: $skript" }

# pyw.exe: kein schwarzes Fenster. Die Seite geht im Browser auf, das genuegt.
$pyw = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pyw.exe"

$aktion = New-ScheduledTaskAction -Execute $pyw `
    -Argument "-3 `"$skript`" ernten --zeigen" `
    -WorkingDirectory "$env:USERPROFILE\Documents\Claude-Daten\knowledge-hubs"

# Stuendlich zwischen 8 und 19 Uhr - Kloepfer schickt vormittags, meist
# montags, aber nicht auf die Minute.
$takt = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(8) `
    -RepetitionInterval (New-TimeSpan -Hours 1)

$optionen = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew

# Interactive: Nur so kommt die Aufgabe an das laufende Outlook und kann ein
# Browserfenster oeffnen.
$wer = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "MVF Kloepfer" -Action $aktion `
    -Trigger $takt -Settings $optionen -Principal $wer -Force `
    -Description "Erntet Kloepfers PDF-Lieferung, sichtet sie und oeffnet die Entscheidungsseite." |
    Select-Object TaskName, State

Write-Output ""
Write-Output "Eingerichtet. Probelauf von Hand:"
Write-Output "  Start-ScheduledTask -TaskName 'MVF Kloepfer'"
Write-Output "Seite jederzeit selbst oeffnen:"
Write-Output "  py -3 `"$skript`" entscheiden"
