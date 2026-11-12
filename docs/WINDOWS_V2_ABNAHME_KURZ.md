# Windows-Abnahme #186 / V2 – Kurzanleitung für den Owner-PC (möglichst wenig Handarbeit)

Stand 2026-11-12. **#186 bleibt offen, bis dieser Ablauf auf dem echten PC gelaufen und der Nachweis (Ordner `abnahme-v2\`) in #186 dokumentiert ist.** Die CI ersetzt das nicht. Das Skript ist auf Windows **noch nicht ausgeführt**: der erste Lauf ist deshalb ein **Trockenlauf**. Ausführliche Fassung: `docs/WINDOWS_V2_ABNAHME.md` (Tabellen), V1-Teil: `docs/WINDOWS_V1_ABNAHME.md`.

## Vorbereitung (einmalig, ca. 10 min)
1. Release-Kandidat auschecken (Ordner **außerhalb von OneDrive**), `py -3 -m venv .venv`, `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` (wie V1 §1). Für die Schritte S2/S8 zusätzlich `".[voice]"` und `".[ui]"` (V1-Voraussetzungen; das Skript installiert **nichts**, es meldet nur, was fehlt).
2. Eine **normale** (nicht als Administrator gestartete) PowerShell öffnen. Das Skript bricht ab, wenn es erhöht läuft.

## Ablauf (ca. 60–90 min, davon ca. 25 min Handarbeit)
| Schritt | Befehl / Handlung | Ergebnis |
|---|---|---|
| 1 Trockenlauf | `powershell -File scripts\abnahme\run-abnahme.ps1` | gibt nur aus, was passieren würde; startet und ändert nichts |
| 2 Echter Lauf | `powershell -File scripts\abnahme\run-abnahme.ps1 -Execute` | führt die automatisierbaren Prüfungen aus (smoke, doctor, pytest-Gruppen, nur lesende UIA-Prüfungen) und fragt die Handschritte ab (PASS / FAIL / NA + Notiz) |
| 3 Einzelne Schritte | `... -Execute -Only S3,S4` | z. B. nur TTS und Zeitmessung |
| 4 Belege | Ordner `abnahme-v2\` (`ergebnis.json`, `*.xml`, `*.txt`, Screenshots mit Win+Shift+S) | **vor dem Anhängen an #186 auf Schlüssel prüfen** |

## Handschritte, die nicht automatisierbar sind
* **S1** NEXUS ansehen (Kugel flüssig, „verbunden/bereit“). **S2** Satz ins Mikrofon sprechen, Mikrofon abziehen. **S3** deutschen Satz anhören (verständlich, Umlaute). **S4** bei „audible“ Enter drücken, sobald der erste Ton zu hören ist.
* **S5** harmlose Lese-Aktion in Notepad (Windows 11), Rechner, Einstellungen; Freigabe in Notepad **ablehnen**.
* **S6 UAC:** Notepad über das Kontextmenü „Als Administrator ausführen“ **selbst** starten und im UAC-Dialog **selbst** entscheiden; das Skript bestätigt oder bedient UAC nie und erhöht nie Rechte. Danach „Lies das Notepad-Fenster“ im Chat: erwartet klare Ablehnung oder leerer Baum, kein Hänger.
* **S7** mehrstufigen Auftrag starten, Panel „Freigaben“ und „Zeitleiste“ ansehen, Rückfragen ablehnen/ablaufen lassen/zustimmen. **S8** NOTAUS während Sprachausgabe, Auftrag und UIA-Aktion; danach `Get-Process powershell`. **S9** Auftrag starten, Prozess hart beenden, neu starten, `/resume` (nur Auflisten), dann gezielt `/resume <id>`.

## Wertung
* PASS nur mit Beleg; **übersprungene Tests zählen als FAIL des Schritts**; Messwerte (S4, G5/G7) sind **MEASURED**, nicht bestanden, solange keine Owner-Zielwerte festgelegt sind.
* No-Go bei jedem FAIL in Freigabe-/Ablehnen-/Timeout-/Not-Aus-Zeilen oder bei fehlenden Belegen (`WINDOWS_V2_ABNAHME.md` §12). Die Freigabe zum Release erteilt ausschließlich der Owner.

## Fehlerdiagnose in einem Satz
`jarvis doctor` nennt fehlende Komponenten; kein Mikrofonpegel → Windows-Mikrofonfreigabe/Standardgerät; keine deutsche Stimme → Windows-Sprachpaket (Owner-Entscheidung); Overlay-Test startet nicht → `".[ui]"`/WebView2; Panel leer → `agents.enabled`/`security.audit_enabled` in der Konfigurationskopie.
