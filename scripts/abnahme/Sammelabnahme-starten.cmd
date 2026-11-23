@echo off
rem Doppelklick-Start der Sammelabnahme #186 (kein Tippen noetig). ExecutionPolicy Bypass gilt nur fuer diesen einen Prozess; die dauerhafte Richtlinie bleibt unveraendert.
rem Normale (nicht erhoehte) Sitzung verwenden. Ohne Wirkung ausprobieren: powershell -File scripts\abnahme\sammelabnahme.ps1 (Trockenlauf).
cd /d "%~dp0\..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\abnahme\sammelabnahme.ps1 -Execute
pause
