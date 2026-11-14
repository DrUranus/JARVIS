# Release-Kandidat #186: Integrationsplan, CI-Strategie, Abnahmesitzung, Go/No-Go (Stand 2026-11-14)

**Nichts davon ist ausgeführt oder freigegeben:** kein Commit, kein Push, kein PR. Dieses Dokument bereitet die kontrollierte Integration vor; die Freigabe erteilt der Owner.

## 1. Ausgangslage (geprüft)
* Arbeitskopie `C:\JARVIS-Test\V2`, **detached HEAD `7c2b4b7`** = Spitze von `origin/claude/v2-integration` (0 voraus, 0 zurück). `claude/v2-integration` ist 54 Commits vor `origin/main` (`7cc65b0`), 0 dahinter.
* Offene PRs (GitHub-API, nur gelesen): #258 `claude/v2-integration` -> `main` (Draft, „NICHT mergen“), #259 `claude/v21-integration` -> `claude/v2-integration` (Draft). **Keiner enthält die hier geänderten Quelldateien** (`files_intent.py`, `goal_text.py`, `adapters/base.py`, `cli.py`): keine Doppelarbeit. Einzige Berührung: #259 ändert `tests/test_control_center_views.py` in einem anderen Abschnitt (`test_js_views_use_get_only_and_no_commands`); unsere Änderung (Journal-Pfad im Test `..._wires_journal_and_audit_read_only`) liegt an anderer Stelle, ein Konflikt ist unwahrscheinlich, aber beim Zusammenführen zu beachten.
* Geschützte Pfade (CODEOWNERS: `.github/`, `CLAUDE.md`, `.claude/`, `permissions/`, `bootstrap.py`, `config/jarvis.toml`, `tests/test_emergency_stop.py`, `tests/test_security_*`) sind **nicht** geändert. `tests/test_protected_files.py` ist grün. Es gibt keine Änderung an PermissionEngine, Freigaben oder Not-Aus.
* Hinweis: `git fetch` aktualisierte nur Remote-Tracking-Referenzen im gemeinsamen `.git` (Worktrees teilen es); das Aktualisieren des lokalen `main` scheiterte an einer vorhandenen Sperre `...\JARVIS\.git\refs\heads\main.lock` im Original-Repository. Die Sperre habe ich nicht angefasst (Prüfung: `python -m jarvis.interface.gitlocks`, nur lesend).

## 2. Dateien des Integrations-Commits (14)
| Datei | Zweck |
|---|---|
| `src/jarvis/goals/files_intent.py` | Datei-Intents: Anleitungs-/Fragen-Guard, Namensformeln, Ordner ohne Namen, Orte nie geraten, Datei ohne Inhalt, Mehrfachaktion |
| `src/jarvis/interface/cli.py` | `research_route`: nur Imperative starten ein Recherche-Ziel |
| `src/jarvis/interface/goal_text.py` | Klartext-Erklärungen, konkreter Grund bei Dateianfragen |
| `src/jarvis/agents/adapters/base.py` | Eingabefehler der Datei-/Office-Tools nicht wiederholen (`invalid_input`) |
| `tests/test_agents_files.py`, `tests/test_agents_files_e2e.py`, `tests/test_file_intents_followup.py` (neu) | Regressionstests |
| `tests/test_control_center_views.py` | Test-Isolation (eigener Journal-Pfad) |
| `scripts/abnahme/run-abnahme.ps1` | `NOT_CHECKED` statt FAIL bei SKIP (Exit 3), Playwright-Meldung, `JARVIS_CHROMIUM_PATH`, `-Only S1,S3`-Splitting, Node/Chromium im Protokoll |
| `config/nexus.live.example.toml` (neu) | Beispiel für echtes LLM/Browser/Recherche, **ohne Schlüssel** |
| `docs/PRODUKTIVSTART.md`, `docs/WINDOWS_V2_ABNAHME_SITZUNG.md`, `docs/RELEASE_KANDIDAT_186.md` (neu) | Doku |
| `.gitignore` | schließt `abnahme-v2/`, `config/*.voice-test.toml`, `config/nexus.live.toml`, `config/*.local.toml` aus |
**Ausdrücklich nicht in den Commit:** `config/nexus.voice-test.toml` (lokal, jetzt ignoriert), `abnahme-v2/`, `data/`, `logs/`, `reports/`, `.venv/`, Testartefakte, jede Datei mit Schlüsseln. Geheimnis-Scan über alle 14 Dateien: keine Treffer.

## 3. Integrationsplan (zur Freigabe)
* **Basis:** `origin/claude/v2-integration` (= `7c2b4b7`). **Zielbranch (neu):** `claude/v2-186-windows-abnahme` (Präfix `claude/` ist für die CI-Auslöser nötig). **PR-Ziel:** `claude/v2-integration`, als **Draft**, nicht `main`.
* Befehle (erst nach deiner Freigabe):
```powershell
cd C:\JARVIS-Test\V2
git switch -c claude/v2-186-windows-abnahme            # nimmt die Änderungen mit, kein Reset
git add .gitignore scripts/abnahme/run-abnahme.ps1 src/jarvis/agents/adapters/base.py src/jarvis/goals/files_intent.py src/jarvis/interface/cli.py src/jarvis/interface/goal_text.py `
        tests/test_agents_files.py tests/test_agents_files_e2e.py tests/test_control_center_views.py tests/test_file_intents_followup.py `
        config/nexus.live.example.toml docs/PRODUKTIVSTART.md docs/WINDOWS_V2_ABNAHME_SITZUNG.md docs/RELEASE_KANDIDAT_186.md
git diff --cached --stat                                # muss exakt diese 14 Dateien zeigen
git commit                                              # Nachricht siehe unten
git push -u origin claude/v2-186-windows-abnahme        # Besitzer; löst tests.yml (push, claude/**) aus
```
* **Commit-Nachricht (deutsch, ein Commit):**
  `Windows-Stabilisierung #186: Datei-Intents, Fehlerklartext, Abnahmeskript (NOT_CHECKED), Doku`
  Rumpf: Fragen/Anleitungen lösen keine Dateiaktion aus; Ordnernamen („namens“), fehlende Namen/Inhalte/Orte werden mit Grund zurückgefragt; Eingabefehler der Datei-/Office-Tools werden nicht wiederholt; Abnahmeskript wertet SKIP als NOT_CHECKED; Beispielkonfiguration für echtes LLM; .gitignore für lokale Konfigurationen und Belege. Keine Änderung an PermissionEngine, Freigaben, Not-Aus.
  (Die Zeile `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` wird angehängt.)

## 4. CI-Strategie
**Wiederverwendbarer Nachweis (Basis `7c2b4b7`, alle am 2026-11-12 grün, GitHub-API):** `tests` (push), `pr-tests` (tests-linux/tests-windows, PR und dispatch), `Control Center GUI E2E` (PR und dispatch), `Browser Research (real Playwright)`, `Fresh Install (Windows)`. Für `uia-compat` gibt es auf dieser SHA **keinen** Lauf (nur bei Änderungen unter `ci/uia-compat/**` ausgelöst).
**Was die Änderung braucht:** Sie berührt weder `src/jarvis/browser|research|control_center|ui_contract` noch UIA noch `ci/`. Pfadgefilterte Workflows (`browser-research`, `control-center-gui-e2e`, `uia-compat`, `fresh-install`) würden **nicht** automatisch laufen, und `pr-tests` läuft nur bei PRs gegen `main` (nicht gegen `claude/v2-integration`).
| Workflow | Auslösung für den neuen Commit | Nötig? |
|---|---|---|
| `tests` (gui-windows, phase15-windows) | automatisch beim Push (`claude/**`, Pfade `src/**`, `tests/**`) | ja |
| `pr-tests` (tests-linux + **tests-windows**, Vollsuite) | manuell: Actions -> pr-tests -> Run workflow -> Branch `claude/v2-186-windows-abnahme` (oder `gh workflow run pr-tests.yml --ref claude/v2-186-windows-abnahme`) | **ja (Windows-Nachweis)** |
| `uia-compat` | manuell (workflow_dispatch) | für Go sinnvoll (Pflichtnachweis 7.x), Code unverändert |
| `Control Center GUI E2E` (browser-e2e, native-desktop) | manuell (dispatch) | optional (Code unverändert, Basis grün) |
| `Browser Research`, `Fresh Install` | manuell | optional (Basis grün) |
**Auswertung:** je Lauf `conclusion = success` **und** keine neuen Skips gegenüber der Basis (Skips im Log `-rfEs` prüfen; ein unerklärter Skip ist No-Go laut §12 der Abnahme). Auswertungshilfe: `https://api.github.com/repos/DrUranus/JARVIS/actions/runs?head_sha=<SHA>` (lesend).

## 5. Optimierte Reihenfolge der Abnahmesitzung (alle Befehle in einer **nicht erhöhten** PowerShell)
Vorab (einmal): `cd C:\JARVIS-Test\V2; $env:Path += ";C:\Program Files\nodejs"` (nur falls die Shell vor der Node-Installation geöffnet wurde). Alias: `$A = "powershell -ExecutionPolicy Bypass -File scripts\abnahme\run-abnahme.ps1"` (Bypass nur für diesen Prozess; die dauerhafte Richtlinie bleibt unverändert).
| Nr. | Schritte | Grund der Reihenfolge | Befehl |
|---|---|---|---|
| 0 | Trockenlauf | prüft Pfade, ändert nichts | `& $A` |
| 1 | **S1 + S7** | eine NEXUS-Sitzung: Start sehen, dann Freigabe-/Zeitleisten-Panels | `& $A -Execute -Only S1,S7` |
| 2 | **S2 + S3 + S4** | alle Audio-Schritte am Stück (Mikrofon, Lautsprecher, Latenz) | `& $A -Execute -Only S2,S3,S4` |
| 3 | **S5** | UIA lesend: Notepad, Rechner, Einstellungen | `& $A -Execute -Only S5` |
| 4 | **S6** | UAC (nur du); danach nichts erhöht lassen | `& $A -Execute -Only S6` |
| 5 | **S8** | braucht Sprache (a), Auftrag (b), UIA (c), Overlay (d): erst nach S2–S5 | `& $A -Execute -Only S8` |
| 6 | **S9** | beendet Prozesse hart: zuletzt | `& $A -Execute -Only S9` |
Bereits automatisch nachgewiesen und nur im Gesamtlauf nötig, falls der Owner einen einzigen Beleg wünscht (sonst nicht wiederholen): S1-Server (96), S3-TTS (45), S7-NEXUS (74) + E2E (3), S9 (68), `test_emergency_stop`. Das Skript führt sie je Schritt erneut aus (ca. 1–3 min je Gruppe); ein Überspringen einzelner Schritte erlaubt nur `-Only`.
**Voraussetzungen:** S4: Lautsprecher/Kopfhörer, Standardgerät; S5: Notepad, Rechner, Einstellungen, `pywinauto` (vorhanden); S6: Administratorrechte nur für Notepad (UAC-Dialog selbst entscheiden); S8: Mikrofon, Lautsprecher, Overlay (`pywebview` + WebView2 vorhanden), `JARVIS_NATIVE_GUI=1` setzt das Skript selbst.

## 6. Live-Test mit echtem LLM und Brave-Suche (nach der Abnahmesitzung, eigene Freigabe, kostet Geld)
**Benötigte Schlüssel (nicht vorhanden, nie in Dateien/Git/Berichte):** `ANTHROPIC_API_KEY` (oder `OPENAI_API_KEY`), `BRAVE_SEARCH_API_KEY`. Setzen nur in der laufenden PowerShell, ohne Anzeige:
```powershell
$k = Read-Host "Anthropic-Schluessel" -AsSecureString; $env:ANTHROPIC_API_KEY = [Net.NetworkCredential]::new("", $k).Password
$k = Read-Host "Brave-Schluessel" -AsSecureString;    $env:BRAVE_SEARCH_API_KEY = [Net.NetworkCredential]::new("", $k).Password
Copy-Item config\nexus.live.example.toml config\nexus.live.toml          # lokale Kopie, ist ignoriert
# in nexus.live.toml: search_enabled = true; den [voice]-Block aus nexus.voice-test.toml hineinkopieren, wenn Sprache gebraucht wird
.\.venv\Scripts\jarvis.exe -c config\nexus.live.toml doctor              # erwartet: 0 Fehler, kein Schluessel-Hinweis
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.live.toml --open
```
Testaufträge im Chat: (1) „Erkläre kurz, was ein Ordner ist“ -> echte Antwort statt „[mock]“. (2) „Recherchiere https://example.org“ -> Seite gelesen, Antwort mit Quelle (nur Browser, keine Suche). (3) „Recherchiere die aktuelle Python-Version“ -> Suche + Quellen (Kosten ca. 5 USD je 1000 Anfragen, Limit `search_max_searches`). Erwartet: Quellen mit URL, Rückfragen im Freigabedialog, Audit ohne Schlüssel (`Select-String -Pattern 'sk-|Bearer ' logs\audit.jsonl` leer). Danach `Remove-Item env:ANTHROPIC_API_KEY, env:BRAVE_SEARCH_API_KEY`.

## 7. Erwartete Ergebnisse und Nachweise je Schritt
| Schritt | Erwartung | Beleg (Ordner `abnahme-v2\`) |
|---|---|---|
| S1 | Smoke BESTANDEN, Doctor Exit 0, NEXUS „verbunden/bereit“, Kugel flüssig | `01-smoke.txt`, `01-doctor.txt`, `01-nexus.png` |
| S2 | Pegel bewegt sich, Satz erkannt und beantwortet; Mikrofon ziehen -> verständliche Meldung, Texteingabe bleibt; Median Zeit bis Text (5x) | `02-voice.txt`, `02-devices.txt`, Notiz |
| S3 | deutscher Satz verständlich, Umlaute korrekt; Befehlsähnliches wird nur gesprochen | `03-tts.txt`, Notiz |
| S4 | `MEASURED` (wav und hörbar, Kaltstart getrennt); kein Zielwert -> nie PASS/FAIL | `04-tts-latenz-wav.json`, `04-tts-latenz-hoerbar.json` |
| S5 | Notepad/Rechner/Einstellungen: lesen ok; Freigabe-Aktion abgelehnt führt nichts aus; `check_uia.py` Exit 0 | `05-uia-*.txt`, Notiz je App |
| S6 | Notepad erhöht: klare Ablehnung/leerer Baum, kein Hänger, JARVIS bleibt nicht erhöht | `06-integritaet.txt`, Screenshot, Notiz |
| S7 | Panel „Freigaben“ (Liste, Frist, keine Knöpfe), Dialog ablehnen/ablaufen/zustimmen, Zeitleiste mit Farben, Animationen reduzieren wird respektiert | `07-*.xml`, Screenshots `07-*.png` |
| S8 | (a) Ausgabe ≤ 1 s weg, kein hängendes `powershell.exe`; (b)–(d) Aktion sofort gestoppt, Banner rot | `08-prozesse-vorher/nachher.txt`, Screenshots |
| S9 | `/resume` listet nur, `/resume <id>` fragt neu; Audit ohne Schlüssel | `09-*.xml`, Notiz |
**Ablage:** alles in `C:\JARVIS-Test\V2\abnahme-v2\` (ignoriert, nie committen); Dateiname = Schritt-Nr. + Inhalt; Screenshots mit Win+Shift+S. **Vor dem Anhängen an #186 auf Schlüssel prüfen:** `Select-String -Path abnahme-v2\* -Pattern 'sk-|Bearer |api[_-]?key' -SimpleMatch:$false`.

## 8. Ungeklärtes Popup-Test-Flake (dokumentiert, kein Code geändert)
`tests/test_browser_real.py::test_popups_become_known_pages` scheiterte **einmal** in einem großen Lauf von zehn Dateien (`out["pages"]` war 1 statt 2). Danach: 3 von 3 einzeln grün, 2 von 2 im ganzen Modul grün, im zweiten großen Lauf grün; auf der CI-Basis `7c2b4b7` ist `Browser Research (real Playwright)` grün. Unbelegte Vermutung: Popup-Ereignis trifft nach der festen 120-ms-Wartezeit (`PlaywrightPage._settle`) ein, wenn der Rechner stark ausgelastet ist. **Vorgehen bei Wiederholung:** Test 20x einzeln wiederholen (`pytest tests/test_browser_real.py -k popups --count`/Schleife), Auslastung notieren, erst dann über eine begrenzte Wartebedingung entscheiden. Kein Release-Blocker, solange die CI grün bleibt.

## 9. Go/No-Go-Vorlage (nach `docs/WINDOWS_V2_ABNAHME.md` §12; die Freigabe erteilt nur der Owner)
| Bedingung | Quelle | Ergebnis |
|---|---|---|
| Release-Kandidat festgelegt (SHA: ________) und committet, `git status` sauber | Git | ☐ |
| Pflicht-CI auf genau diesem SHA grün (`tests`, `pr-tests` inkl. tests-windows; Gates G1–G4, G6, G8), keine neuen Skips | Actions | ☐ |
| G0 (V1-Abnahme) erfüllt | `WINDOWS_V1_ABNAHME.md` | ☐ |
| Abschnitt 1 (Installation/Start/V1-Regression), 3.2, 4, 5, 8.3–8.5, 10 = PASS | Sitzung | ☐ |
| Abschnitte 2, 3.3–3.5, 6, 7, 9 nach Umfang des Kandidaten (fehlende WPs als N/A in der Release-Notiz) | Sitzung | ☐ |
| Kein FAIL in 1.3, 1.4, 3.5, 4.2–4.3, 5.3–5.4, 6.4, 8.4, 8.5, 10.x | Sitzung | ☐ |
| Kein `NOT_CHECKED`/PENDING in Pflichtzeilen; kein unerklärter Skip | `ergebnis.json` | ☐ |
| Belege vollständig und schlüsselfrei | `abnahme-v2\` | ☐ |
| Entscheidung: ☐ GO  ☐ NO-GO — Datum/Unterschrift Owner: ________ | | |

## 10. Was du als Owner noch tun musst (in dieser Reihenfolge)
1. Diese 14 Dateien und den Plan prüfen; Freigabe für Branch, Commit und Push erteilen (oder selbst ausführen, Befehle in §3).
2. Auf GitHub `pr-tests` für den Branch manuell starten (und `uia-compat`); Ergebnisse gegen §4 prüfen; Draft-PR gegen `claude/v2-integration` öffnen.
3. Abnahmesitzung nach §5 durchführen (S4/S5/S6/S8 mit Ton, Fenstern, UAC: nur du am PC).
4. Optional: Schlüssel setzen und Live-Test nach §6 (eigene Freigabe, Kosten).
5. Belege in #186 anhängen (schlüsselfrei), Go/No-Go (§9) entscheiden. Kein automatischer Merge, Release oder Tag.
