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

---

# Nachtrag 2 (Security Gate & Draft PR)

## E. Zahlen je Quelle (nicht vermischen)
| Quelle | Commit | Bestanden | Übersprungen | Fehlgeschlagen |
|---|---|---|---|---|
| CI Linux, V2.0-Basis | `7c2b4b7` | 5820 | 120 | 0 |
| CI Windows, V2.0-Basis | `7c2b4b7` | 5900 | 46 | 0 |
| CI Linux, V2.1 (vor M7-Audit) | `570348c` | 6223 | 120 | 0 |
| CI Windows, V2.1 (vor M7-Audit) | `570348c` | 6303 | 46 | 0 |
| lokaler Volllauf (venv, mit `origin/main`), nach M7-Audit | `68ff2c1` | 6241 | 99 | 1 (UIA-Wächter) |
Unterschied zur Baseline (CI, `570348c` gegenüber `7c2b4b7`): **+403 bestanden, Skips unverändert** (120 / 46). Die Skip-Obergrenzen der Baseline (`tests/support/skip_baseline.json`) sind nicht erhöht.
**UIA-Wächter:** In der CI wird `test_the_ui_tool_only_touches_computer_and_documentation_files` **übersprungen** („kein origin/main in diesem Checkout“, Linux und Windows) – die CI-Grünheit sagt über diesen Wächter nichts aus. Lokal mit `origin/main` ist er rot, **auch auf der V2.0-Basis** (V2.0 ändert `bootstrap.py` um 63 Zeilen gegenüber `main`). Option B liegt als eigener Branch `claude/v21-uia-guard-b` (nicht im Integrationsbranch) und ist noch nicht freigegeben.
„CI grün“ ≠ „lokaler Volllauf“ ≠ „gezielte Tests“ ≠ interaktive Windows-Abnahme (#186, weiterhin offen und vorrangig); keine der genannten Zahlen ersetzt #186.

## F. M7 – unabhängige Evidenz und Audit-Anbindung
- `quality/reports.py`: typisierte Berichte nur für `business` und `strategist`, **auf der Seite des Tors aus dem Ergebnis abgeleitet**; ein vom Agenten mitgebrachter `quality_report` zählt für diese Agenten nicht.
- Unabhängige Evidenz: (1) zitierte Quellen müssen von einer erfolgreichen Elternaufgabe tatsächlich gelesen sein (Orchestrator-Aufzeichnung), (2) `break_even` wird neu berechnet, (3) Behauptete Aktionen und Blueprint-Schritte, die keine reinen Vorschläge sind, brauchen eine akzeptierte Bestätigung im Audit, (4) eine im Audit protokollierte Budgetausschöpfung **dieser** Aufgabe sperrt das Ergebnis. `market_analysis`/`competitor_analysis` brauchen mindestens eine gelesene Quelle.
- Audit fail-closed: ohne Audit-Quelle (`quality_audit_unavailable`), nicht lesbar (`quality_audit_unavailable`), fehlerhaft oder widersprüchlich (`quality_audit_inconsistent`: Bestätigung ohne Anfrage-Id, mehrfach angenommen, angenommen und abgelehnt) → BLOCKED.
- Wiederverwendet: `permissions.audit` (`AuditSink.tail`, Ereignistypen `confirmation_*`, `budget_exhausted`); nichts Neues im Audit, kein neuer Schreibweg. Die Fabrik nimmt `audit_tail` entgegen; **`bootstrap.py` übergibt ihn bewusst noch nicht** (jede Änderung dort setzt den gepinnten Stand zurück; Owner-Entscheidung). Folge: bei eingeschaltetem Tor bleiben `business`/`strategist` blockiert, bis das entschieden ist – sicher, aber nicht nutzbar.
- Grenzen: Szenarien/Payback werden nicht neu berechnet (die Engine kennt `break_even`, `sum`, `margin`); eine Ergebnisform, die das Modul nicht kennt, führt zu einem leeren Bericht und damit zur Ablehnung; das Tor bleibt standardmäßig **aus**.
- Fabrik-Pin: `agents/factory.py` importiert zusätzlich genau `jarvis.quality.gate` (statisch, in einer Bedingung; Test: keine `importlib`/`__import__`/`eval`/`exec`).


---

# Nachtrag 3 (Final Security Hardening)

## G. UIA-Wächter Option B – übernommen
- Diff am historischen Test: genau die vier Zeilen aus `UIA_WAECHTER_ENTSCHEIDUNG.md` §7 (Verbotsliste und `assert forbidden == []` unverändert, kein Skip hinzugefügt; vorhandene Skips unverändert).
- `bootstrap.py` ist nur erlaubt, wenn `wiring_problems(bootstrap.py) == []`: vollständiger kanonischer AST (jede Bedingung, jeder Operator, jedes Argument, jede Reihenfolge, Konstante, Docstring, Import) ist gleich dem V2.0-Stand `7c2b4b7`, ausgenommen drei einzeln exakt gepinnte Teile: `emergency_guard`, `speech_guard` und die beiden Schlüsselwörter `stop_guard`, `audit_tail` an `build_agents`. Keine pauschale Ausnahme.
- Gegenbeweis am echten Test mit `origin/main` (Wegwerf-Worktree, jede Mutation einzeln committet): bootstrap-Bedingung gedreht, Argument erweitert, `speech_guard` ohne Delegation, `emergency.py`, `engine.py`, `config/jarvis.toml`, `.github/`, `test_emergency_stop.py`, `pyproject.toml` → jeweils rot; unverändert → grün.

## H. Audit-Quelle in `bootstrap.py`
- Verdrahtung (eine Zeile): `audit_tail=permissions.audit.tail if settings.security.audit_enabled else None` an `build_agents`. Bestehende Schnittstelle (`AuditLogger.tail`), kein neuer Schreibweg, keine neue Berechtigung, `PermissionEngine`/`emergency.py`/X0 unverändert, Qualitätstor weiter **aus**.
- Fail-closed: Audit ausgeschaltet → kein `audit_tail` → `business`/`strategist` bleiben bei eingeschaltetem Tor BLOCKED (`quality_audit_unavailable`); Audit ohne jedes Ereignis, beschädigte Zeile (`unreadable_line`), Bestätigung ohne Anfrage-Id, mehrfach angenommen oder angenommen+abgelehnt → BLOCKED (`quality_audit_unavailable` bzw. `quality_audit_inconsistent`); Budgetausschöpfung dieser Aufgabe im Audit → `quality_rejected`.
- Der Fingerabdruck wurde **nur** um diese exakte Verdrahtung erweitert (`AUDIT_TAIL_EXPR`, per kanonischem AST gepinnt). 14 Mutations-Negativtests: fehlend, `None`, unbedingt, Bedingung immer wahr/negiert/anderer Schalter/vertauscht, anderes Attribut, falsches Audit (Lambda), anderes Objekt, umhüllt, doppelt gebunden, an anderen Aufruf gebunden, `stop_guard` entfernt.
- Grenzen: Ein leeres Audit lässt sich von „Datei nicht lesbar“ nicht unterscheiden und gilt deshalb als nicht verfügbar. Das Fenster (500 Ereignisse) begrenzt die Rückschau der Budget-Gegenprobe; die Budgetsperre des Orchestrators wirkt unabhängig davon.

## I. N3-D erweitert
Aufgenommen (Pfade vorher geprüft, beide vorhanden): `tests/test_v21_bootstrap_wiring.py`, `tests/test_computer_uia_tools.py`. Verfahren unverändert (`python -m tests.support.protected_manifest --write --confirm-owner-review --base-commit <SHA von main>`, `base_commit` = `7cc65b0e…`); die Ausgabe nannte ausschließlich die zwei neuen Einträge, alle 32 bisherigen Hashes blieben gleich. Tests: Änderung/Fehlen beider Dateien wird gefunden; Werkzeug, das einen Pfad auslässt, wird gefunden; falscher Manifest-Hash wird gefunden; `MUST_BE_PROTECTED` enthält beide Pfade.
**Verbleibende Grenze (ehrlich):** Wer Schreibzugriff auf die Testdateien, das Manifest **und** das Werkzeug/den Prüftest (`tests/support/protected_manifest.py`, `tests/test_protected_files.py`) hat, kann alles gemeinsam ändern; lokal ist das nicht erkennbar. Erkennbar ist es nur durch den Vergleich mit dem Manifest einer Referenz außerhalb des Branches (`--verify-against origin/main`, Gate G1) und den Owner-Review (CODEOWNERS deckt `bootstrap.py`, nicht die beiden neuen Testdateien). Das Werkzeug und `test_protected_files.py` selbst sind nicht im Manifest.
