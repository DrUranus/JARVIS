# V2.1 – Integrationsbericht

Datum 2026-11-13. Integrationsbranch **`claude/v21-integration`**, lokal, **nicht gepusht**, kein PR. Basis: `claude/v2-integration` @ `7c2b4b7` (CI Linux und Windows grün). `main` (`7cc65b0`) und `claude/v2-integration` sind unverändert; nichts unter `.github/`.

## 1. Tatsächlicher Branch-Stand
Siehe Matrix in `ARCHITEKTUR.md` Abschnitt 0. Kurz: elf `claude/v21-*`-Branches, alle auf `7c2b4b7`. Nachfolger: `strategist` → `strategist-agent`; lokal ersetzt: `integration-prep` → `integration`. Duplikate: Windows-Fix des Benchmarks (`lab-bench` ≙ `bench-winfix`), Mission-Control-Modell (`mission-control` ≙ `nexus`).

CI je Remote-Kopf (Stand der Abfrage; ein Lauf gilt nur für genau diesen Commit):

| Branch / Commit | Linux | Windows |
|---|---|---|
| `intelligence` `91471bc` | grün | grün (der frühere rote Lauf war ein Flake: `WinError 10053` in `test_oversized_command_rejected_before_parsing`, bestehender Test; Wiederholung grün) |
| `strategist` `ace5a84` | grün | grün |
| `memory-quality` `d39f508` | grün | grün |
| `lab-bench` `8458f73` | grün | grün |
| `nexus` `d1b810f` | grün | grün |
| `strategist-agent` `915a5a7` | grün | **offen** (läuft) |
| `estop-orchestrator` `b27c243` | grün | **offen** (läuft) |
| `bearer-detection` `0299291` | grün | **offen** (läuft) |
| `mission-control` `c18e3a1` | grün | **offen** (läuft) |
| `bench-winfix` `bb3e23b`, `m4-lab-concept` `308c61d` | nicht gestartet | nicht gestartet (Duplikat bzw. nur Doku) |
| **`claude/v21-integration`** (lokal) | lokal grün bis auf Abschnitt 5 | **Windows-Nachweis ausstehend** (nicht gepusht, daher kein CI-Lauf möglich) |

## 2. Integrationsreihenfolge (so gebaut)
1 Bearer → 2 Not-Aus → 3 Gedächtnis/Qualität (M3/M7) → 4 Plan/Vergleich (M1/M5) → 5 Strategist (Kern + Agent, M2) → 6 Lab-Bench (M8 + M4-Kern) → 7 Mission Control (M6) → 8 M4-Konzept. Danach Integrationsarbeit (Abschnitt 3). Alle Merges konfliktfrei; keine doppelten Commits.

## 3. Zusammengeführte Komponenten und eigene Integrationsarbeit
- **Strategist** als Agent `strategist`, Fähigkeit `business.strategy`, keine Tools, Standard aus (`business.strategist`), nur ausdrückliche Auswahl (nie Planer-/Router-/Replan-wählbar), keine externen Aktionen, Budgets/Zeitlimits/Not-Aus über den bestehenden Orchestrator, **keine** neue E5-Artefaktfreigabe, **keine** zweite Business-Rechnung (nutzt `business.calc`/`finder`).
- **Not-Aus**: Orchestrator-Guard (read-only, fail-closed, unter dem Orchestrator-Lock geprüft → keine Starts nach sichtbarem Halt, kein Deadlock), `emergency_stop` zusätzlich in `plan_graph.NEVER_REPLAN`; `test_v21_coordination` von „BEFUND dokumentiert“ auf die verschärfte Zusicherung umgestellt.
- **Bearer**: zwei Muster vor „credential statement“; bestehende Regeln und ihre Reihenfolge unverändert.
- **M3+M7**: Integrationstests (Projekttrennung, Widersprüche, Quellen, Budget, Persistenz nur als Snapshot, Geheimnisse, keine I/O, nirgends verdrahtet); `ProjectMemory.overview()` (nur Zähler).
- **Mehragenten-Tests**: widersprüchliche Ergebnisse (M5-Lücke geschlossen), 10 laufende + 10 wartende Agenten bei Not-Aus, keine doppelten externen Aktionen, Neuplanung nur nach Absturz, nie nach Budgetüberschreitung/Not-Aus. (10 parallele Agenten, Absturz, Hänger, Budget, Wiederaufnahme standen bereits in `test_v21_coordination.py`.)
- **Mission Control**: `/view/mission` (nur GET) + Panel im bestehenden Design, ohne neue Bibliothek; aus dem Prototyp `nexus` übernommen: Fehlercodes und „blockiert durch Fehlschlag“. Pins für Route/Fetch um genau diesen Eintrag erweitert (genehmigt).
- **M4**: Konzept + Bewertungskern; zwei Integrationsfehler behoben (K10, K11). D1–D8 stehen unverändert offen (`M4_SELF_IMPROVEMENT_LAB.md` §9), nichts wurde geraten.

## 4. Konflikte
K1–K12 in `ARCHITEKTUR.md` §6. Inhaltliche Merge-Konflikte: keine. Vertragsänderungen (genehmigt): `KNOWN_CAPABILITIES` + `business.strategy`; Route-/Fetch-Pins + `mission`. Historischer Wächterkonflikt K8 (UIA-Bereichswächter) bleibt **rot** und unverändert; enge Zusatzprüfung `test_v21_bootstrap_wiring.py` ist grün.

## 5. Testergebnisse (Linux, lokal, ein sequenzieller Volllauf auf `claude/v21-integration`, Commit `8234308`)
Gezielte Suiten vor dem Volllauf grün (alle `test_v21_*`, Not-Aus, Bearer, Mission, Wächter, Sicherheit).
Volllauf: **53 Fehlschläge**, 99 Skips (Obergrenze der Baseline Linux 120). Einordnung:

| Klasse | Anzahl | Beschreibung |
|---|---|---|
| Produktfehler | 0 | – |
| Testfehler | 0 | – |
| Umgebung | 52 | `openpyxl` fehlt (`test_office.py` ×48, `test_agents_files` ×1); drei Importtests mit `python -I` brauchen ein installiertes `jarvis` (`pip install -e`, ohne Freigabe nicht ausgeführt). Dieselben Fälle sind auf der unveränderten Basis `7c2b4b7` rot. |
| Historischer Wächterkonflikt | 1 | `test_computer_uia_tools::test_the_ui_tool_only_touches_computer_and_documentation_files` (siehe K8) |

Reparaturschleifen: je Klasse höchstens eine. **Windows-CI für die Integration: nicht gelaufen** (kein Push); Windows-Ergebnisse gelten nur für die in Abschnitt 1 genannten Einzelcommits und sind teils noch offen.

## 6. Sicherheitsnachweise
- Not-Aus: `test_agents_orchestrator_estop.py` (parallel, deterministisch, Wiederholung 3×; Mutation „Guard aus“ macht die Tests rot), `test_v21_multiagent_integration.py`, `test_emergency_stop.py` unverändert grün.
- `PermissionEngine`, `emergency.py`, X0, Hash-Manifest (N3-D) und bootstrap-AST (N3-B): unverändert bzw. grün (`test_protected_files.py`).
- Bearer: `test_redaction_bearer.py` (Header, Schreibweisen, synthetische Tokens, False Positives, kein Klartext in Beschreibung/Log, bestehende Regeln).
- Strategist: `test_v21_strategist_agent.py`, `test_analysis_security.py`, E5-Wächter (`test_agent_artifacts*.py`) unverändert grün.
- Phase 15: `test_v21_lab_integration.py` (Sperre, reservierte Schlüssel, Lab nirgends verdrahtet, `may_apply = False`).
- Mission Control: nur GET (PUT/DELETE/PATCH 405, POST 404), keine verbotenen Importe/Schreibnamen, keine neuen Ereignisse im UI-Kanal.
- Keine produktive Aktivierung: alle neuen Schalter aus; M3/M7/M1/M5/M4 nirgends verdrahtet (per Test).

## 7. Noch blockierte Integrationspunkte
- Verdrahtung M7 (Qualitätstor nach Agentenergebnissen) und M3 (Persistenz, Quelle für Mission Control), M1/M5 in die `GoalEngine`: je eigene Phase-14-Freigabe.
- Artefakte des Strategist: E5-Allowlist (zwei Wächtertests) – nicht freigegeben.
- Windows-Nachweis der Integration; Chromium-E2E des neuen Panels.
- M4-Ausführungsstrecke (Sandbox): D1–D8.

## 8. Fortschritt M1–M8
M1 Kern ✔ (unverdrahtet) · M2 Kern + Agent ✔ (aus) · M3 Kern ✔ + Integrationstests, Persistenz offen · M4 Konzept + Bewertungskern ✔, Ausführung gesperrt · M5 Kern ✔, Widerspruchstest ✔ · M6 verdrahtet ✔ (lesend), Quellen M3/M7 offen · M7 Kern ✔ + Integrationstests, unverdrahtet · M8 Skript ✔, Windows grün auf `8458f73`.

## 9. Nächste Schritte nach V2.0
1. Besitzer-Merge `claude/v2-integration` → `main` (Voraussetzung für alles).
2. Windows-CI für `claude/v21-integration` (Push-Freigabe nötig) und Chromium-E2E.
3. Entscheidungen aus Abschnitt 10; danach M7 als Qualitätstor, M3-Persistenz, M1/M5 in den Planer – jeweils einzeln, standardmäßig aus.
4. README/`docs/TESTING.md` um die neuen Tests und Schalter ergänzen (nicht Teil dieses Auftrags).

## 10. Entscheidungen, die Ihre Freigabe brauchen
1. **Push** von `claude/v21-integration` für den Windows-Lauf (und danach ein PR gegen `claude/v2-integration`, nicht `main`)?
2. **K8**: historischen UIA-Bereichswächter nach Prüfung der engen Zusatzprüfung begrenzen/freigeben – oder die Verdrahtung anders lösen?
3. **E5-Allowlist** erweitern, damit der Strategist typisierte Artefakte liefern darf?
4. **Phase-14-Freigaben** je Teilziel: M7-Qualitätstor, M3-Persistenz (Ort, Format), M1/M5-Planeranbindung.
5. **M4 D1–D8** (`M4_SELF_IMPROVEMENT_LAB.md` §9): Sandbox-Backend, `EXPORTED`-Zustand, Paketort/Aufbewahrung, Installationsrechte, Speicher-Sicherung, Erweiterungsverfahren der Erlaubnisliste, Tests des Vorschlags, Modellnutzung.
6. Umgang mit den Duplikatzweigen `bench-winfix` und `nexus` (behalten als Referenz oder löschen – Löschen wurde nicht vorgenommen).
7. Installation von `pip install -e ".[dev]"` freigeben, damit die 52 Umgebungsfehler lokal verschwinden?


---

# Nachtrag (Folgeauftrag „Integration Validation & Next Gates“)

## A. Verifikation der Angaben
Bestätigt: Basis `7c2b4b7`, Doku in `docs/v21/`, `main`/`claude/v2-integration` unverändert. Korrektur: der Kopf war `3337d1b` (Doku-Commit nach dem geprüften Code-Commit `8234308`; Code identisch). Zwei Commits mit gleicher Nachricht (`ba39271`, `4223b73`) sind ein Zwischenstand und seine Korrektur – kein doppelter Inhalt.
Vor dem Push geprüft: keine Änderungen an `.github/`, `.claude/`, `config/`, `permissions/`, `ui_contract/`, `pyproject.toml`, `CLAUDE.md`, X0 oder `emergency.py`; keine Binär-/Schlüssel-/`.env`-Dateien; Funde des Geheimnis-Detektors im Diff sind ausschließlich synthetische Testwerte und Doku-Beispiele. Push ohne Force.

## B. Linux-Testumgebung (Aufgabe 2)
Ursache der 52 „Umgebungsfehler“ (Abschnitt 5): fehlende Pakete (`openpyxl`, `python-docx`, `defusedxml` → 49) und `python -I` ohne installiertes `jarvis` (3). `pyproject.toml` `dev` unter Linux = `pytest`, `openpyxl`, `python-docx`, `defusedxml` (die Windows-Pakete `mss`/`pywinauto` entfallen); die CI installiert zusätzlich `pyyaml`. Isoliertes venv außerhalb des Repos, `pip install -e ".[dev]"` + `pyyaml`. **Ergebnis des sequenziellen Volllaufs auf `3337d1b`: 1 failed, 6126 passed, 99 skipped (138 s).** Der eine Fehlschlag ist der historische UIA-Wächter (K8). Es gibt damit keine Umgebungsfehler mehr.

## C. Neue Arbeitspakete (Branch `claude/v21-gates`, in `claude/v21-integration` eingeführt)
| Paket | Inhalt | Standard | Tests |
|---|---|---|---|
| M7-Qualitätstor | `quality/gate.py`, Hook im Orchestrator (duck-typed), `agents.quality_gate` + `agents.quality_gate_agents` | **aus**; unbekannter Agent = Start der Agentenschicht verweigert | `test_v21_quality_gate.py` (17) |
| M1-Vorabprüfung | `goals/plan_check.py`, Hook in `GoalEngine._plan`, `goals.plan_analysis` | **aus** | `test_v21_plan_analysis.py` (35) |
| M3-Persistenz | nur Testadapter `tests/support/project_memory_file_adapter.py`, Konzept `M3_PERSISTENZ.md` | **nicht verdrahtet** | `test_v21_project_memory_persistence.py` (8) |
| UIA-Wächter | Entscheidungsvorlage + Vorschlagstest (nicht angewendet), Negativtests der bootstrap-Verdrahtung | Wächter **unverändert** | `test_v21_uia_guard_proposal.py`, `test_v21_bootstrap_wiring.py` (32) |
| M4 | `M4_ENTSCHEIDUNGEN_D1_D8.md` | alle offen | – |
Vertragserweiterungen (Prüfung erbeten): Fabrik `agents/factory.py` darf zusätzlich `jarvis.quality` importieren (Pin in `test_agents_security.py`); `plan_graph.NEVER_REPLAN` kennt `quality_*`, `plan_*`.
Nicht geändert: E5-Allowlist, Strategist, `PermissionEngine`, `emergency.py`, X0, Konfigurationsdatei `config/jarvis.toml`.

## D. Sicherheitsbewertung der neuen Teile
- **Qualitätstor:** reine Leseprüfung des Ergebnisses; Agenten-Selbstaussagen (auch `accepted`/`status` im Bericht) werden ignoriert; kein Bericht, unlesbarer Bericht oder fehlerhafte Prüfung = BLOCKED; das eigene Ergebnis des Agenten wird nicht weitergereicht; Budget (`agent_budget_exceeded`) und Not-Aus (`emergency_stop`) wirken **vor** dem Tor. Offen: ohne angebundene Audit-Quelle gelten Aktionen mit Nebenwirkung als nicht freigegeben (fail-closed); Datei-Prüfung nur mit übergebener Funktion.
- **Plan-Vorabprüfung:** führt nichts aus; ein unlösbarer Plan startet keinen Schritt; Fehler der Prüfung = BLOCKED.
- **Persistenz:** nur Test; Geheimnisse werden beim Laden erneut geprüft; Isolation je Projekt belegt.
