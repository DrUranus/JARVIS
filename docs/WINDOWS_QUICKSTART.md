# JARVIS NEXUS: Windows-Schnellstart (ohne ExecutionPolicy-Änderung)

Stand: 2026-11-08. Alle Schritte funktionieren in einer normalen PowerShell **ohne** `Set-ExecutionPolicy`: Es wird nie `Activate.ps1` ausgeführt, sondern das Python der virtuellen Umgebung direkt aufgerufen.
Geprüft: die komplette Testsuite lief unter Linux mit Python 3.11 und 3.14 und in der Windows-CI mit 3.13 grün (Stand 2026-11-08). **Die Installation auf einem echten Windows-PC ist nicht von mir geprüft**; Windows-CI testet die Software, nicht diese Anleitung.

## 1. Ordner wählen (wichtig)
Lege JARVIS **außerhalb von OneDrive** ab, z. B. `C:\dev\JARVIS`. OneDrive kann Dateien beim Schreiben sperren (SQLite-Gedächtnis/Journal, Git-Fehler `index.lock`). `jarvis doctor` warnt, wenn ein Pfad in OneDrive liegt.

## 2. Installation (PowerShell)
```powershell
cd C:\dev\JARVIS
py -3 -m venv .venv                                   # Python 3.11 oder neuer von python.org (inkl. tkinter); 3.13 und 3.14 sind getestet
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```
Optional (nur wenn gebraucht): `".[ui]"` (Mini-Overlay, pywebview), `".[voice]"` (Mikrofon/Lautsprecher), `".[browser]"` und danach `.\.venv\Scripts\python.exe -m playwright install chromium` (Browser-Agent und Webrecherche).

## 3. Prüfen
```powershell
.\.venv\Scripts\jarvis.exe doctor
```
Der Doctor liest nur (keine Änderung, Schlüssel nur als „gesetzt/nicht gesetzt“) und meldet Python, tkinter, optionale Pakete, Konfiguration, Subsysteme, Sicherheitsmodus, WebView2 und OneDrive-Pfade. Exit-Code 0 = startbereit.

## 4. Start von NEXUS
```powershell
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.example.toml --open
```
Das gibt eine URL `http://127.0.0.1:<Port>/?t=<Token>` aus und öffnet sie im Browser. Beenden mit Strg+C. Mit `--overlay` (und installiertem `".[ui]"`) startet zusätzlich das Mini-Overlay. Die Beispielkonfiguration ändert keine Sicherheitseinstellung: Aktionen mit Wirkung fragen im NEXUS-Dialog (Ablehnen ist Standard), der NOTAUS ist immer erreichbar.

## 5. Optionale Funktionen (nur bewusst einschalten)
Websuche (Brave), Browser, Computer-/Datei-/Coding-Werkzeuge und Mikrofon stehen in `config/nexus.example.toml` auskommentiert. Schlüssel nur als Umgebungsvariable setzen (`$env:BRAVE_SEARCH_API_KEY = "…"` gilt nur für diese PowerShell-Sitzung).

## 6. Fehlerbehebung
| Symptom | Ursache / Lösung |
|---|---|
| `Startfehler: Das Control Center ist aus …` | Beispielkonfiguration mit `-c config\nexus.example.toml` übergeben (schaltet Control Center, Assistent, Agenten ein). |
| `pip` meldet `Python 3.x ist zu alt` | Python ≥ 3.11 von python.org installieren; `py -3 --version` prüfen. |
| `jarvis-cc` wird nicht gefunden | Direkt `.\.venv\Scripts\jarvis-cc.exe` aufrufen (kein Aktivieren nötig). |
| „Das Skript … kann nicht ausgeführt werden“ (ExecutionPolicy) | Nicht `Activate.ps1` benutzen; die Befehle oben rufen die `.exe` direkt auf. Nichts an der Richtlinie ändern. |
| Git: `Unable to create '.git/index.lock': File exists` | Erst `python -m jarvis.interface.gitlocks` (nur lesend). Es zeigt Sperren, laufende Git-Prozesse und ob eine Sperre verwaist aussieht. Entfernen nur mit `--remove --yes`, und nur wenn kein Git-Prozess läuft und die Sperre mindestens 2 Minuten alt ist. Dauerhaft: Ordner außerhalb von OneDrive. |
| Seite lädt nicht / `GETRENNT` | Der Server läuft nur lokal und nur solange `jarvis-cc` läuft; die URL enthält ein Einmal-Token pro Start. Neu starten und die neue URL öffnen. |
| Kein Ton / kein Mikrofon | `".[voice]"` installieren; ohne Hardware meldet NEXUS „Sprachmodus nicht verfügbar“ und die Texteingabe bleibt nutzbar. |
| Websuche: „web search unavailable“ | `[research] enabled`, `search_enabled`, `[browser] enabled` und `BRAVE_SEARCH_API_KEY` setzen (siehe README). |
