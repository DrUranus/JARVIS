# JARVIS Windows V1: Abnahmeleitfaden für den echten Windows-PC (Ziel 21.11.2026)

**Status dieses Dokuments:** Vorlage und Anleitung. Es enthält **keine Ergebnisse**. Eine Zeile gilt erst als bestanden, wenn du sie auf dem echten PC ausgeführt und einen Beleg abgelegt hast. Automatische CI-Läufe (Windows-Runner ohne Mensch) sind ein anderer Nachweis und ersetzen diese Abnahme nie (Issue #186).

Nachweisstufen: **CI-Linux** · **CI-Windows** (Runner, kein Mensch am Desktop) · **PC** (diese Abnahme, du am echten Windows-PC).
Ergebnis je Zeile: **PASS** / **FAIL** / **PENDING** (noch nicht geprüft) / **N/A** (bewusst nicht geprüft, mit Begründung).

## 0. Vorbereitung (einmalig)
Trage oben in Issue #186 ein: Datum, Commit-SHA des Release-Stands, Windows-Version (`winver`), Python-Version, Monitoranzahl.

```powershell
cd C:\dev\JARVIS                                      # Ordner AUSSERHALB von OneDrive
git rev-parse HEAD                                    # SHA notieren; muss dem Release-Commit auf main entsprechen
git status --short                                    # erwartet: leer
py -3 --version                                       # erwartet: Python 3.11 oder neuer
(Get-ComputerInfo).OsName, (Get-ComputerInfo).OsVersion
```
Belege (Screenshots/Textdateien) in einen Ordner `abnahme\` legen, Dateiname = Schritt, z. B. `abnahme\04-freigabedialog.png`, und in #186 anhängen. **Keine Schlüssel in Belege kopieren.**

## 1. Installation und Start
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe ci\fresh-install\smoke.py 2>&1 | Tee-Object abnahme\01-smoke.txt
.\.venv\Scripts\jarvis.exe doctor 2>&1 | Tee-Object abnahme\01-doctor.txt
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.example.toml --open
```
Erwartet: Der Rauchtest endet mit `Ergebnis: BESTANDEN`; `jarvis doctor` endet mit "JARVIS ist startbereit" (Exit-Code 0 prüfen: `$LASTEXITCODE`); `jarvis-cc` gibt `http://127.0.0.1:<Port>/?t=<Token>` aus, der Browser zeigt NEXUS mit "verbunden". Keine Änderung der ExecutionPolicy nötig (es wird nie `Activate.ps1` ausgeführt).

| # | Prüfung | Erwartung | PC-Ergebnis | Beleg |
|---|---|---|---|---|
| 1.1 | Rauchtest | `BESTANDEN` | PENDING | 01-smoke.txt |
| 1.2 | `jarvis doctor` | Exit-Code 0 | PENDING | 01-doctor.txt |
| 1.3 | NEXUS im Browser | "verbunden", Zustand "bereit" | PENDING | Screenshot |
| 1.4 | Beenden mit Strg+C | Port geschlossen: `Get-NetTCPConnection -State Listen \| ? LocalAddress -eq 127.0.0.1` zeigt den Port nicht mehr | PENDING | Text |

## 2. Python 3.14 und vorhandene virtuelle Umgebung
Nur wenn du Python 3.14 nutzt (sonst "N/A: 3.13"). Python 3.14 ist unter Linux in der Vollsuite grün, unter Windows nur teilweise abgesichert.
```powershell
py -3.14 -m venv .venv314
.\.venv314\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv314\Scripts\python.exe ci\fresh-install\smoke.py
.\.venv314\Scripts\python.exe -m pytest -q -rfEs tests\test_voice_stability.py tests\test_journal_hard_kill.py
```
Eine **vorhandene** venv: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --upgrade` und danach `jarvis doctor`. Erwartet: keine Fehler; Abweichungen unter 3.14 als FAIL mit Log eintragen.

| # | Prüfung | Erwartung | PC-Ergebnis |
|---|---|---|---|
| 2.1 | Rauchtest unter 3.14 | `BESTANDEN` | PENDING |
| 2.2 | Ausgewählte Tests unter 3.14 | grün | PENDING |
| 2.3 | Update einer vorhandenen venv | `jarvis doctor` weiter Exit 0 | PENDING |

## 3. OneDrive-Projektpfad und Git-Lock-Diagnose
```powershell
.\.venv\Scripts\jarvis.exe doctor | Select-String -Pattern "OneDrive"
.\.venv\Scripts\python.exe -m jarvis.interface.gitlocks        # nur lesend
```
Erwartet in einem Ordner unter OneDrive: `jarvis doctor` warnt vor OneDrive; ausserhalb: "kein OneDrive-Ordner erkannt". Bei `index.lock`-Fehler zeigt `gitlocks` Sperrdatei und laufende Git-Prozesse; **es löscht nichts von selbst.**

| # | Prüfung | Erwartung | PC-Ergebnis |
|---|---|---|---|
| 3.1 | Doctor ausserhalb OneDrive | "kein OneDrive-Ordner erkannt" | PENDING |
| 3.2 | Doctor innerhalb OneDrive (Kopie zum Test) | OneDrive-Warnung | PENDING |
| 3.3 | `gitlocks` | liest nur, löscht nichts | PENDING |

## 4. NEXUS Premium V2: Kugel und Dashboard
Im Browser: Orb-Ansicht, "Dashboard"-Umschalter, Effekte "reduziert" und "aus".
Erwartet: Kugel läuft flüssig, Zustandsfarben wechseln (bereit grün, Verarbeitung violett), Dashboard zeigt Aufgaben, Agenten, Ergebnisse, Systemstatus ("unbekannt" statt erfundener Werte). Windows-Einstellung "Animationen reduzieren" führt zum 2D-Fallback ohne Fehler. Im Experten-Modus "Einrichtung und Diagnose" -> "Prüfen": zeigt Python, Komponenten, Schlüssel nur als "gesetzt"/"nicht gesetzt".

| # | Prüfung | PC-Ergebnis | Beleg |
|---|---|---|---|
| 4.1 | Orb/Dashboard umschalten, Kugel flüssig | PENDING | |
| 4.2 | Effekte reduziert/aus, Windows-Animationen aus | PENDING | |
| 4.3 | Setup-Panel zeigt keine Schlüsselwerte | PENDING | |

## 5. Overlay, Fokus, Always-on-Top
```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ui]"       # pywebview; WebView2-Laufzeit nötig (doctor prüft)
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.example.toml --overlay --overlay-on-top
```
Erwartet: Fenster ca. 140x140, verschiebbar, über anderen Fenstern, NOTAUS erreichbar, Klick auf den Kern öffnet das Hauptfenster im Browser. Prüfe zusätzlich Fokusverlust (anderes Fenster aktivieren) und, falls vorhanden, einen zweiten Monitor.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 5.1 | Größe, verschiebbar, immer im Vordergrund | PENDING |
| 5.2 | NOTAUS im Overlay | PENDING |
| 5.3 | Klick öffnet das Hauptfenster | PENDING |
| 5.4 | Zweiter Monitor / Fokus | PENDING |

## 6. Mikrofon, Spracherkennung, Sprachausgabe
Nur mit Hardware. Konfiguration: `".[voice]"` installieren; `[voice] stt_provider`/`tts_provider` je nach Wunsch (siehe `docs/WINDOWS_V1_KONFIGURATION.md`).
```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
.\.venv\Scripts\jarvis.exe doctor | Select-String -Pattern "sounddevice|numpy"
```
Erwartet: Doctor meldet Mikrofon-Pakete verfügbar; Sprachmodus startet, ein gesprochener Satz wird erkannt und beantwortet; Notaus beendet den Sprachmodus; Mikrofon abziehen -> verständliche Meldung, kein Absturz, Texteingabe bleibt nutzbar.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 6.1 | Satz erkannt, Antwort gesprochen | PENDING |
| 6.2 | Unterbrechen während der Ausgabe | PENDING |
| 6.3 | Mikrofon trennen | PENDING |
| 6.4 | Notaus beendet den Sprachmodus | PENDING |

## 7. Echte LLM-Verbindung
Standard ist `mock`. Schlüssel **nur** als Umgebungsvariable, nie in Dateien:
```powershell
$env:JARVIS_LLM_PROVIDER = "openai"          # oder "anthropic"
$env:JARVIS_LLM_MODEL    = "<Modellname>"
$env:OPENAI_API_KEY      = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host "OpenAI-Schluessel" -AsSecureString)))   # Eingabe verdeckt, Windows PowerShell 5.1 und 7
.\.venv\Scripts\jarvis.exe doctor | Select-String -Pattern "LLM|API_KEY"
```
Erwartet: Doctor zeigt den Anbieter und den Schlüssel nur als "gesetzt". Im Chat eine einfache Frage stellen; Antwort kommt vom Modell. Mit falschem Schlüssel: verständliche Fehlermeldung, kein Schlüssel im Text/Log.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 7.1 | Doctor zeigt Anbieter, Schlüssel nur "gesetzt" | PENDING |
| 7.2 | Antwort vom echten Modell | PENDING |
| 7.3 | Falscher Schlüssel: Fehler ohne Schlüssel im Text | PENDING |

## 8. Live-Brave-Recherche
```powershell
$env:JARVIS_RESEARCH_SEARCH_ENABLED = "true"
$env:BRAVE_SEARCH_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host "Brave-Schluessel" -AsSecureString)))
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
.\.venv\Scripts\python.exe -m playwright install chromium
```
Zusätzlich in der TOML-Kopie `[research] enabled = true` und `[browser] enabled = true` (siehe Konfigurationsanleitung). Chat: `Recherchiere die Vorteile von Python`.
Erwartet: Jede Seite fragt im Freigabedialog nach (Ablehnen ist Standard); Antwort mit Quellen; ohne Schlüssel/Einstellungen eine verständliche BLOCKED-Meldung. Es gehen nur Suchtext, Trefferzahl und dein Schlüssel an `api.search.brave.com`.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 8.1 | Ohne Einrichtung: BLOCKED-Meldung mit Hinweis | PENDING |
| 8.2 | Mit Einrichtung: Antwort mit Quellen | PENDING |
| 8.3 | Ablehnen einer Seite: nichts wird gelesen | PENDING |

## 9. Datei- und Office-Aufträge
Legt zuerst eine Testdatei im Arbeitsbereich an (`workspace\`):
```powershell
New-Item -ItemType Directory -Force workspace | Out-Null
"Hallo aus der Testdatei" | Set-Content workspace\notiz.txt -Encoding utf8
```
Chat-Aufträge: `Lies die Datei notiz.txt` (erwartet: Inhalt als Daten, keine Rückfrage) · `Erstelle den Ordner Archiv` (Freigabedialog; **Ablehnen** legt nichts an; **Zustimmen** legt an) · eine Tabelle/ein Dokument erstellen und zurücklesen.
Erwartet: Nichts wird gelöscht, bestehende Office-Dateien werden nie verändert, `.env` und Schlüsseldateien werden nicht gelesen.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 9.1 | Lesen ohne Rückfrage | PENDING |
| 9.2 | Anlegen: Ablehnen = nichts passiert | PENDING |
| 9.3 | Anlegen: Zustimmen = Ordner existiert (`Test-Path workspace\Archiv`) | PENDING |
| 9.4 | Office erstellen und zurücklesen | PENDING |

## 10. Computersteuerung mit harmlosen Aktionen
Nur bewusst einschalten (`[computer] enabled = true`, Kopie der Beispielkonfiguration). Nutze ausschliesslich Notepad/Taschenrechner:
```powershell
Start-Process notepad
```
Erwartet: Jede Eingabe/Fensteraktion fragt nach; Ablehnen führt nichts aus; Passwortfelder werden nur gelesen; Notaus stoppt sofort. Keine Aktionen in Banking-, Mail- oder produktiven Fenstern ausführen.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 10.1 | Text in Notepad schreiben nur nach Freigabe | PENDING |
| 10.2 | Ablehnen: nichts geschieht | PENDING |
| 10.3 | Notaus während einer Aktion | PENDING |

## 11. Agentenkoordination und Aufgabenstatus
Chat: ein mehrstufiger Auftrag (z. B. erst Datei lesen, dann Ordner anlegen) und ein bewusst fehlschlagender (`Lies die Datei gibtsnicht.txt`).
Erwartet: Dashboard zeigt Aufgaben mit Statusverlauf; beim Fehlschlag die Zeile "Fehler" mit Grund; Ergebnis mit "Zur Aufgabe"-Knopf; Abbrechen eines laufenden Auftrags liefert eine echte Antwort.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 11.1 | Statusverlauf sichtbar | PENDING |
| 11.2 | Fehlertext bei Fehlschlag | PENDING |
| 11.3 | Abbrechen | PENDING |

## 12. Memory, Journal und Resume
```powershell
# Ziel starten, dann das Fenster von jarvis-cc hart schliessen (Task-Manager: Prozess beenden)
Get-Process | Where-Object { $_.Name -like "*jarvis*" -or $_.Name -eq "python" }
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.example.toml --open
```
Chat nach dem Neustart: `/resume` (Auflisten). Erwartet: Auflisten startet **nichts**; Fortsetzen nur mit ausdrücklichem `/resume <id>`; ein offener Schritt mit Wirkung fragt neu; Ablehnen startet nichts. Journal-Datei (`data\journal.db`) enthält keine Schlüssel.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 12.1 | Auflisten startet nichts | PENDING |
| 12.2 | Fortsetzen nur auf Befehl, mit neuer Freigabe | PENDING |
| 12.3 | Erinnerung/Gedächtnis überlebt Neustart | PENDING |

## 13. Freigaben, Ablehnung, Timeout, Not-Aus
Erwartet: Freigabedialog zeigt alle Felder; Escape/Ablehnen ist Standard; ohne Antwort innerhalb von `confirmation_timeout_seconds` (Beispielkonfiguration: 120 s) gilt die Rückfrage als abgelehnt; Verbindung trennen (jarvis-cc beenden, Seite offen lassen) -> "GETRENNT", Dialog gilt als abgelehnt; NOTAUS im Orb, im Dashboard und bei offenem Dialog wirkt sofort, Banner rot, neue Eingaben abgelehnt, Aufhebung nur über Rückfrage.

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 13.1 | Ablehnen ist Standard | PENDING |
| 13.2 | Timeout = abgelehnt | PENDING |
| 13.3 | Verbindungsverlust = abgelehnt | PENDING |
| 13.4 | NOTAUS in allen drei Ansichten | PENDING |

## 14. Stabilität bei Neustart, Unterbrechung, Fehlern
Zehn Zyklen: starten, Auftrag geben, hart beenden, neu starten. Dazu Netzwerk trennen während einer Recherche, Mikrofon trennen, Datei sperren (Datei in Excel geöffnet lassen und lesen). Erwartet: keine Abstürze mit Traceback im Browser/Terminal, verständliche Meldungen, keine hängenden Prozesse (`Get-Process python`).

| # | Prüfung | PC-Ergebnis |
|---|---|---|
| 14.1 | 10 Start/Stopp-Zyklen ohne hängende Prozesse | PENDING |
| 14.2 | Netz weg während Recherche | PENDING |
| 14.3 | Gesperrte Datei | PENDING |

## 15. Logs sichern (ohne Geheimnisse)
Siehe `docs/WINDOWS_V1_KONFIGURATION.md`, Abschnitt "Log-Erfassung". Vor dem Anhängen an #186 prüfen, dass keine Schlüssel enthalten sind.

## 16. Go/No-Go
- **Go:** Eintrittskriterien erfüllt (Release-Commit festgelegt, Pflicht-CI auf dem Release-Commit grün), Schritte 1, 3, 4, 9, 11, 12, 13 sind **PASS**, und kein Sicherheitsverhalten (Freigaben, Ablehnen, Timeout, Not-Aus) weicht ab.
- **No-Go:** jeder FAIL in 9.2, 12.2, 13.x, oder fehlende Belege.
- Schritte 2, 5, 6, 7, 8, 10, 14 dürfen nur dann "N/A" bleiben, wenn der Besitzer das ausdrücklich entscheidet und es in der Release-Notiz steht.
