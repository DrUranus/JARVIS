# Windows-Abnahme #186 – Kurzanleitung (Owner-PC)

**#186 bleibt offen, bis dieser Ablauf auf dem echten PC gelaufen und der Ordner `abnahme-v2\` in #186 dokumentiert ist.** Die CI ersetzt das nicht. Das Skript installiert nichts, bestätigt oder bedient UAC nie und erhöht keine Rechte; es bricht in einer erhöhten PowerShell ab.

## Einmalig (ca. 10 min)
```powershell
cd C:\dev\JARVIS                                   # Ordner AUSSERHALB von OneDrive; Release-Kandidat ausgecheckt
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,voice,ui]"
```
(`voice` für Mikrofon/TTS, `ui` für das native Overlay – wie in V1; ohne sie meldet das Skript den Schritt als nicht ausführbar.)

## Ablauf (normale, **nicht** als Administrator gestartete PowerShell)
```powershell
powershell -File scripts\abnahme\run-abnahme.ps1             # 1. TROCKENLAUF: gibt nur aus, was passieren würde; schreibt/startet nichts
powershell -File scripts\abnahme\run-abnahme.ps1 -Execute    # 2. echter Lauf (ca. 60–90 min, davon ca. 25 min Handarbeit)
```
Teilschritte: `-Execute -Only S3,S4` (nur TTS und Zeitmessung). Das Skript fragt die Handschritte ab: **PASS / FAIL / NA** und eine Notiz. Protokoll: `abnahme-v2\run.log`, Ergebnis: `abnahme-v2\ergebnis.json`.

## Was du selbst tun musst (nicht automatisierbar)
1. NEXUS ansehen (S1), Satz ins Mikrofon sprechen (S2), deutschen Satz anhören (S3), bei der Zeitmessung **Enter** drücken, sobald der erste Ton zu hören ist (S4).
2. Notepad (Windows 11), Rechner, Einstellungen: harmlose Lese-Aktion; Freigabe in Notepad **ablehnen** (S5).
3. **UAC (S6):** Notepad über „Als Administrator ausführen“ **selbst** starten und im UAC-Dialog **selbst** entscheiden; danach im Chat „Lies das Notepad-Fenster“: erwartet klare Ablehnung oder leerer Baum, kein Hänger.
4. Mehrstufigen Auftrag starten, Panel „Freigaben“ und „Zeitleiste“ ansehen, Rückfragen ablehnen/ablaufen lassen/zustimmen (S7); NOTAUS während Sprachausgabe, Auftrag und UIA-Aktion (S8); Prozess hart beenden, neu starten, `/resume` (S9).

## Wertung und Abschluss
* PASS nur mit Beleg. **Übersprungene Tests zählen als FAIL des Schritts.** Messwerte (S4, Leistung) sind **MEASURED**, nicht „bestanden“, solange keine Zielwerte festgelegt sind.
* No-Go bei jedem FAIL bei Freigabe/Ablehnen/Timeout/Not-Aus oder fehlenden Belegen (`docs/WINDOWS_V2_ABNAHME.md` §12).
* Belege **vor dem Anhängen an #186 auf Schlüssel prüfen** (`Select-String -Path abnahme-v2\* -Pattern "sk-|Bearer "` muss leer sein).

## Wenn etwas nicht läuft
`jarvis doctor` nennt fehlende Komponenten · Exit-Code 3 = `.venv` fehlt · Exit-Code 2 = PowerShell war erhöht (normal neu öffnen) · kein Mikrofonpegel → Windows-Mikrofonfreigabe/Standardgerät · keine deutsche Stimme → Windows-Sprachpaket (Owner-Entscheidung) · Overlay-Test startet nicht → `".[ui]"`/WebView2.
