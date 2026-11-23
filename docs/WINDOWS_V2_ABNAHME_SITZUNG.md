# Abnahme #186: gemeinsame Abnahmesitzung (Stand 2026-11-14)

Kompakte Anleitung für die Handschritte S1–S9. Verbindlich bleiben `docs/WINDOWS_V2_ABNAHME.md` und `docs/WINDOWS_V2_ABNAHME_KURZ.md`; dieses Dokument ändert keine Kriterien. **Ein Skip ist nie ein PASS** (Skript-Wertung: `NOT_CHECKED`, Exit-Code 3).

## Schon nachgewiesen (lokal, Windows 11, Python 3.14.8; kein Ersatz für die Handschritte, keine CI)
| Schritt | Automatischer Teil | Ergebnis |
|---|---|---|
| S1 | `ci\fresh-install\smoke.py`, `jarvis doctor`, Server-Tests (96) | PASS |
| S2 | Voice-Tests (36) | 35 PASS, 1 `NOT_CHECKED` (Test „kein Mikrofon“ ist mit installiertem sounddevice nicht herstellbar, gehört zum Handschritt „Mikrofon ziehen“) |
| S3 | Windows-TTS-Tests (45) | PASS |
| S7 | NEXUS-Tests inkl. Node-DOM (74) und Browser-E2E (3) | PASS |
| S8 | `test_emergency_stop`, `test_voice_windows_tts` | PASS (ohne native GUI) |
| S9 | Journal/Resume/Session-Budget (68) | PASS |
Nicht automatisch ausgeführt (öffnen reale Fenster/Ton): S4 `tts_first_sound.py`, S5 UIA-Tests und `check_uia.py`, S8 native GUI (`JARVIS_NATIVE_GUI=1`). Handschritte S1–S9: **alle offen**.

## Vorbereitung (einmal)
```powershell
cd C:\JARVIS-Test\V2
$env:Path += ";C:\Program Files\nodejs"          # nur nötig, falls diese PowerShell vor der Node-Installation geöffnet wurde
powershell -ExecutionPolicy Bypass -File scripts\abnahme\run-abnahme.ps1          # Trockenlauf (Bypass gilt nur für diesen Prozess)
```
* **Normale** (nicht erhöhte) PowerShell verwenden; das Skript bricht sonst ab.
* Vorher festlegen, welcher Commit der Release-Kandidat ist (`dirty` steht im Protokoll `00-umgebung.json`).
* Textchat und Sprache starten mit derselben Konfiguration: `jarvis-cc.exe -c config\nexus.voice-test.toml --open` (Whisper-Modell `C:/JARVIS-Test/models/whisper-base`, Windows-TTS). Echtes LLM: Kopie von `config\nexus.live.example.toml` anlegen und `ANTHROPIC_API_KEY` nur in der Sitzung setzen.

## Reihenfolge der Sitzung (ca. 60–90 min)
**Empfohlene Reihenfolge (optimiert, mit Befehlen und Belegen: `docs/RELEASE_KANDIDAT_186.md` §5 und §7): S1+S7 -> S2+S3+S4 -> S5 -> S6 -> S8 -> S9.** Die Nummern unten sind Schritt-IDs; bei Abweichung gilt die Reihenfolge aus `RELEASE_KANDIDAT_186.md`.

1. **Automatik + S1:** `powershell -ExecutionPolicy Bypass -File scripts\abnahme\run-abnahme.ps1 -Execute -Only S1` (fragt PASS/FAIL/NA). Handschritt S1: NEXUS zeigt „verbunden“ und „bereit“, Kugel läuft flüssig, Screenshot `01-nexus.png`.
2. **S2 + S3 + S4 (Audio, eine Runde):** `-Only S2,S3,S4`. Satz sprechen (Pegel bewegt sich, Satz erkannt und beantwortet), danach Mikrofon abziehen (verständliche Meldung, Texteingabe bleibt nutzbar); deutschen Satz anhören (Umlaute); bei „audible“ Enter beim ersten Ton. Mikrofon wieder anschließen.
3. **S5 UIA:** `-Only S5`. Braucht Benutzer: Notepad, Rechner, Einstellungen lesen; eine Freigabe-Aktion **ablehnen**; Passwortfelder nie bedienen.
4. **S6 UAC (nur du):** Notepad per Kontextmenü „Als Administrator ausführen“ selbst starten, im UAC-Dialog selbst entscheiden; dann im Chat „Lies das Notepad-Fenster“: klare Ablehnung/leerer Baum, kein Hänger, JARVIS bleibt nicht erhöht. Das Skript bedient UAC nie. **Einziger Schritt mit Administratorrechten (nur die Fremd-App).**
5. **S7:** `-Only S7`. Mehrstufigen Auftrag starten (z. B. „Liste den Ordner workspace“), Panel „Freigaben“ und „Zeitleiste“ ansehen; Dialog ablehnen / ablaufen lassen / zustimmen; „Animationen reduzieren“ an/aus.
6. **S8 Not-Aus (zuletzt vor S9):** `-Only S8`. (a) langen Text sprechen + NOTAUS (Ausgabe ≤ 1 s weg, kein hängendes `powershell.exe`), (b) langer Auftrag + NOTAUS, (c) UIA-Aktion + NOTAUS, (d) NOTAUS im Overlay (`jarvis-cc --overlay`). Danach Notaus über die Rückfrage aufheben. Der native GUI-Test öffnet Fenster: nicht anfassen, bis er fertig ist.
7. **S9:** `-Only S9`. Auftrag starten, Prozess hart beenden, neu starten: `/resume` listet nur, `/resume <id>` fragt neu; `Select-String -Pattern 'sk-|Bearer ' logs\audit.jsonl` muss leer sein.
Gesamtlauf statt Einzelschritten: `-Execute` (ohne `-Only`). Belege landen in `abnahme-v2\` (`ergebnis.json`, `*.xml`, Screenshots mit Win+Shift+S). **Vor dem Anhängen an #186 auf Schlüssel prüfen.**

## Wer muss was tun
| Schritt | Benutzerinteraktion | Administratorrechte |
|---|---|---|
| S1 | ansehen, Screenshot | nein |
| S2 | sprechen, Mikrofon ziehen | nein |
| S3/S4 | hören, Enter | nein |
| S5 | Fremd-Apps bedienen, Freigaben ablehnen | nein |
| S6 | UAC-Dialog selbst entscheiden | **ja, nur Notepad (nicht JARVIS)** |
| S7 | Dialoge bedienen | nein |
| S8 | NOTAUS auslösen, Prozesse prüfen | nein |
| S9 | Prozess hart beenden | nein |

## Noch fehlende Nachweise / Blocker
* Alle Handschritte S1–S9 (siehe oben), inklusive Messwerte S4/9.x (Owner-Zielwerte fehlen: bleiben `MEASURED`).
* Release-Kandidat nicht committet (`dirty`), kein fester SHA; Windows-CI (`tests-windows`, `uia-compat`, `browser-e2e`) für diese Änderungen nicht gelaufen.
* Echtes LLM nicht konfiguriert/getestet (`[llm]` fehlt in `nexus.voice-test.toml`, kein Schlüssel in der Umgebung); Brave-Websuche und Live-Recherche nie live (kein `BRAVE_SEARCH_API_KEY`, Live-Test braucht `JARVIS_TEST_PUBLIC_WEB=1`).
* `test_browser_real.py::test_popups_become_known_pages` scheiterte einmal in einem großen Lauf (Popup-Zählung), danach 3/3 einzeln und 2/2 im ganzen Modul grün. Vermutung (nicht belegt): feste 120-ms-Wartezeit in `PlaywrightPage._settle`. Bei Wiederholung untersuchen.

## Kürzeste sichere Reihenfolge bis zum Abschluss von #186
1. Owner: Änderungen prüfen und einen Release-Kandidaten committen (kontrollierte Integration, siehe `docs/PRODUKTIVSTART.md`); lokale Dateien nicht mitnehmen (`config/nexus.voice-test.toml`, `abnahme-v2/`, `data/`, `logs/`).
2. CI-Windows auf genau diesem Commit grün abwarten.
3. Sitzung oben durchführen, Belege in `abnahme-v2\`, auf Schlüssel prüfen, an #186 anhängen.
4. Owner-Entscheidung Go/No-Go nach `docs/WINDOWS_V2_ABNAHME.md` §12.
