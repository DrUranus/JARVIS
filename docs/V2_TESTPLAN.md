# JARVIS V2.0: Testmatrix, Release-Gates und Skip-Bericht

**Status: Vorbereitung (WP08). Keine CI-Workflows geändert oder gestartet; nichts unter `.github/`.** Gilt für den Umfang „V2.0 Minimum“ (`F_V2_0_IMPLEMENTIERUNGSPLAN.md`, Scratchpad-Plan) und ergänzt `docs/TESTING.md` (Befehle, Workflows, Umgebungsbefunde) – wiederholt es nicht. Hinweis für den Merge: ein Verweis auf diese Datei kann in `docs/TESTING.md` ergänzt werden (hier bewusst nicht geändert, um Konflikte mit anderen Branches zu vermeiden). Grundsätze aus `CLAUDE.md`: Ein übersprungener Test gilt nie als bestanden; Linux-Ergebnisse sind kein Windows-Nachweis; Runner-CI (Windows ohne Mensch) ersetzt nicht die interaktive Abnahme (#186 für V1, `docs/WINDOWS_V2_ABNAHME.md` für V2).

## 1. Testmatrix
Spalten: **L** = Linux-CI (`tests-linux`), **W** = Windows-CI (`tests-windows` und gezielte Jobs), **PC** = interaktiv am echten Windows-PC. „✔“ = vorgesehen/vorhanden, „–“ = nicht zutreffend. Dauer: belegte Beobachtungen vom 2026-11-11 (Stichproben).
| Ebene | Inhalt (Beispiele) | L | W | PC | Dauer |
|---|---|---|---|---|---|
| Einheit/Komponente | reine Funktionen: Artefakte (`test_agent_artifacts`), Kostenmodell (`test_llm_cost_budget`), Projektkontext, Quellenbewertung, Skip-Bericht | ✔ | ✔ | – | Sekunden |
| Sicherheitsregression | `tests/test_*security*.py`, `test_emergency_stop.py`, `test_autonomy_invariants.py`; Strukturtests (nur eine Kontrollstelle, keine unerlaubten Importe, Layering „unverdrahtet“) | ✔ | ✔ | – | ~1 Min. gezielt |
| Agenten-Integration | Orchestrator/Goal Engine mit Fake-Agenten und Mock-LLM; Plan-Harness mit Golden-Fingerabdrücken (`tests/plan_eval*.py`, nach Merge von #230) | ✔ | ✔ | – | in der Vollsuite |
| Windows-Prozess/UIA | Job Objects, ACL, Junctions, `computer`-Tests mit Fakes, Notepad-E2E auf dem Runner | (erwartete Skips) | ✔ | echte Apps | Runner Minuten |
| GUI-E2E | Node-DOM-Tests, Chromium-E2E (Orb, Dashboard, Dialog, später Timeline/Freigaben) | ✔ | ✔ (`real-browser`, `gui + voice + emergency stop`) | natives Fenster, Overlay, Mehrmonitor, GPU | ~1–2 Min. |
| Browser-E2E | lokale Testseite + Chromium; Live-Web nur manuell | ✔ | ✔ | Live-Brave mit Schlüssel | ~1 Min. |
| Sprache | Fake-Quellen/Detektoren, Fake-Läufer für Windows-TTS (nach Freigabe); Hörprobe | ✔ | ✔ | Mikrofon, Lautsprecher, Latenz | manuell |
| Frischinstallation | `fresh-install.yml` | – | ✔ | – | Minuten |
| Performance | Frame-Zeit im Chromium-E2E (Richtwert), Startzeit, Task-Durchsatz mit Fake-Agenten, STT-Zeit | begrenzt | begrenzt | **maßgeblich** | Messprotokoll |
| Zuverlässigkeit | Neustart/Resume, Not-Aus unter Last, drei grüne Vollläufe in Folge | ✔ | ✔ | Dauerlauf | Stunden |
| Kosten/Aufgabe | Token-/Zeitzähler auf festem Aufgabenkorpus (Mock deterministisch; echtes Modell manuell) | ✔ | ✔ | Echtmodell-Lauf | Messprotokoll |
| Lizenz/Abhängigkeit | `test_integration_docs.py`, Prüfdateien, Hash-Pinning | ✔ | ✔ | – | Sekunden |
**Gezielte Läufe zuerst** (`python -m pytest -rfEs tests/test_<modul>_*.py`), danach Sicherheitsregression, die volle Suite nur an Meilensteinen (CI). Windows-Vollsuite ≈ 22–28 Min. je Lauf (belegt), Linux ≈ 3,5 Min.

## 2. Release-Gates (reproduzierbar)
Zahlenwerte für G5 und G7 legt der Owner fest; ohne Zahl gilt das Gate als **offen**, nicht als bestanden.
| Gate | Bedingung | Befehl / Nachweis |
|---|---|---|
| **G0** | V1-Windows-Abnahme #186 bestanden (Go) | Owner-Protokoll `docs/WINDOWS_V1_ABNAHME.md`, Issue #186 |
| **G1** | Sicherheitsregression grün; **keine Änderung** an PermissionEngine, X0, Not-Aus, Audit, Sicherheitsdefaults | `python -m pytest -rfEs tests/test_*security*.py tests/test_emergency_stop.py tests/test_autonomy_invariants.py` und `git diff --stat origin/main...HEAD -- src/jarvis/permissions src/jarvis/ui_contract config/jarvis.toml .github` muss leer sein oder jede Zeile ist vom Owner ausdrücklich freigegeben |
| **G2** | Volle Suite grün auf Linux **und** Windows; Skips innerhalb der Baseline und erklärt | CI-Jobs `tests-linux`, `tests-windows` auf dem Release-Kandidaten; `python -m pytest -rs … > pytest.txt` dann `python tests/support/skip_report.py pytest.txt --platform windows --strict` (Exit-Code 0) |
| **G3** | GUI-E2E, Browser-E2E, Frischinstallation grün | CI-Jobs `gui + voice + emergency stop`, `real-browser (windows-latest / ubuntu-latest)`, `fresh-install` |
| **G4** | Agenten-Integration und Plan-Harness: Golden unverändert **oder** bewusst aktualisiert und vom Owner geprüft | `python -m pytest -rfEs tests/test_plan_eval.py tests/test_goals_*.py` (nach Merge von #230) |
| **G5** | Performance-Budgets erfüllt (Owner-Zahlen: Startzeit, UI-Framezeit, Zeit bis Text bei Sprache, Task-Durchsatz) | Messprotokoll am Owner-PC (`docs/WINDOWS_V2_ABNAHME.md` §9) |
| **G6** | Zuverlässigkeit: drei aufeinanderfolgende grüne Vollläufe auf dem Release-Kandidaten; Resume- und Not-Aus-Test | drei CI-Läufe (verschiedene Pushes/Dispatches, nicht dieselbe Prüfung wiederholt); Abnahme §8 |
| **G7** | Kosten je erfolgreicher Aufgabe gemessen und innerhalb des Owner-Budgets | Messprotokoll (Korpus + Zähler); ohne Preistabelle/Token: `UNKNOWN` = Gate offen |
| **G8** | Lizenz-/Abhängigkeits-Gate: Prüfdatei für jedes neu aufgenommene Paket, Hash-Pinning, keine AGPL/GPL, **kommerzielle Nutzung berücksichtigt** | `python -m pytest -rfEs tests/test_integration_docs.py`; Owner prüft `docs/integrations/*` |
| **G9** | Interaktive V2-Abnahme am Windows-PC | `docs/WINDOWS_V2_ABNAHME.md` (alle Pflichtzeilen PASS) |
| **G10** | Owner-Freigabe zum Release (kein automatischer Release/Tag) | ausdrückliche Owner-Entscheidung |

## 3. Skip-Bericht (`tests/support/skip_report.py`)
- Eingabe: Ausgabe von `pytest -rs`. Gruppiert die Gründe in Kategorien (interaktiv, bekannte Lücke, optionale Bibliothek, Umgebung, extern, plattformbedingt) und vergleicht mit `tests/support/skip_baseline.json` (Windows **46**, Linux **119** als Obergrenze; Quellen in der Datei).
- Exit-Codes: `0` in Ordnung · `1` mehr Skips als die Baseline · `2` (nur `--strict`) unbekannter Grund · `3` Baseline fehlt/ungültig (kein stilles Grün).
- **Interaktive Skips** (`JARVIS_NATIVE_GUI=1 fehlt`) und **bekannte Lücken** (Symlink-Recht in `test_office.py`, `/proc`-Nachfahrenerkennung im Workspace-Test) werden gesondert ausgewiesen; sie sind **nicht bestanden**.
- Baseline-Änderungen sind bewusst und mit Begründung im PR vorzunehmen (Absenken ist erwünscht, Anheben braucht Owner-Zustimmung).
- Grenze: Die 119 Linux-Skips der V1-Referenz sind nicht einzeln aufgeschlüsselt; ein lokaler Linux-Lauf zeigte 93 Skips (78 plattformbedingt, 12 optionale Bibliothek, 2 Umgebung, 1 extern) – der Unterschied zu 119 ist nicht erklärt.

## 4. Betrieb
- **Nächtliche/zeitgesteuerte Läufe:** nur als Entwurf (`docs/V2_04_CI_VERGLEICH.md`, Variante „Lauf nur bei Änderung“); Einführung ist ein **Owner-PR** an `.github/`.
- **Flaky-Regel:** ein Wiederholungslauf nur mit Begründung; wiederkehrende Fehler sind Fehler. Tests werden nie abgeschwächt oder auf `skip` gesetzt, um grün zu werden; neue Skips brauchen Plattformgrund und Ersatznachweis.
- **Commit-Hinweis:** die Stichwörter für `ci-phase15`/`ci-full` in eckigen Klammern lösen zusätzliche Windows-Läufe aus (siehe `docs/TESTING.md`); nur bewusst verwenden.
