# Entwicklungs-Backlog PC-Version (Windows)

Stand: 2026-10-28, `main` = 01f6829. Quelle: tatsächlicher Code- und CI-Stand, nicht nur die README. Die maschinenlesbare Form für die
Automatisierung ist `.github/automation/backlog.json` (Freigabe dort per `approved`, nur der Besitzer ändert sie).

## Bestandsaufnahme (belegt)

| Bereich | Stand | Beleg |
|---|---|---|
| Phase 1–10 (Core, Voice, Memory, Computer, Browser, Coding, Multi-Agent, Goal Engine, Self-Repair, Research/Business/Finance) | implementiert, getestet | volle Suite auf Linux: Exit 0 (`pytest`, Stand 01f6829); Windows-Laufzahlen siehe `docs/TESTING.md` |
| Phase 11 GUI | implementiert (Text, Sprache, Status, Bestätigung, Notaus, laufende Arbeit) | GUI-Tests auf Windows-Runner (`docs/TESTING.md`); Mikrofon/Lautsprecher bleiben manuell |
| Phase 13 Security | implementiert | `permissions/`, Sicherheits- und Invariantentests |
| Phase 14 | Teilziel 1 (Notaus), 2 (Sichtbarkeit), 3 (Invarianten, PR #13) fertig; **4 (Gesamtbudget) freigegeben, offen**; 5 (Hintergrund/Selbststart/Fernsteuerung) nur mit neuer Entscheidung | `docs/PHASE14_AUTONOMY.md`, `backlog.json` |
| Phase 15 | deaktivierter Vorschlagsworkflow, keine Sandbox | README „Self-Improvement“ |
| Phase 12 Smartphone | nicht begonnen (zuletzt) | – |
| GitHub-Automatisierung | Start, Bericht, Watchdog, Controller, `pr-tests` (Linux+Windows), Merge-Gate laufen auf `main` | Workflow-Läufe auf `main` erfolgreich (Gate, Controller, Report, Watchdog) |

Echte Lücken gegenüber „fertig“ (aus Code und „Bekannte Grenzen“, nicht aus Wunschlisten):
1. Ziele, Agenten-Aufgaben, Reparaturläufe und Task-Ergebnisse liegen nur im Speicher (`tasks/manager.py`: „In-memory“).
2. Windows: Bildschirmaufnahme (`mss`) und Eingabe (`pyautogui`) nur gegen Fakes getestet; Win32-Fensterprovider hat echte Windows-Tests. Coding-Testläufe beenden unter Windows nur den Wurzelprozess.
3. Echte Browser-Tests (Playwright) laufen in der CI nicht (Browser nicht installiert) – braucht eine Workflow-Änderung (Besitzer).
4. Kein Einstieg für Erstnutzer auf Windows (keine Diagnose, keine Erstkonfiguration).
5. Memory ohne semantische Suche; Voice ohne Unterbrechen/lokales Hotword.
6. Audit-Log ohne Hash-Kette/Rotation, CLI-Bestätigung ohne Zeitlimit (beides `permissions/`, Besitzer).
7. Dokumentation hinkt hinterher (README-Status, `TESTING.md`-CI-Tabelle nennt noch den alten Branch).

## Priorisierter Backlog

| # | ID | Inhalt | Freigabe | Merge |
|---|---|---|---|---|
| 1 | `session-budget` | Phase 14 Teilziel 4: Gesamtbudget (bereits freigegeben) | ja | Besitzer (`permissions/`, `bootstrap.py`) |
| 2 | `windows-capture-tests` | Echte Windows-Tests für `mss`-Aufnahme/Monitore (keine Eingabe, nichts wird geklickt) | vorgeschlagen ja | automatisch |
| 3 | `coding-windows-process-tree` | Coding-Testlauf beendet unter Windows den ganzen Prozessbaum (Job Object, vorhandenes `winjob`) | vorgeschlagen ja | automatisch |
| 4 | `persistent-results` | Ziele/Reparaturen/Tasks-Ergebnisse überleben Neustart (nur Historie; nichts läuft nach Neustart automatisch weiter) | vorgeschlagen ja | Besitzer, falls `bootstrap.py` berührt |
| 5 | `onboarding-windows` | `jarvis doctor` (Diagnose) + Erststart-Konfiguration + Windows-Schnellstart | vorgeschlagen ja | automatisch |
| 6 | `memory-semantic-search` | Lokale, netzfreie semantische Suche hinter `MemoryStore` | vorgeschlagen ja | automatisch |
| 7 | `voice-barge-in-hotword` | Unterbrechen beim Sprechen, lokaler Hotword-Detektor (mit Fake-Audio testbar) | vorgeschlagen ja | automatisch |
| 8 | `docs-sync` | README-Status, `TESTING.md` (CI-Tabelle, Läufe), Phase-Tabellen angleichen | vorgeschlagen ja | automatisch |
| 9 | `audit-hash-chain` | Hash-verkettetes Audit-Log + Rotation | **nein** (sicherheitskritisch) | Besitzer |
| 10 | `cli-confirm-timeout` | Zeitlimit für CLI-Bestätigung (Ablehnung bei Ablauf) | **nein** | Besitzer |
| 11 | `llm-goal-planning` | LLM-gestützte Zielzerlegung statt 3 Vorlagen, mit bestehender Planprüfung | **nein** (Autonomie) | Besitzer |
| 12 | `coding-llm-edits` | Coding-Agent entwirft Änderungen selbst (heute nur übergebene `edits`) | **nein** (Autonomie) | Besitzer |
| 13 | `smartphone-api-design` | Phase 12: nur Entwurf (Schnittstelle, Bedrohungsmodell), kein Code | **nein** (Fernsteuerung) | Besitzer |

Bewusst nicht im Backlog: Phase 14 Teilziel 5 (Hintergrundziele, Selbststart), Phase-15-Ausführung/Sandbox, Echtgeld-Handel, automatische Installation von Fähigkeiten.
Das sind neue Autonomie bzw. Sicherheitsgrenzen und brauchen eine eigene Entscheidung des Besitzers.

## Owner-Aktionen außerhalb des Backlogs (geschützte Pfade, je eigener PR)
- Playwright-Browser in `pr-tests`/`tests.yml` installieren, damit `tests/test_browser_real.py` auf Windows und Linux wirklich läuft (heute übersprungen).
- Variablen `JARVIS_AUTO_CONTINUE_ENABLED` / `JARVIS_AUTO_MERGE_ENABLED` erst nach den ersten beobachteten Statusberichten setzen; Limits (`chain_budget` ≤ 5, Tageslimit, 3 Korrekturen) bleiben unverändert.

## Was automatisch läuft – und was nicht
Mit den Variablen aus dem Automatisierungs-README startet der Controller nur Backlog-Schritte mit `approved: true`, einen aktiven Auftrag zugleich, höchstens 5 je Kette.
Ohne gesetzte Variable und ohne gestarteten Auftrag arbeitet **nichts** unbeaufsichtigt weiter. Ein Auftrag wird per Workflow „Trigger Claude Code Routine“ gestartet.
