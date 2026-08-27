# Richtet die Aufgabe "MVF Laufwache" ein: Taeglich um 09:00 sieht sie nach, ob
# die naechtlichen Laeufe der zwoelf Hubs und der Sammelbericht wirklich
# gelaufen sind, stoesst fehlende an und meldet sich per Outlook.
#
# Warum ausserhalb von GitHub: Am 27.08.2026 hat GitHub die geplanten Laeufe
# ALLER dreizehn Repos verschluckt. Ein ausgebliebener Lauf meldet nichts - kein
# Fehler, keine Mail, nur Stille. Innerhalb von GitHub greift bereits ein
# zweiter Zeitplan um 05:30 UTC; diese Aufgabe ist die Stufe darunter.
#
# Einmal ausfuehren, dann laeuft es:
#   powershell -ExecutionPolicy Bypass -File "scripts\Zeitplan-Laufwache.ps1"
#
# Entfernen laesst sich das jederzeit mit:
#   Unregister-ScheduledTask -TaskName "MVF Laufwache" -Confirm:$false

$skript = "$env:USERPROFILE\Documents\knowledge-hubs\scripts\laufwache.py"
if (-not (Test-Path $skript)) { throw "Skript nicht gefunden: $skript" }

# pyw.exe startet Python ohne Fenster - wie bei den Pressemeldungen. Das
# Protokoll schreibt das Skript selbst nach knowledge-hubs\laufwache.log.
$pyw = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pyw.exe"
if (-not (Test-Path $pyw)) { throw "pyw.exe nicht gefunden: $pyw" }

$aktion = New-ScheduledTaskAction -Execute $pyw `
    -Argument "-3 `"$skript`"" `
    -WorkingDirectory "$env:USERPROFILE\Documents\knowledge-hubs"

# 09:00 Ortszeit: eine Stunde vor dem Versand um 10:00. Ein nachgeholter Lauf
# braucht ein bis zwei Minuten, es bleibt also Luft fuer einen Blick von Hand.
$takt = New-ScheduledTaskTrigger -Daily -At 9:00

# StartWhenAvailable holt die Aufgabe nach, wenn der Rechner um 09:00 aus war.
$optionen = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

# Interactive: nur so kommt die Aufgabe an das laufende Outlook heran - und an
# die gh-Anmeldung dieses Benutzers.
$wer = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "MVF Laufwache" -Action $aktion `
    -Trigger $takt -Settings $optionen -Principal $wer -Force `
    -Description "Prueft taeglich um 09:00, ob die naechtlichen Studienlaeufe der zwoelf Knowledge-Hubs und der Sammelbericht gelaufen sind; stoesst fehlende an und meldet sich per Outlook." |
    Select-Object TaskName, State

Write-Output ""
Write-Output "Von Hand pruefen, ohne etwas anzustossen:"
Write-Output "  py scripts\laufwache.py --trocken --ohne-mail"
