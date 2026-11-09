# Windows-Release 21.11.2026: Bestandsaufnahme, Risiken, Abnahmeprotokoll (Stand 2026-11-08)

Dieses Dokument ändert keine Freigabe, startet nichts und ersetzt keine Abnahme. Es trennt streng:
**A** = automatisch geprüft (Tests laufen im PR/CI) · **L** = nur unter Linux geprüft · **W** = in der Windows-CI geprüft (`tests-windows`, Windows-Runner **ohne Menschen am Desktop**) · **I** = interaktive Windows-Prüfung durch einen Menschen **ausstehend** (Issue #186) · **B** = blockiert / nicht freigegeben.

## 1. Feature-Matrix
| Funktion | Implementiert | Getestet | Windows-CI | Echte GUI-Abnahme | Blocker |
|---|---|---|---|---|---|
| NEXUS Orb/Dashboard, Zustandsfarben, Systemstatus (#189) | ja | A: Node-DOM + Chromium-E2E (25 Tests), L: Tk | W: `browser-e2e` (headless Chromium), `tests-windows` | I | #186 |
| Freigabedialog (Ablehnen = Standard, Timeout/Trennung abgelehnt) | ja (#148) | A: Browser-E2E, Engine-Tests | W: Browser-E2E; `native-desktop` (Runner): Dialog sichtbar, Escape lehnt ab | I | #186 |
| Not-Aus (Orb, Dashboard, Overlay) | ja | A: Engine, Browser-E2E (Fake **und echte Engine**) | W: `native-desktop` (Mausklick im Overlay → `emergency`-Ereignis der echten Engine) | I | #186 |
| Mini-Overlay (pywebview, optional) | ja (#168) | A: Fake-Fenster; W: echtes Fenster auf dem Runner (Größe ~140x140, Always-on-Top, Klick auf Kern → Rückruf) | W (nicht interaktiv) | I (Fokus, Mehrmonitor; tatsächliches Öffnen des Systembrowsers ungetestet) | #186 |
| Sprache (STT/TTS, VAD, Barge-in, NEXUS-Knöpfe) | ja (console/mock/openai/system; lokal als Extra `stt-local`) | A: geskriptetes STT/TTS in echter `VoiceSession` (Browser-E2E, 4 Tests), Fehlerfall „kein Mikrofon“ | W: Tests laufen; **keine Hardware** | I; **echtes Mikrofon/Lautsprecher nicht getestet** (vom Besitzer verschoben) | Hardware |
| Agentenkoordination (Router, Orchestrator, Fehlerbehandlung, Wiederholung ≤3) | ja (#97, #103) | A: Unit + Integration (`test_assistant_e2e`, `test_goals_integration`) | W | – | – |
| Zielplanung (Regeln, optional LLM, Neuplanung) | ja (#88) | A: Mock-LLM | W | – | echtes LLM ungetestet |
| Browserrecherche mit Brave (#194) | ja (opt-in) | A: Mock-Provider/-Transport, Fake-Browser, Injection, Fehlerfälle | W: Tests; **echter Playwright-Browser läuft in der Pflicht-CI nicht** (Tests skippen ohne Playwright) | I | **kein Live-Lauf** (Schlüssel, Netz) |
| Datei-Tool `files` (Workspace, bestätigte Wurzeln, kein Löschen) | Tool ja (#108); Agent `files` **in PR #216 (offen, nicht gemergt)** | A: `test_files_tools`, `test_agents_files` (34), E2E über den Server (#220, offen) | W: nach CI-Lauf der PRs | I | R2 erst mit Merge von #216 gelöst |
| Office-Tool `office` (xlsx/docx, ohne Makros, #211) | Tool ja; Agent `files` (#216, offen) | A: Tool-Tests, `test_agents_files` | W: nach CI-Lauf | I | R2 erst mit Merge von #216 gelöst |
| Computer-Steuerung (Bildschirm, Maus, Tastatur, Fenster) | ja | A: Fake-Provider; L: X11 | W: `windows-capture-tests` | I (echte Eingabe) | – |
| Windows-UI-Automation (lesen + handeln, pywinauto 0.6.9) | ja (#65–#116) | A: Fake; W: **echt an Notepad** (Passwortfeld nur lesend) | W (py 3.13 und 3.14 in `uia-compat`) | I | – |
| Memory (SQLite, lokale Suche) | ja | A | W | – | OneDrive-Pfade (R7) |
| Task-Journal + `/resume` (#95, #105, #192) | ja | A: Absturz-Simulation, Notaus, Bestätigung; **neu (PR #226, offen): echtes hartes Prozessende (kill) mit SQLite-Integritätsprüfung** | W: nach CI-Lauf | I (echter Neustart) | – |
| Coding-Agent + Tests, LLM-Änderungsvorschläge | ja (#140) | A: Fake-Provider, Windows-Prozessbaum (`winjob`) | W | – | echtes LLM ungetestet |
| LLM-Anbieter (mock, openai, anthropic, openai_compatible) | ja | A: Mocks | W | – | **Standard `mock`**, kein Live-Test (R4) |
| PermissionEngine, Not-Aus, Audit, Sitzungsbudget | ja | A: >800 Sicherheitstests | W | – | – |
| Windows-Installation/Erststart (`jarvis doctor`, `jarvis-cc`, `nexus.example.toml`, Schnellstart #214) | ja | A: Doctor-/Config-Tests; W: `pip install -e ".[dev]"` (Py 3.13) | W | **I: frische Installation auf echtem PC** | R6/R7/R8 |
| NEXUS-Einrichtung/Diagnose (`GET /view/doctor`, nur lesend) | PR #217 (offen) | A: 12 Tests + Chromium-E2E, Schlüssel nur gesetzt/nicht gesetzt | W: nach CI-Lauf | I | – |
| Frischinstallations-Rauchtest (venv, Import, CLI, Doctor, `jarvis-cc` Start/Stopp) | Skript PR #218 (offen); Workflow PR #219 (offen, **Besitzer-Review**) | L: lokal grün | W: erst nach Merge/Lauf von #219 | I (frische Installation auf echtem PC) | R6/R8 |
| Python 3.14 | – | L: **vollständige Suite grün (3.14.6)** + Tk-Tests unter Xvfb; 3.11: grün | nur `uia-compat` (3.14); **Vollsuite auf Windows/3.14 nicht in der CI** | I | R6 |
| Automatisierungskette | ja | A: Automatisierungstests | W (Gate) | – | genehmigter Backlog **ausgeschöpft**, `cc-windows-smoke` zurückgestellt (B) |
| Mail, Medien (`mail-provider`, `media-agent`) | nur Entwürfe (Doku) | – | – | – | B: nicht freigegeben |
| Smartphone | nein | – | – | – | zurückgestellt bis nach stabiler PC-Version |

## 1a. Was in dieser Sitzung tatsächlich ausgeführt wurde (Linux, nicht Windows)
| Prüfung | Ergebnis |
|---|---|
| Vollständige Testsuite, Python 3.14.6 (venv, `pip install -e ".[dev]"`) | keine Fehlschläge |
| Vollständige Testsuite, Python 3.11 | keine Fehlschläge (Skips: Tk/Display, POSIX/Windows-spezifisch) |
| Tk-GUI-Tests (`test_gui_view/model/confirmation`) unter Xvfb, Python 3.14 | grün |
| Echte Playwright-Browser-Tests (`test_browser_real`, `test_analysis_real`, `test_browser_basics`) mit installiertem Chromium | grün (lokaler Server; Live-Internet-Test bewusst nicht) |
| Wiederholung der nebenläufigen Module (Agenten, Goals, Control-Center-Server, Journal, Assistent, Notaus, `/resume`) 5x unter 3.14 | 5/5 grün, keine Flakes |
| Server-Last: 80 sequenzielle + 30 parallele SSE-Verbindungen auf/zu | Clients zurück auf 0, keine übrigen Threads, Server antwortet |
| `jarvis-cc -c config/nexus.example.toml` als echter Prozess: Start, Token-Pflicht (401 ohne Token), SIGINT | sauberes Beenden, Port geschlossen |
| Randeingaben im echten Assistenten (leer, sehr lang, Unicode, unbekannter Befehl) | korrekt abgelehnt bzw. beantwortet |

**Hinweis 2026-11-09:** Die Ergänzungen der Zehn-Aufgaben-Kette (Abschnitt 8) sind Linux-geprüft; ihr Windows-CI-Stand steht in den jeweiligen PRs und ist hier **nicht** als bestanden eingetragen.

**Windows-CI** (Runner, nicht interaktiv): `tests-windows` lief für PR #215 grün. Bei PR #214 fand sie einen **Testfehler in meinem neuen Test** (`os.utime(..., follow_symlinks=False)` ist unter Windows nicht verfügbar); behoben im selben PR.

## 2. Die zehn wichtigsten Release-Risiken (priorisiert)
1. **R1 Keine echte interaktive Windows-GUI-Abnahme.** Runner-Tests (headless Chromium, Runner-Desktop) belegen Mechanik, nicht das Verhalten für einen Menschen (Fokus, Mehrmonitor, echte Fenster, Darstellung/Leistung). Abnahmeprotokoll: Abschnitt 5, Issue #186. *Release-Blocker.*
2. **R2 Agenten können Datei- und Office-Aufträge nicht ausführen.** Die Tools `files` und `office` existieren, aber kein Agent (`research`, `browser`, `coding`, `computer`, `business`, `finance`) deklariert sie; über Router/NEXUS-Aufträge sind sie nicht erreichbar, nur per `/run`. Ein neuer Agent ist eine neue Fähigkeit und braucht Freigabe (Empfehlung E1).
3. **R3 Webrecherche nie live; echter Browser nicht in der Windows-Pflicht-CI.** `test_browser_real`/`test_analysis_real` skippen in `tests-windows` (kein Playwright installiert); unter Linux laufen sie lokal grün (siehe 1a). Brave-Schlüssel, Netz und `playwright install` unter Windows unbewiesen.
4. **R4 Echtes LLM ungetestet.** Standard ist `mock`. Plan-Qualität realer Modelle (Zielzerlegung, Code-Vorschläge) ist unbewiesen; ohne LLM sind nur URL-, Workspace-, Bildschirm- und Suchaufträge planbar.
5. **R5 Sprache auf echter Hardware ungetestet** (Mikrofon, Lautsprecher, lokale Modelle/Downloads). Vom Besitzer verschoben.
6. **R6 Python 3.14 auf Windows nicht in der Vollsuite abgesichert.** Linux 3.14.6: grün; Windows nur `uia-compat`. Tk-GUI/Windows-spezifische Pfade (winreg, winjob, pywebview) unter 3.14 ungeprüft.
7. **R7 OneDrive-Pfade.** SQLite (Gedächtnis, Journal) und Git-Sperren in OneDrive-Ordnern; #214 warnt im Doctor und bringt `gitlocks`, aber nicht auf echtem Windows verifiziert.
8. **R8 Erststart-Komplexität.** Konfiguration per TOML/Umgebung, keine geführte Einrichtung in NEXUS; fehlende Schlüssel werden erst bei Nutzung erklärt (Empfehlung E2).
9. **R9 Mini-Overlay-Voraussetzungen und Hauptfenster-Öffnen.** Braucht `.[ui]` + WebView2; „Klick öffnet Hauptfenster“ ist bis zum Rückruf belegt, das tatsächliche `webbrowser.open` unter Windows nicht.
10. **R10 Autonome Weiterentwicklung steht.** Genehmigter Backlog ausgeschöpft, `cc-windows-smoke` (B9) zurückgestellt; ohne neue Besitzerfreigaben läuft die Kette nicht weiter.

## 3. Bekannte Einschränkungen
- Kein 3D/WebGL-Kern: Canvas-2D mit Tiefenwirkung, 2D-Fallback bei „Effekte aus“ und `prefers-reduced-motion`.
- Pegelanzeige zeigt nur Mikrofon an/aus (das Backend meldet keinen Pegel).
- Plain-Chat-Routing nur für Eingaben, die mit „Recherchiere/Finde heraus/Informiere dich/Research/Find out“ beginnen.
- Rückfragen ohne Antwort/Zeitablauf/Verbindungsverlust gelten immer als abgelehnt (gewollt).
- Mail, Medien, MCP, externe Coding-Agenten und Smartphone sind nicht umgesetzt.
- Suchtext-Erzeugung ist regelbasiert (kein LLM).

## 4. Release-Checkliste
- [ ] #214 gemergt (Schnellstart, OneDrive-Hinweis, `gitlocks`); `docs/WINDOWS_QUICKSTART.md` auf dem Windows-PC einmal Schritt für Schritt durchgegangen.
- [ ] `jarvis doctor`: Exit-Code 0 auf dem Zielrechner.
- [ ] `jarvis-cc -c config\nexus.example.toml --open` startet, Orb sichtbar, Zustand „bereit“.
- [ ] Abnahmeprotokoll Abschnitt 5 vollständig ausgefüllt, **Belege** (Screenshots/Logs) abgelegt, #186 aktualisiert.
- [ ] Windows-CI auf dem Release-Commit grün (`tests-windows`, `browser-e2e (windows-latest)`, `native-desktop`); Skips kontrolliert (`-rs`).
- [ ] Entscheidung zu R2 (Datei-/Office-Agent) und R3 (Webrecherche live) getroffen.
- [ ] Python-3.14-Entscheidung: auf dem Zielrechner 3.13 oder 3.14 verwenden; bei 3.14 Abschnitt 5 Schritt 1 besonders beobachten.
- [ ] Bekannte Einschränkungen (Abschnitt 3) in die Release-Notiz.

## 5. Windows-Abnahmeprotokoll (für #186, auf dem echten Windows-Desktop auszufüllen)
Datum/Build/Commit/Windows-Version/Python-Version eintragen. Je Zeile **bestanden / fehlgeschlagen / nicht geprüft**, Beleg (Screenshot/Log) benennen. Nichts als bestanden markieren, was nicht tatsächlich geprüft wurde.

| # | Prüfung | Erwartung | Ergebnis | Beleg |
|---|---|---|---|---|
| 1 | Installation nach `docs/WINDOWS_QUICKSTART.md` (ohne ExecutionPolicy-Änderung, Ordner außerhalb OneDrive) | `jarvis doctor` Exit-Code 0 | | |
| 2 | `jarvis-cc -c config\nexus.example.toml --open` | Browser zeigt NEXUS, „verbunden“, Zustand „bereit“ (grün) | | |
| 3 | Orb ↔ Dashboard manuell | Umschalten funktioniert, Kugel läuft flüssig, Systemstatus plausibel | | |
| 4 | Chat: „Recherchiere die Vorteile von Python“ ohne eingerichtete Websuche | verständliche BLOCKED-Meldung (Was fehlt / Warum / Was tun / Alternative) | | |
| 5 | Chat-Eingabe und Antwort | Antwort erscheint, Zustand wechselt (violett → grün) | | |
| 6 | Freigabedialog (z. B. `/run files action=list` bzw. Computer-Aktion) | Dialog mit allen Feldern, Ablehnen ist Standard (Escape lehnt ab), ohne Antwort wird abgelehnt | | |
| 7 | NOTAUS im Orb-Modus, im Dashboard, bei offenem Dialog | wirkt sofort, Banner rot, neue Eingaben abgelehnt, Aufhebung nur über Rückfrage | | |
| 8 | Effekte „reduziert“/„aus“, Windows „Animationen reduzieren“ | 2D-Fallback ohne Fehler | | |
| 9 | Mini-Overlay `jarvis-cc --overlay --overlay-on-top` (mit `.[ui]`) | ~140x140, immer im Vordergrund, NOTAUS erreichbar, Klick auf Kern öffnet das Hauptfenster im Browser | | |
| 10 | Verbindungsverlust (jarvis-cc beenden, Seite offen lassen) | „GETRENNT“, Dialog schließt als abgelehnt | | |
| 11 | `/resume` nach hartem Beenden mitten in einem Ziel | Auflisten startet nichts; Fortsetzen nur auf Befehl; riskante Schritte fragen neu | | |
| 12 | Sprache (nur wenn Hardware getestet werden soll; sonst „nicht geprüft“) | Start/Ende, erkannter Satz, Antwort, Notaus beendet Sprachmodus | | |
| 13 | Webrecherche mit eigenem Schlüssel und Browser (optional) | Antwort mit Quellen, jede Seite fragt nach | | |
| 14 | Beenden (Strg+C) | Port geschlossen, keine hängenden Prozesse (Task-Manager) | | |

## 6. Fehlerbehebung (Kurzfassung)
Siehe `docs/WINDOWS_QUICKSTART.md` Abschnitt 6 (ExecutionPolicy, OneDrive, `index.lock`, Token/URL, Mikrofon, Websuche). Ergänzend: Tk-GUI braucht Python von python.org (tkinter); `jarvis-gui` ist unabhängig von NEXUS.

## 7. Phase I: Empfehlung für die nächsten Freigaben (nichts davon ist freigegeben oder gestartet)
Zulässige nächste Automatisierungsschritte **gibt es aktuell keine**: `next` findet keinen freigegebenen, nicht erledigten, nicht zurückgestellten Schritt (geprüft: nur `cc-windows-smoke`, zurückgestellt bis 2026-12-07). Die Kette wird nicht künstlich gestartet. Empfohlen, **einzeln** freizugeben (Besitzer ergänzt `approved_items`/`scope`):

| # | Vorschlag | Umfang (scope) | Risiko | Abhängigkeiten (alle erledigt) | Abnahmekriterien |
|---|---|---|---|---|---|
| E1 | `files-office-agent`: Agent `files`, der die vorhandenen Tools `files` und `office` über den Router nutzbar macht (löst R2) | `src/jarvis/agents/adapters/files.py`, `agents/factory.py`, `agents/router.py` (Regeln), `tests/test_agents_files.py`, `README.md`, `docs/TESTING.md`; **kein** `bootstrap.py`, **keine** Änderung an Tool-Rechten | mittel: jede Aktion bleibt YELLOW mit Einzelbestätigung, nur bestätigte Wurzeln, kein Löschen, keine Makros | `file-tools`, `office-docs`, `agent-router` | Aufträge laufen nur über `ToolRegistry.execute → PermissionEngine`; Ablehnung/Notaus beenden den Schritt; Journal-Eintrag; Tests mit echter Engine; Standard aus |
| E2 | `nexus-setup-panel`: NEXUS zeigt die Doctor-Ergebnisse (nur lesend: fehlende Pakete/Schlüssel, aktive Subsysteme) und was zu tun ist (löst R8) | `src/jarvis/control_center/` (Ansicht `GET /view/doctor`), `web/`, `tests/test_control_center_*`, `docs/NEXUS_GUI.md` | niedrig: nur lesend, Schlüssel nur „gesetzt/nicht gesetzt“ | `cc-results-audit` | Kein Schreibweg, kein Befehl, nur GET mit Token; Ausgabe ohne Geheimnisse; E2E-Test |
| E3 | Windows-CI: Frisch-Installation (`venv` + `pip install -e ".[dev]"` + `jarvis doctor` + `jarvis-cc` Start/Stop) auf Python 3.13 **und 3.14**, plus Playwright-Chromium für die echten Browser-Tests (löst R3/R6 teilweise) | `.github/workflows/` (**Besitzer-PR**, nicht per Auftrag) | niedrig/mittel (CI-Laufzeit, geschützte Datei) | – | Läuft nur bei relevanten Änderungen; Skips im JUnit sichtbar; kein Pflichtcheck-Wechsel ohne Besitzer |
| E4 | `cli-confirm-timeout` (vorhanden) | `src/jarvis/permissions/confirmation.py` ist geschützt: braucht `sensitive_edits` mit Modus `additive` | mittel (Sicherheitscode) | – | Zeitablauf = abgelehnt, Standard unverändert, Sicherheitstests nur additiv |
| E5 | `audit-hash-chain` (vorhanden) | `permissions/audit.py` geschützt: `sensitive_edits` nötig | mittel/hoch | – | Hash-Kette, Rotation, bestehende Audit-Tests unverändert; später, nicht release-kritisch |
| E6 | `mcp-security-review` (vorhanden) | nur `docs/MCP_SECURITY.md` | niedrig (Doku) | erledigt | wie im Backlog; nicht release-kritisch |
| später | `mail-provider` (nur Lesen/Entwurf zuerst), `media-agent` (nach `os-sandbox-design`), `smartphone-api-design` | – | hoch (Senden, Prozesse) | – | nach stabilem PC-Release |

**Empfohlene Reihenfolge nach der Rückkehr:** zuerst die echte Abnahme (#186), parallel E3 (Besitzer-PR), dann E1 und E2 als einzelne, gedeckelte Aufträge. Der sichere Neustartweg der Kette steht in `.github/automation/README.md` (Abschnitt „Besitzer-Zurückstellung“).

## 8. Stand der Zehn-Aufgaben-Kette (2026-11-09; nichts davon ist gemergt, nichts davon ersetzt #186)
Nachweisstufen: **L** = Linux-Lauf in der Sitzung · **W** = Windows-CI (Runner ohne Mensch) · **I** = interaktive Windows-Abnahme (#186, **ausstehend**).

| # | Aufgabe | PR | Inhalt | Nachweis |
|---|---|---|---|---|
| 1 | E1 Datei-/Office-Agent | #216 | Agent `files` über Router/NEXUS; jede Aktion `ToolRegistry.execute → PermissionEngine`; Änderungen nur hash-geschützt, kein Löschen, Geheimnisse gesperrt | L: grün; W: siehe PR |
| 2 | E2 NEXUS-Setup-Panel | #217 | `GET /view/doctor`, Panel im Experten-Modus, Schlüssel nur gesetzt/nicht gesetzt, keine Aktivierung | L: grün; W: siehe PR |
| 3 | E3 Frischinstallation | #218 (Skript), #219 (Workflow, **Besitzer-Review nötig**) | venv, Install aus Repo, Import/CLI, `jarvis doctor`, `jarvis-cc` Start/Stopp; Matrix Windows/Linux × 3.11/3.13 | L: grün; W: erst nach Lauf von #219 |
| 4 | Datei/Office-E2E | #220 (auf #216 gestapelt) | echter Server → Assistent → Router → Agent → Engine → Tool → Chat/Audit/Verlauf | L: grün |
| 5 | NEXUS Aufgaben-/Ergebnisansicht | #221 | Statusfolge, deutsches Statuswort, Fehlerzeile, Ergebnis ↔ Aufgabe | L: grün |
| 6 | Browserrecherche mit echtem Browser | #222 (Tests), #223 (Workflow, **Besitzer-Review nötig**) | lokale Seite, Widerspruch, Injektion als Daten, fehlende Seite | L: 29 Tests grün; W: erst nach Lauf von #223 (löst R3 teilweise: nur lokaler Server, kein Live-Internet) |
| 7 | Sprachpipeline-Stabilität | #224 | 3 belegte Abstürze (Handler/Lautsprecher/Mikrofon werfen unerwartet) behoben | L: grün; Hardware/Mikrofon **nicht geprüft** |
| 8 | Agentenkoordination/Fehlerwiederherstellung | #225 (auf #220 gestapelt) | Koordination war bereits dicht getestet, kein Produktfehler; E2E-Belege für Fehlerweitergabe und Abbruch | L: grün |
| 9 | Memory/Journal/Resume | #226 | hartes Prozessende, Integrität, Listing startet nichts, Neubestätigung bei Wirkung | L: grün; W: kill-Verhalten nur durch CI belegt |
| 10 | Release-Integration | dieser PR | Matrix, Blocker, Checkliste, README-Korrektur | Dokumentation |

**Gefundene und behobene Fehler:** (a) `tests/test_analysis_integration.py` pinnte die Agentenliste ohne `files` (CI-Fehlschlag in #216, behoben); (b) Sprachsitzung stürzte bei unerwarteten Ausnahmen ab (#224); (c) Rauchtest: `jarvis-cc`-Ausgabe kam auf dem Runner nicht an (Pufferung), behoben in #218/#219 mit ungepuffertem Kindprozess und Diagnoseausgabe.

**Blockerliste (Stand heute):**
1. **#186 interaktive Windows-Abnahme** – ausstehend, Release-Blocker (R1).
2. **Besitzer-Review** der geschützten Workflow-PRs #219 und #223 (`.github/` darf nur der Besitzer freigeben).
3. **Merge-Reihenfolge**: #216 → #220 → #225 (gestapelt); #218 vor #219; #222 vor #223. Kein Merge erfolgt.
4. **Backlog**: E1–E3 sind nur mündlich/im Auftrag freigegeben; die Backlog-Datei wurde **nicht** verändert. Falls die Automatisierungskette sie kennen soll, muss der Besitzer `approved_items` selbst ergänzen.
5. **Offen wie bisher**: echtes LLM (R4), Sprache auf Hardware (R5), Python 3.14 auf Windows (R6; der neue Workflow testet 3.11/3.13, nicht 3.14), OneDrive (R7), Live-Webrecherche (R3 Rest), Mini-Overlay-Details (R9).

**Neue Checklistenpunkte:** [ ] #216/#217/#218/#221/#222/#224/#226 nach grüner Windows-CI zum Merge freigeben (Besitzer) · [ ] #219/#223 prüfen und mergen, danach Lauf auf `main` ansehen · [ ] Schritt 11 und 12 des Abnahmeprotokolls erneut gegen die neuen Stände.
