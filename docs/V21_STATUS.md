# JARVIS V2.1 – Entwicklungsstand (Fortsetzungsdatei)

Stand: 2026-11-13. Diese Datei ist der Einstieg für eine neue Sitzung. Erst `git fetch`, dann die Köpfe unten gegen `git rev-parse origin/<branch>` prüfen.

## Grenzen
- `main` (`7cc65b0`) und `claude/v2-integration` (`7c2b4b7`, Draft-PR #258) bleiben unverändert. Keine PRs, keine Merges, nichts unter `.github/`.
- Alle V2.1-Branches zweigen von `claude/v2-integration` @ `7c2b4b7` ab. Nichts ist verdrahtet (kein Eintrag in `bootstrap.py`, `config`, Server, Webseite); kein Default geändert.
- Verdrahtung, neue Agenten/Fähigkeiten und jede Übernahme brauchen eine ausdrückliche Owner-Freigabe. #186 (Windows-Abnahme) ist weiter offen.

## Branches
| Branch | Mission | Dateien | Neue Tests |
|---|---|---|---|
| `claude/v21-intelligence` | M1, M5 | `src/jarvis/goals/plan_graph.py`, `src/jarvis/goals/decision.py`, `tests/test_v21_plan_graph.py`, `tests/test_v21_coordination.py` | 42 |
| `claude/v21-strategist` | M2 | `src/jarvis/business/strategist.py`, `tests/test_v21_business_strategist.py` | 35 |
| `claude/v21-memory-quality` | M3, M7 | `src/jarvis/memory/project_memory.py`, `src/jarvis/quality/engine.py`, je eine Testdatei | 39 |
| `claude/v21-lab-bench` | M4, M8 | `src/jarvis/lab/evaluate.py`, `scripts/bench/v21_bench.py`, `tests/test_v21_lab.py`, `tests/test_v21_bench.py` | 23 |
| `claude/v21-nexus` | M6 | `src/jarvis/control_center/mission_view.py`, `tests/test_v21_mission_view.py`, diese Datei | 11 |

Die Köpfe und CI-Läufe stehen im jeweils letzten Bericht der Sitzung; maßgeblich ist `git log origin/<branch>`.

## Abhängigkeiten (wer braucht wen bei der späteren Verdrahtung)
| Baustein | nutzt heute | braucht für die Verdrahtung |
|---|---|---|
| M1 Plananalyse/Vergleich | `goals.policy` (Grenzen, Fehlercodes) | GoalEngine-Planer (Aufruf vor dem Start), M7 als Qualitätstor |
| M2 Strategist | `business.calc`, `business.finder` (Score) | Research-Agent (Fakten mit Quelle), Artefakte (E5), Agentenbudget (WP02b), M7 |
| M3 Projektgedächtnis | `redaction.SecretDetector` | Persistenz (bestehender SQLite-Speicher), M6-Anzeige |
| M4 Bewertungslabor | nichts (reine Daten) | M8-Ausgabe und JUnit-Berichte als Eingabe; `[self_improvement]` bleibt gesperrt |
| M5 Koordination | bestehender Orchestrator (nur Tests) | M7 für widersprüchliche Ergebnisse |
| M6 Ansichtsmodell | `redaction.SecretDetector` | Daten aus M1, M2, M3, M7; Route im Server und Seite (nicht gebaut) |
| M7 Quality Engine | nichts (Rechner werden hereingereicht) | Aufruf nach jedem Agentenergebnis, `business.calc` als Rechner |
| M8 Benchmark | bestehende Komponenten | Zielwerte des Owners (G5) |

Reihenfolge für eine Integration: M7 → M1 → M3 → M2 → M5-Ergänzung → M6 → M4/M8 (unabhängig).

## Offen
- M5: Test „widersprüchliche Ergebnisse zweier Agenten“ fehlt; er braucht M7 (`quality.conflicts`) und den Orchestrator im selben Checkout.
- M2: kein registrierter Agent (neue Fähigkeit/Aufgabenart nötig; die Listen sind durch Tests fixiert → Owner-Entscheidung).
- M3: nur im Speicher (`to_dict`/`from_dict`), keine Datei-Persistenz; Kontext-Wiederherstellung nur über diese beiden Funktionen.
- M4: keine Testgenerierung, keine Patch-Vorschläge als Code – Code-Vorbereitung ist in `[self_improvement]` bewusst gesperrt.
- M6: nur das Datenmodell; keine Route, kein HTML/JS, keine Fensterabnahme.
- M8: nicht gemessen sind CPU-Last, LLM-Kosten, Tool-Latenz echter Werkzeuge und alles am Owner-PC.
- Befund Not-Aus: Der Orchestrator nimmt nach dem Not-Aus direkt eingereichte Aufgaben noch an (Einstiegspunkte und jeder Werkzeugaufruf verweigern). Nur als Test dokumentiert; Änderung braucht Freigabe.
- Befund Detektor: `SecretDetector` erkennt `Bearer <token>` nicht; das Projektgedächtnis fängt es lokal ab.
- Bekannt rot (lokal, mit `origin/main`): `test_the_ui_tool_only_touches_computer_and_documentation_files` (N3, in der CI übersprungen).
- Beobachtet: `tests/test_control_center_server.py::test_oversized_command_rejected_before_parsing` einmal rot auf Windows (WinError 10053), bestehender Test, nicht im V2.1-Diff.

## Nächster Schritt
1. CI-Ergebnisse (pr-tests per `workflow_dispatch`, Linux und Windows getrennt) der fünf Branches prüfen; Skip-Baseline Linux 120 / Windows 46.
2. Mit Owner-Freigabe: Integrationsbranch `claude/v21-integration` aus den fünf Branches (keine gemeinsamen Dateien erwartet) und dort den M5-Widerspruchstest ergänzen.
3. Owner-Entscheidungen einholen: Strategist als Agent, Orchestrator-Verhalten nach Not-Aus, Bearer-Token im gemeinsamen Detektor.

## Tests ausführen
```
PYTHONPATH=src python -m pytest -rfEs tests/test_v21_*.py
PYTHONPATH=src python -m pytest -rfEs tests/test_*security*.py tests/test_emergency_stop.py
```
