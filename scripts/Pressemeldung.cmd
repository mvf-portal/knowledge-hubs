@echo off
rem Doppelklick-Weg fuer die Redaktion: Mail in Outlook offen oder markiert
rem lassen, diese Verknuepfung starten. Es entsteht ein WordPress-Entwurf und
rem eine Vorschau, die sich sofort im Browser oeffnet.
rem
rem Voraussetzung sind die drei Umgebungsvariablen KNOWLEDGEHUBS, WPUSER und
rem WPPASSWORT - einmal gesetzt, gelten sie fuer jeden neuen Start.
setlocal
set VORSCHAU=%TEMP%\pressemeldung-vorschau.html
py -3 "%~dp0pressemeldung.py" outlook --vorschau "%VORSCHAU%" %*
if exist "%VORSCHAU%" start "" "%VORSCHAU%"
echo.
pause
