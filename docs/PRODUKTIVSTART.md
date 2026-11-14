# JARVIS V2: Produktivstart unter Windows (Stand 2026-11-14)

Dieses Dokument beschreibt den **tatsächlich geprüften** Stand dieser Arbeitskopie. Es ersetzt weder die Windows-Abnahme (#186, `docs/WINDOWS_V2_ABNAHME_KURZ.md`) noch eine Release-Freigabe.
Geprüft wurde lokal unter Windows 11 mit Python 3.14.8 (`.venv`), ohne Netzwerk, ohne echtes LLM, ohne Mikrofon-/Lautsprecher-Hardware-Test.

## Start (PowerShell, ohne ExecutionPolicy-Änderung)
```powershell
cd C:\JARVIS-Test\V2                                    # Ordner außerhalb von OneDrive
.\.venv\Scripts\jarvis.exe doctor                       # nur lesend; Exit 0 = startbereit
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.example.toml --open    # NEXUS (Dashboard, Chat, Freigaben, Notaus), nur 127.0.0.1, Token pro Start
.\.venv\Scripts\jarvis.exe                              # alternativ: Textchat im Terminal (/help)
```
Geprüft: `doctor` meldet 0 Fehler; `jarvis-cc` startet, gibt die URL mit Token aus und antwortet ohne Token mit 401.
Optionale Funktionen (Websuche, Browser, Dateien/Office, Computer, Mikrofon) sind in `config/nexus.example.toml` auskommentiert und müssen **bewusst** eingeschaltet werden; Schlüssel nur als Umgebungsvariable.

## Was im Chat wie behandelt wird
| Eingabe | Verhalten |
|---|---|
| Fragen, Erklärungen, „Wie …“, „Anleitung …“ | normale Antwort (LLM; Standard ist `mock`), nie eine Dateiaktion |
| „Lies/Zeige/Liste …“ mit Pfad, „Erstelle den Ordner X“, „Erstelle datei.txt mit dem Inhalt: …“, Kopieren/Verschieben/Ersetzen | genau **ein** Schritt über Files-/Office-Agent -> ToolRegistry -> PermissionEngine (Änderungen fragen im Dialog) |
| „Ordner namens X“ / „folder called X“ | Ordner `X` |
| Ordner ohne Namen, Orte statt Pfad („auf dem Desktop“), Datei ohne Inhalt, mehrere Aktionen in einer Anfrage | **Rückfrage mit konkretem Grund**, nichts wird ausgeführt |
| „Recherchiere …“ (Imperativ) | Ziel `/goal`; mit URL wird die Seite gelesen, mit eingerichteter Websuche gesucht, sonst klare Erklärung, was fehlt |
Orte wie „Desktop“ oder „Dokumente“ werden **nie geraten**: der vollständige Pfad muss genannt werden (und liegt innerhalb der bestätigten Wurzeln, sonst lehnt die Berechtigungsprüfung ab).

## Fehlerbehandlung (neu in dieser Arbeitskopie)
* Eingabefehler der Datei-/Office-Werkzeuge (Datei fehlt, Ziel existiert, gesperrter/geschützter Pfad, zu groß, binär …) werden **nicht wiederholt** (`invalid_input`) und im Chat in Klartext erklärt (statt „step_failed … (2 Versuche)“).
* Bei abgelehnten Dateianfragen steht der konkrete Grund (z. B. „kein Ordnername genannt“) im Chat-Text.

## Bekannte Grenzen / Blocker (nicht behoben, nicht verschleiert)
1. **#186 echte interaktive Windows-Abnahme steht aus** (Release-Blocker laut `docs/RELEASE_READINESS_20261108.md`).
2. **Standard-LLM ist `mock`**: ohne konfigurierten Anbieter antwortet der Chat nur mit „[mock] Ich habe verstanden …“. Für echte Antworten `[llm]` konfigurieren (`docs/LLM_ROUTING.md`); echte Modelle sind hier ungetestet.
3. **Browserrecherche/Websuche** nie live getestet (Brave-Schlüssel, Netz, `playwright install` nötig). Echte-Browser-Tests laufen hier nur, wenn Playwright/Chromium installiert ist.
4. **Sprache** (Mikrofon/Lautsprecher) auf echter Hardware nicht geprüft; Texteingabe bleibt nutzbar.
5. Einige Tests der geprüften Gruppen werden hier **übersprungen** (u. a. `node` nicht installiert -> NEXUS-DOM-Tests; Symlink-Rechte des Kontos). Übersprungen = nicht bewiesen.
6. Tests teilen sich z. T. `data\journal.db` (Test-Isolation): ein Test wurde auf einen eigenen Pfad umgestellt; weitere Tests ohne `JARVIS_JOURNAL_PATH` können bei Parallel-/Wiederholungsläufen kollidieren.
7. „Ordner und Datei in einer Anfrage“ wird bewusst abgelehnt (eine Aktion pro Anfrage); Computersteuerung („Öffne Notepad“) läuft nicht über freien Chattext, sondern über die expliziten Befehle.

## Nächste sinnvolle Schritte
1. Abnahme #186 mit `scripts\abnahme\run-abnahme.ps1` (zuerst Trockenlauf) auf dem Owner-PC.
2. Echten LLM-Anbieter konfigurieren und Chat-/Planungsqualität prüfen.
3. Optional Websuche einrichten (`docs/WINDOWS_QUICKSTART.md` §5) und einen echten Rechercheauftrag testen.
4. CI-Windows-Lauf (`tests-windows`) für die Änderungen dieser Arbeitskopie abwarten, danach Review/Commit durch den Owner.
