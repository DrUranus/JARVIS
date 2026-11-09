# JARVIS Windows V1: Konfiguration, Diagnose, Logs, Wiederherstellung

Gilt für den Release-Freeze (Ziel 21.11.2026). Installation und Start: `docs/WINDOWS_QUICKSTART.md`. Abnahme auf dem echten PC: `docs/WINDOWS_V1_ABNAHME.md`. Hier steht **nichts, was nicht im Code vorhanden ist**; Ergebnisse stehen nur in `docs/RELEASE_READINESS_20261108.md`.

## 1. Grundprinzip
- Einstellungen kommen aus `config\jarvis.toml` (Standard), einer eigenen TOML-Datei (`-c datei.toml`) und Umgebungsvariablen. Umgebungsvariablen haben die Form `JARVIS_<ABSCHNITT>_<SCHLÜSSEL>` (z. B. `JARVIS_LLM_PROVIDER`, `JARVIS_RESEARCH_SEARCH_ENABLED`).
- Alles mit Wirkung ist standardmäßig **aus**. `config\nexus.example.toml` schaltet nur Control Center, Assistent, Agenten, Ziele, Journal und das Datei-Werkzeug ein; es ändert keine Sicherheitseinstellung.
- **Schlüssel stehen nie in Dateien, im Chat, in Logs oder in Issues.** Nur als Umgebungsvariable der laufenden PowerShell-Sitzung.

## 2. Benötigte Schlüssel (ohne Werte)
| Zweck | Umgebungsvariable | Pflicht? | Hinweis |
|---|---|---|---|
| OpenAI-Modell | `OPENAI_API_KEY` | nur mit `llm.provider = "openai"` | zugleich Standard für OpenAI-Sprache, falls kein eigener Sprachschlüssel gesetzt ist |
| Anthropic-Modell | `ANTHROPIC_API_KEY` | nur mit `llm.provider = "anthropic"` | |
| OpenAI-kompatibler Anbieter | `JARVIS_LLM_API_KEY` | nur mit `openai_compatible` | in einer Datei **verboten** |
| Websuche | `BRAVE_SEARCH_API_KEY` | nur mit eingeschalteter Suche | Standard: Suche aus |
| Sprache (OpenAI) | `JARVIS_VOICE_API_KEY` | nur mit OpenAI-STT/TTS | |

Schlüssel in der aktuellen PowerShell-Sitzung setzen, Eingabe verdeckt (Windows PowerShell 5.1 und 7):
```powershell
$env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host "Schluessel" -AsSecureString)))
```
Der Schlüssel gilt nur für dieses Fenster. Dauerhaft setzen ist möglich (Windows-Benutzerumgebungsvariablen), aber bewusst nicht Teil dieser Anleitung. `jarvis doctor` zeigt Schlüssel nur als "gesetzt/nicht gesetzt".

## 3. Echtes LLM
Standard ist `mock` (keine Netzwerkverbindung). Umschalten:
```powershell
$env:JARVIS_LLM_PROVIDER = "openai"        # openai | anthropic | openai_compatible
$env:JARVIS_LLM_MODEL    = "<Modellname laut Anbieter>"
.\.venv\Scripts\jarvis.exe doctor
```
Erwartet: Doctor nennt den Anbieter, den Schlüssel als "gesetzt". Mit einem echten Modell sind zusätzlich `goals.llm_planning` und `goals.replanning` möglich (in der TOML-Kopie, Standard aus). Ohne LLM planen nur URL-, Workspace-, Datei-, Bildschirm- und Suchaufträge.

## 4. Brave-Suche und Recherche
Drei Dinge müssen zusammenkommen: Browser, Recherche, Suche.
```toml
# Kopie von config\nexus.example.toml, z. B. config\meine.toml
[browser]
enabled = true            # pip install -e ".[browser]" und: python -m playwright install chromium
[research]
enabled = true
```
```powershell
$env:JARVIS_RESEARCH_SEARCH_ENABLED = "true"
$env:BRAVE_SEARCH_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host "Brave-Schluessel" -AsSecureString)))
.\.venv\Scripts\jarvis-cc.exe -c config\meine.toml --open
```
Was an Brave geht: nur der Suchtext (Geheimnisse vorher geschwärzt, höchstens 300 Zeichen), die Trefferzahl, dein Schlüssel als Header und technisch deine IP-Adresse, per HTTPS an `api.search.brave.com`. Keine Seiteninhalte, Dateien oder Erinnerungen. Jede gelesene Seite läuft über den Browser und fragt im Freigabedialog nach. Fehlt etwas, meldet NEXUS BLOCKED mit Was fehlt / Warum / Was tun.

## 5. Fehlerdiagnose
| Symptom | Ursache und Schritt |
|---|---|
| `jarvis doctor` Exit-Code 1 | Zeilen mit FEHLER lesen; HINWEIS-Zeilen sind optional. Der Doctor ändert nichts. |
| Python 3.14: Paket lässt sich nicht installieren | Auf Python 3.13 ausweichen (`py -3.13 -m venv .venv`). Python 3.14 ist unter Linux in der Vollsuite getestet, unter Windows nur teilweise; Auffälligkeiten mit Log melden (Abschnitt 6). |
| Tk-GUI startet nicht (`tk.tcl`/`init.tcl`) | tkinter fehlt oder Umgebungsproblem; Python von python.org verwenden. `jarvis-gui` ist unabhängig von NEXUS. |
| OneDrive-Warnung im Doctor | Projekt nach `C:\dev\JARVIS` verschieben. SQLite (Gedächtnis, Journal) und Git können in OneDrive-Ordnern blockieren. |
| Git: `index.lock` | `.\.venv\Scripts\python.exe -m jarvis.interface.gitlocks` (nur lesend). Löschen nur selbst und nur, wenn kein Git-Prozess läuft. |
| NEXUS zeigt GETRENNT | `jarvis-cc` läuft nicht mehr oder URL/Token ist alt. Neu starten, die neue URL öffnen. |
| Port belegt | `Get-NetTCPConnection -State Listen \| Where-Object LocalAddress -eq 127.0.0.1`; alten Prozess beenden. |
| Overlay startet nicht | `".[ui]"` installieren, WebView2-Laufzeit prüfen (`jarvis doctor`). |
| Kein Mikrofon/Ton | `".[voice]"` installieren; ohne Gerät meldet NEXUS "Sprachmodus nicht verfügbar", Texteingabe bleibt nutzbar. |
| Suche "unavailable" | Abschnitt 4: Browser, Recherche, Suche **und** Schlüssel prüfen. |

## 6. Log-Erfassung ohne Geheimnisse
Das Programmlog liegt standardmäßig in `logs\jarvis.log` (`log_dir`), das Audit in `logs\audit.jsonl`, das Journal in `data\journal.db` (Beispielkonfiguration). Das Audit und die Logs sind für Geheimnisse geschwärzt; **prüfe die Sammlung trotzdem, bevor du sie weitergibst**.
```powershell
New-Item -ItemType Directory -Force abnahme | Out-Null
$out = "abnahme\diagnose.txt"
"== Zeit: $(Get-Date -Format s)"  | Set-Content $out
"== Commit: $(git rev-parse HEAD)" | Add-Content $out
"== Python: $(.\.venv\Scripts\python.exe --version)" | Add-Content $out
.\.venv\Scripts\jarvis.exe doctor *>&1 | Add-Content $out
Get-ChildItem logs -Filter jarvis.log -ErrorAction SilentlyContinue | ForEach-Object {
  "== $($_.Name) (letzte 200 Zeilen)" | Add-Content $out
  Get-Content $_.FullName -Tail 200 | Add-Content $out
}
# Schluesselmuster zusaetzlich schwaerzen (Sicherheitsnetz, kein Ersatz fuer die Sichtpruefung)
(Get-Content $out) `
  -replace 'sk-[A-Za-z0-9_\-]{10,}', 'sk-***' `
  -replace '(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+', '$1=***' `
  -replace '(?i)bearer\s+\S+', 'Bearer ***' | Set-Content $out
Select-String -Path $out -Pattern 'sk-|api_key|Bearer ' | Select-Object -First 5   # erwartet: nur '***'
```
Anhängen an Issue #186 erst, wenn die letzte Zeile nur geschwärzte Treffer oder nichts zeigt.

## 7. Wiederherstellung und Neustart
| Situation | Vorgehen |
|---|---|
| NEXUS hängt | Strg+C in der Konsole von `jarvis-cc`; wenn nötig Prozess im Task-Manager beenden; neu starten (neue URL, neues Token). |
| Not-Aus ausgelöst | Aufhebung nur über die Rückfrage in NEXUS. Der Zustand liegt nur im laufenden Prozess (es gibt keine Speicherung auf Platte); ein Neustart von `jarvis-cc` beginnt wieder im Normalzustand, die Sicherheitsabfragen gelten unverändert. Danach Sicherheitsmodus mit `jarvis doctor` prüfen. |
| Absturz mitten in einem Ziel | Neu starten, dann `/resume` (Auflisten startet nichts). Fortsetzen nur mit `/resume <id>`; Schritte mit Wirkung fragen neu. Erledigte Schritte werden nicht wiederholt. |
| Journal/Gedächtnis beschädigt | Datei nicht überschreiben: umbenennen (`Rename-Item data\journal.db journal.defekt.db`); JARVIS legt bei Bedarf eine neue an. Eine fremde oder beschädigte Datei wird gemeldet und nie stillschweigend überschrieben. |
| Konfiguration ungültig | `jarvis doctor` nennt den Fehler; Kopie der Beispielkonfiguration neu anlegen. Sicherheitsrelevante Werte (`security.*`, `max_steps`, `max_attempts_per_step`) nicht lockern. |
| Alles zurücksetzen | `jarvis-cc` beenden, `venv` und `data\` bleiben unangetastet; nur die Arbeitskopie der TOML verwerfen und die Beispielkonfiguration neu kopieren. |
