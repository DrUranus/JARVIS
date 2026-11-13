# V2.1 – Architektur, Abhängigkeitsmatrix und Integrationsvorbereitung (M1–M8)

Stand: Vorbereitung, **nichts ist gepusht, kein PR, kein Merge**. Alle V2.1-Zweige liegen auf `claude/v2-integration` (Commit `7c2b4b7`), das **selbst noch nicht in `main` ist**
(`main` steht auf `7cc65b0e`). Die Reihenfolge unten gilt daher erst nach dem Besitzer-Merge von `claude/v2-integration`.

Legende „Stand“: **Kern** = reine, getestete Logik ohne Verdrahtung · **Verdrahtet (aus)** = in `bootstrap.py`/Fabrik eingehängt, Standard aus · **Konzept** = nur Dokument.

## 1. Die acht Missionen

| M | Name | Zweig / Commit | Stand | Dateien |
|---|---|---|---|---|
| M1 | Plananalyse (Abhängigkeitsgraph, Wellen, Neuplanung, Wiederaufnahme) | `claude/v21-intelligence` `91471bc` | Kern | `goals/plan_graph.py` |
| M2 | Business Strategist | `claude/v21-strategist` `ace5a84` (Kern) + `claude/v21-strategist-agent` (Agent) | Kern + **Agent verdrahtet (aus)** | `business/strategist.py`, `business/strategist_agent.py`, `agents/policy.py`, `agents/factory.py`, `config.py` |
| M3 | Projektgedächtnis | `claude/v21-memory-quality` `d39f508` | Kern | `memory/project_memory.py` |
| M4 | Self-Improvement Lab | `claude/v21-m4-lab-concept` | **Konzept** (keine Implementierung) | `docs/V21_M4_SELF_IMPROVEMENT_LAB.md` |
| M5 | Vorgehensvergleich und Koordination | `claude/v21-intelligence` | Kern | `goals/decision.py` |
| M6 | NEXUS Mission Control | `claude/v21-mission-control` | **Verdrahtet** (nur lesende Ansicht; Anzeige nur mit `control_center.enabled`) | `control_center/mission.py`, `views.py`, `server.py`, `launcher.py`, `web/*` |
| M7 | Quality Engine | `claude/v21-memory-quality` | Kern | `quality/engine.py` |
| M8 | Lab-Bench (Mikro-Benchmarks) | `claude/v21-lab-bench` `c8be7d1` | Werkzeug (Skript, nur Messung) | `scripts/bench/v21_bench.py` |

Querschnitt (kein M, aber V2.1-Aufträge): Not-Aus-Guard im Orchestrator (`claude/v21-estop-orchestrator`) und Bearer-Erkennung (`claude/v21-bearer-detection`).

## 2. Abhängigkeitsmatrix

Zeile **braucht** Spalte. `●` = harte Laufzeit-/Importabhängigkeit, `○` = lose Kopplung über übergebene Funktion/Daten (kein Import), `·` = keine.

| braucht → | M1 Plan | M2 Strat. | M3 Gedächtnis | M4 Lab | M5 Vergleich | M6 Mission | M7 Qualität | M8 Bench | Orchestrator | Notaus | Redaktion |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **M1 Plan** | – | · | · | · | · | · | · | · | ○ (`from_steps` adaptiert `GoalStep`) | · | · |
| **M2 Strategist** | · | – | · | · | · | · | · | · | ● (Agent, ohne Tools) | ● (über Guard) | ● |
| **M3 Gedächtnis** | · | · | – | · | · | · | · | · | · | · | ● (`SecretDetector`) |
| **M4 Lab** (Konzept) | ○ | · | · | – | · | · | ○ (Qualitätstor) | · | ○ | ● | ● |
| **M5 Vergleich** | · | · | · | · | – | · | · | · | · | · | · |
| **M6 Mission** | ○ (Graph später aus M1) | ○ (Ergebnisse) | ○ (Quelle offen) | · | · | – | ○ (Quelle offen) | · | ○ (nur `list`/`describe`) | · | ● |
| **M7 Qualität** | · | ○ (`calculators` aus `business.calc`) | · | · | · | · | – | · | · | · | · |
| **M8 Bench** | ○ (misst M1/M5) | ○ | ○ | · | ○ | · | ○ | – | ○ (FakeAgents) | · | · |

Wichtig: M1, M3, M5, M7 sind **schichtrein** (importieren keine andere V2.1-Schicht; M7 bekommt Fachrechnungen hereingereicht, M1/M5 importieren nur `goals.policy`). Dadurch gibt es **keine Importzyklen** und jede Mission kann einzeln integriert werden.

## 3. Vorhandene Komponenten, die wiederverwendet werden (keine Doppelung)

| Bedarf | Vorhanden (V2.0) | V2.1 nutzt es durch |
|---|---|---|
| Agentenausführung, Budgets, Zeitlimits | `agents/orchestrator.py`, `agent_budgets.py` | M2 ist ein gewöhnlicher `Agent` (id `strategist`) – keine zweite Orchestrierung |
| Berechtigungen | `ToolRegistry.execute → PermissionEngine` | M2 hat **keine Tools**; M6 liest nur; M4 ändert nichts daran |
| Geschäftsrechnung | `business/calc.py`, `business/finder.py` | M2-Kern ruft sie auf („keine zweite Rechenmaschine“); M7 bekommt `calc` als `calculators` |
| Recherche-Übergabe | `research/handoff.py` (`collect`) | M2 übernimmt Quellen aus Elternaufgaben wie der `BusinessAgent` |
| Geheimnisschutz | `redaction.SecretDetector` (jetzt mit Bearer) | M3, M6, Orchestrator, Speicher, Audit |
| Not-Aus | `permissions/emergency.py` (unverändert) | Orchestrator-Guard liest nur den Latch |
| Lesende Ansichten | `control_center/views.py` + Server | M6 als sechste, nur lesende Ansicht |
| Selbstverbesserung | Phase 15 (`self_improvement/`) | M4 beschreibt nur die gesperrte Strecke zwischen `PROPOSED` und `READY_FOR_APPROVAL` |
| Plan/Ziele | `goals/` (Engine, Planner, Replanner) | M1/M5 sind reine Analysen; die `GoalEngine` bleibt einziger Ausführer |

## 4. Neue Schnittstellen (vollständig)

| Schnittstelle | Ort | Art | Wirkung |
|---|---|---|---|
| `AgentOrchestrator(stop_guard=...)`, `build_agents(..., stop_guard=...)` | `agents/orchestrator.py`, `agents/factory.py` | Konstruktorparameter (Standard `None` = unverändert) | liest nur den Latch; nach Not-Aus keine Annahme/Start (`error_code = emergency_stop`) |
| `bootstrap.emergency_guard(core)` | `bootstrap.py` | reine Lesefunktion; `speech_guard` delegiert dorthin | – |
| Fähigkeit `business.strategy` | `agents/policy.py` | neu in `KNOWN_CAPABILITIES` | nicht planner-wählbar, nicht `REPLAN_AUTHORABLE` |
| `StrategistAgent` (id `strategist`) | `business/strategist_agent.py` | Agent ohne Tools | nur bei `business.strategist = true` und `agents.enabled` |
| `BusinessSettings.strategist` | `config.py` | Schalter (Standard `false`), Umgebung `JARVIS_BUSINESS_STRATEGIST` | **kein Eintrag in `config/jarvis.toml`** (die Datei ist hash-geschützt) |
| `SecretDetector`-Muster „Bearer token“ (2) | `redaction.py` | zwei zusätzliche Muster vor „credential statement“ | erkennt/schwärzt Bearer-Token vollständig |
| `MissionView.snapshot(limit)`, `ReadViews.mission`, `/view/mission` | `control_center/*` | GET, nur lesend | Graph, Agenten, Budget, Fortschritt, Qualität, Business, Gedächtnis |
| Quellfunktionen `budget_source`, `business_source`, `quality_source`, `memory_source` | `control_center/mission.py` | Rückrufe | M7/M3 sind noch **nicht** angebunden (Abschnitt 8) |

Quell-Verträge für die noch offenen Anbindungen (Form, die `MissionView` erwartet): `quality_source(limit) -> [{task_id, accepted, failed[], unknown[], self_reported}]` (entspricht
`Verdict.to_dict()`); `memory_source() -> [{project, counts{kind:n}, conflicts, stale, suggestions}]` (aus `ProjectMemory`: `recall`/`conflicts`/`suggestions` je Projekt zusammenzählen).

## 5. Sicherheitsgrenzen je Mission

| M | Grenze | Beleg (Test) |
|---|---|---|
| M1 | rein; führt nichts aus, vergibt nichts; Neuplanung nie für fatale Codes, nie mit neuer Fähigkeit | `test_v21_plan_graph.py` |
| M2 | keine Tools, keine externen Aktionen (`external_action_not_supported`), Standard aus, nicht planner-wählbar, keine Artefakte (E5-Erlaubnisliste unberührt) | `test_v21_strategist_agent.py`, `test_analysis_security.py` |
| M3 | Projekte strikt getrennt, Geheimnisse und personenbezogene Daten abgelehnt, nichts wird still überschrieben | `test_v21_project_memory.py` |
| M4 | Konzept; kein Code, kein Schalter | `docs/V21_M4_SELF_IMPROVEMENT_LAB.md` |
| M5 | ordinal, keine Wahrscheinlichkeit; fehlende Rechte nur als nötige Freigaben | `test_v21_coordination.py` |
| M6 | nur GET, nur Quellfunktionen, keine Importe von Rechten/Werkzeugen/Agenten, keine Schreibnamen, Texte nur per `textContent`, keine neue Bibliothek | `test_control_center_mission.py` |
| M7 | ein „Erfolg“ des Agenten entscheidet nichts; ungeprüft = nicht angenommen | `test_v21_quality_engine.py` |
| M8 | nur Messung, Attrappen, kein Netz | `test_v21_bench.py` |
| Not-Aus | Orchestrator nimmt nach Latch nichts an, startet nichts; fail-closed; Reset ohne Sonderpfad | `test_agents_orchestrator_estop.py` |
| Bearer | bestehende Regeln unverändert und in unveränderter Reihenfolge | `test_redaction_bearer.py` |

## 6. Konflikte mit V2.0 (gefunden bei der Integration)

| # | Konflikt | Auflösung | Bewertung |
|---|---|---|---|
| K1 | `tests/test_agents_security.py` pinnt `KNOWN_CAPABILITIES` exakt | `business.strategy` ergänzt; Aussagen „keine shell/git/install/network/… Fähigkeit“ unverändert | **Vertragserweiterung, Besitzer bitte bestätigen (D-A)** |
| K2 | `VIEW_PATHS` ist exakt auf fünf Ansichten gepinnt; `fetch`-Ziele in `app.js` sind exakt gepinnt | je **ein** Eintrag ergänzt (`/view/mission`, `view/mission`); GET-only-Prüfungen unverändert | **Vertragserweiterung, Besitzer bitte bestätigen (D-B)** |
| K3 | E5-Wächtertests erlauben nur Orchestrator und Recherche-Übergabe den Import von `agents.artifacts` | **nicht** geändert; Strategist liefert daher **keine typisierten Artefakte** | offen (D-C) |
| K4 | `config/jarvis.toml` und `test_autonomy_invariants.py` sind hash-geschützt | kein TOML-Eintrag für `business.strategist`; Standard nur im Code | Standard bleibt aus; Dokumentation im README später |
| K5 | `goals/plan_graph.NEVER_REPLAN` kannte den neuen Task-Code `emergency_stop` nicht | in der Integrationsvorbereitung ergänzt (mit Test) | behoben |
| K6 | Die `GoalEngine` ersetzt nur `FAILED/TIMEOUT` mit wiederholbarem Code; `BLOCKED/emergency_stop` wird nie neu geplant | kein Konflikt, per Test gesichert | ok |
| K8 | `tests/test_computer_uia_tools.py::test_the_ui_tool_only_touches_computer_and_documentation_files` vergleicht `origin/main...HEAD` und verbietet jede Änderung an `bootstrap.py` (einmalige Prüfung der UI-Tool-Arbeit, wirkt aber dauerhaft). Der Not-Aus-Guard muss laut Regel „Verdrahtung nur in `bootstrap.py`“ dort eingehängt werden | **nicht geändert**; der Test schlägt auf `claude/v21-estop-orchestrator` (und der Integrationsprobe) fehl, sobald `origin/main` im Checkout liegt | **offene Besitzerentscheidung (D-D)**: Test auf seinen ursprünglichen Zweck begrenzen oder Ausnahme freigeben |
| K9 | `test_v21_coordination` dokumentierte als „BEFUND“, dass der Orchestrator nach Not-Aus noch Aufgaben annahm | Test auf die verschärfte Zusicherung umgestellt (BLOCKED, Agent nie gestartet) – Verschärfung, keine Abschwächung | behoben |
| K7 | Python-Subprozess-Tests mit `-I` brauchen ein installiertes `jarvis` (`pip install -e`) | keine Codeänderung; Umgebungsthema der lokalen Prüfung | siehe Bericht |

## 7. Integrationsreihenfolge (nach Merge von `claude/v2-integration`)

1. **Bearer-Erkennung** (`claude/v21-bearer-detection`) – kleinster Eingriff, nur zusätzliche Regeln; verbessert sofort Memory/Audit/Journal.
2. **Not-Aus im Orchestrator** (`claude/v21-estop-orchestrator`) – Sicherheitsverstärkung, Voraussetzung dafür, dass spätere neue Agenten sofort mitgeschützt sind. Vor allem anderen mit Agenten.
3. **M2 Strategist-Kern + Agent** (`claude/v21-strategist` → `claude/v21-strategist-agent`) – erst nach (2). Standard aus.
4. **M3 und M7** (`claude/v21-memory-quality`) – reine Kerne; danach Quellfunktionen für M6 anbinden (kleine Adapter in `launcher.py`).
5. **M1 und M5** (`claude/v21-intelligence`) – reine Kerne; Verdrahtung in die `GoalEngine` ist eine **eigene, ausdrücklich freizugebende** Phase-14-Aufgabe.
6. **M6 Mission Control** (`claude/v21-mission-control`) – nach 3 und 4, damit die Abschnitte Business/Qualität/Gedächtnis Daten haben; die Ansicht selbst ist unabhängig lauffähig.
7. **M8 Bench** (`claude/v21-lab-bench`) – jederzeit; misst nur.
8. **M4** – Konzept, nur Dokument; Umsetzung erst nach Entscheidungen D1–D8 im Konzept.

Die lokale Probe-Zusammenführung `claude/v21-integration-prep` (alle acht Zweige in dieser Reihenfolge-unabhängigen Mischung auf `claude/v2-integration`) ist **konfliktfrei** und liegt nur lokal vor.

## 8. Noch fehlende Funktionen

- **Verdrahtung von M7 (Quality Engine)** und **M3 (Projektgedächtnis)** in Orchestrator/Zielmotor bzw. als Quelle für M6 – bewusst nicht begonnen (Phase 14 verlangt je Teilziel eine Freigabe).
- **Anbindung von M1/M5** an die `GoalEngine` (Planungswellen, Neuplanung, Wiederaufnahme, Vorgehensvergleich im Planer).
- **Typisierte Artefakte des Strategist** (E5-Allowlist, siehe K3).
- **Persistenz** des Projektgedächtnisses (nur Snapshot `to_dict/from_dict` vorhanden; Speicherort zu entscheiden).
- **M4-Umsetzung** (Sandbox-Backend, Paketformat, Notaus-Stopper des Labs).
- **Strategist in Zielvorlagen** (`goals/planner.py`): bewusst nicht aufgenommen, damit kein Planer und kein Modell den Agenten unaufgefordert wählt.
- **README/Abschnitt in `docs/TESTING.md`** für die neuen Tests und den Schalter `business.strategist` (die Dateien sind nicht Teil dieser Aufträge).
- **Windows-Nachweis** aller neuen Teile (CI-Windows-Lauf je Zweig) und Chromium-E2E der Mission-Control-Oberfläche.
