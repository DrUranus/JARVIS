# V2 – Vorbereitung für die Zeit nach der Abnahme #186

Branch `claude/v2-post186-preparation` (Basis: `claude/v21-integration` @ `3b9b100`, darauf `claude/v2-integration` @ `c1a9715` und `main` @ `81a027e` zusammengeführt). **Alles standardmäßig aus.** PR #261 und die laufende Abnahme #186 sind nicht berührt; an `main`, `claude/v2-integration`, `claude/v21-integration` und `claude/v2-186-finalisierung` wurde nichts geändert.

## 0. Arbeitsumgebung (ehrlich)
Die Arbeit lief in einem **Linux-Container der Cloud**, nicht auf dem Windows-PC (`list_computer_folders`: kein Rechner, kein Ordner). Es gibt **keinen** Windows-, GUI-, Mikrofon- oder GPU-Nachweis aus dieser Arbeit. Alle Tests unten sind Linux-Tests (Python 3.13); Windows läuft nur über die CI der Branches oder auf dem PC des Besitzers.

## 1. Arbeitsmatrix
| Stand | Inhalt |
|---|---|
| Fertig (auf `main`) | NEXUS Ultimate 1.1.0 als optionale **Leseansicht** (`nexus_ultimate/`, `--nexus-preview`), Premium-Texteingabe (#265), Reset-Rückfrage-Vertragsreview (#264) |
| Implementiert, nicht integriert | V2.0 (#258, Draft gegen `main`), V2.1 (#259, Draft gegen `v2-integration`), #261 (Windows #186, Draft) |
| Neu in dieser Vorbereitung | `control_center/nexus_feed.py` (B), `tests/support/agent_conformance.py` (A), Retry-Sicherheit im Zielmotor (C), `scripts/v2/` (D) |
| Technisch offen | Route/JS-Anbindung des NEXUS-Feeds; Dateien des separaten Agentenprojekts; M3-Persistenz; Audit/M7 produktiv |
| Braucht Windows-Abnahme | NEXUS-Fenster, Sprache/Mikrofon, GPU-/WebGL-Verhalten, Not-Aus mit echten Dialogen, `scripts\v2\run-v2-prep-checks.ps1 -Execute` |
| Braucht Owner-Freigabe | siehe Abschnitt 8 |

## 2. Konflikte und Befunde der Integrationsprüfung
1. **`main` ist weiter** (#262–#265, 45 Dateien). Zusammenführung in diesen Branch: zwei Konflikte (`launcher.py` Importzeilen, `test_control_center_e2e_browser.py` angehängte Tests), beide eindeutig durch Beibehalten beider Seiten gelöst. Beide V2-PRs liegen damit 4 Commits hinter `main`.
2. **Hash-Manifest N3-D (geschützt):** #264 hat `src/jarvis/ui_contract/fake.py` geändert (Reset-Rückfrage im Not-Aus). Das Manifest kennt diesen Stand nicht: `test_the_protected_files_on_disk_match_the_manifest_exactly` ist im zusammengeführten Stand **rot**. Nur der Owner darf das Manifest neu bestätigen (`python -m tests.support.protected_manifest --write --confirm-owner-review --base-commit <SHA von main>`); die Änderung betrifft die Not-Aus-/Reset-Semantik des Vertrags und gehört vor der Bestätigung gelesen (Diff: Rückfrage-ID mit Sitzungskennung, `confirm` im Not-Aus nur für die Reset-Rückfrage, nur `allow_once` hebt auf). Ich habe das Manifest **nicht** angefasst.
3. **Historischer UIA-Wächter** (lokal mit `origin/main`): jetzt rot wegen `config/nexus.live.example.toml` (aus #260, schon auf `claude/v2-integration`). `bootstrap.py` ist durch Option B in Ordnung. Das ist kein V2.1-Fehler: auch die V2.0-Basis ist lokal rot. In der CI wird der Test mangels `origin/main` übersprungen. Entscheidung offen: Beispieldateien `config/*.example.toml` in die Wächterregel aufnehmen (Owner).
4. **Probe-Merge mit #261** (Wegwerf-Worktree, PR unverändert): zwei Konflikte – `interface/ui_events.py` (#261 gegen main #264) und `tests/support/protected_manifest.json` (#261 hat das Manifest ebenfalls geändert). Beide betreffen geschützte/vertragsrelevante Stellen und müssen vom Owner entschieden werden; Reihenfolge siehe 6.
5. **Doppelte Arbeit:** Der Prototyp-Branch `claude/v21-nexus` (Mission-View) ist durch `mission.py` ersetzt; der NEXUS-Feed (B) wiederholt keine Ansicht, sondern liest die vorhandenen (`agents`, `mission`, `trace`, `doctor`).

## 3. Bereich A – Agenten
- Alle neun eingebauten Agenten (`browser`, `coding`, `computer`, `files`, `research` echt und Platzhalter, `business`, `finance`, `strategist`) bestehen die neue gemeinsame **Konformitätsprüfung** `check_agent` (gültig, bekannte Fähigkeiten, `describe()` serialisierbar, `cancel` sicher, ohne Berechtigung/mit ungültiger Eingabe/externer Aktion kein Gateway-Aufruf und kein Ausnahmefall). Dieselbe Funktion ist die Eingangsprüfung für die noch fehlenden Agenten.
- Fähigkeiten sind je Agent eindeutig (Test); Standardstart enthält keinen V2-Agenten (Test + `verify_v2_defaults.py`).
- **Fehlt (nicht erfunden):** die Dateien des separaten V2-Agentenprojekts und die A9-Übergabeunterlagen sind aus dieser Umgebung nicht erreichbar. Benötigt werden: Quellcode der Agenten, deren Fähigkeitsnamen, Tool-Listen, A9-Handoff-Dokument, Testliste. Einbindung dann so: (1) jeden Agenten gegen `check_agent` laufen lassen, (2) neue Fähigkeitsnamen als eigene, vom Owner bestätigte Vertragserweiterung in `agents/policy.py` (Pin in `test_agents_security.py`), (3) Registrierung in `agents/factory.py` hinter eigenem Schalter, Standard aus, (4) Agentenbudget und Qualitätstor-Liste ergänzen.

## 4. Bereich B – NEXUS Ultimate
- Der Quellcode liegt im Repo (`nexus_ultimate/`, Premium-Commit `a1b8126…`, **Version 1.1.0**). Ob „V12“ dieser Stand ist oder eine neuere separate Fassung, ist offen: bitte bestätigen; sonst Quelle/ZIP von V12 bereitstellen.
- **Neu:** `nexus_feed.build_feed(events, agents_view=…, mission=…, trace=…, doctor=…)` – rein lesend, keine Simulation: ohne Daten ist jede der **zehn** Seiten `available = False` mit Grund; Kernzustand, Sprache, Not-Aus, Aufgaben (inkl. Routing/Ergebnis), Freigaben (nur Anzeige, ohne Antwortmöglichkeiten, „answer_via: v1_dialog“), Ereignisverlauf nur aus validierten Vertragsereignissen; fehlerhafte Ereignisse werden gezählt, Sequenzlücken gemeldet; Geheimnisse geschwärzt; alles begrenzt. Fünf Seiten (Workspace, Creative, Coding, Trading, Automations) haben im Backend keinen Endpunkt und bleiben ehrlich „nicht verfügbar“.
- **Nicht gebaut (braucht Freigabe):** eine HTTP-Route (`/view/nexus` würde den exakten Pfad-Pin und `app.js`-Fetch-Pin erweitern) und die JS-Anbindung in `nexus_preview/preview.js`. Ein Vorschlag: ein GET `/view/nexus` mit `build_feed(backend.snapshot()+events_since, …)`, nur lesend, dieselben Prüfungen wie die übrigen Ansichten.
- **Performance/GPU (aus dem Quelltext, nicht gemessen):** Reihenfolge der Darstellung WebGPU → WebGL2 → Canvas 2D; `powerPreference: low-power`; Qualitätsstufen `auto|high|performance`; `requestAnimationFrame`-Schleife. Eine dedizierte GPU ist nicht vorausgesetzt, eine Messung auf dem Windows-PC (Integriert/dediziert, Treiber, Akkubetrieb, Hintergrundtab) steht aus.

## 5. Bereich C – Autonomie
- **Doppelte Ausführung verhindert:** Der Zielmotor wiederholte jeden Schritt nach `timeout`, `agent_crashed`, `executor_failed`, `queue_full`, `step_failed` – auch Schritte mit schreibenden oder eingebenden Fähigkeiten (`files.write`, `office.create`, `computer.input`, `browser.interact`, `coding.write/test`). Der Agent kann seine Aktion vor dem Fehler ausgeführt haben; die Wiederholung wäre eine doppelte externe Aktion. Jetzt: nur lesende/rechnende Fähigkeiten (`.read .screen .plan .web .analyze .strategy`) werden wiederholt; unbekannte oder gemischte Mengen gelten als „kann verändern“; die Warnung steht im Zielergebnis (`warnings`). Keine neue Berechtigung, die Codeliste `RETRYABLE_CODES` ist unverändert (Test).
- Bestehend und weiter getestet: Orchestrator-Not-Aus-Guard, Qualitätstor mit Audit, Plan-Vorabprüfung, Wiederaufnahme mit neuer Bestätigung für Schritte mit Wirkung.
- **Noch nicht produktiv aktivieren:** `agents.quality_gate`, `goals.plan_analysis`, `business.strategist`, `agents.artifacts`, M3-Persistenz, M4 (Ausführung), jede Schreibfunktion von NEXUS.

## 6. Integrations- und Abnahmereihenfolge nach #186
Automatisierbar (ohne Freigabe, nur vorbereiten): A1 `scripts\v2\run-v2-prep-checks.ps1` (Trockenlauf prüfen) – A2 Branches aktualisieren und Konflikte prüfen.
Owner nötig, in dieser Reihenfolge:
1. #186 abschließen; **#261** gegen `claude/v2-integration` entscheiden (Konflikt `ui_events.py` und Manifest klären, 2 Punkte oben).
2. `main` (#262–#265) in `claude/v2-integration` bzw. #258 bringen; **N3-D-Manifest neu bestätigen** (Punkt 2) und UIA-Wächterfrage (Punkt 3) entscheiden.
3. #258 (V2.0) prüfen und mergen.
4. #259 (V2.1) neu auf die dann aktuelle Basis, mergen.
5. Dieser Branch (Vorbereitung A–D) als Draft darauf.
6. Danach, jeweils einzeln und mit Windows-Abnahme: Agenten des separaten Projekts → NEXUS-Route/JS → Qualitätstor mit Audit → Plan-Vorabprüfung.

## 7. Rückbau
- Diese Vorbereitung: Branch nicht mergen oder `git revert` der vier Commits; alle neuen Funktionen sind aus, `nexus_feed` ist nirgends eingebunden, `scripts/v2` und `tests/support/agent_conformance.py` sind reine Hilfen.
- Retry-Sicherheit: `GoalEvaluator.judge` zurücksetzen (eine Bedingung in `goals/evaluator.py`, `may_change_outside` in `goals/policy.py`).
- Windows-Wrapper: Löschen von `scripts\v2` und dem Ordner `abnahme-v2-prep`; es wurde nichts installiert oder konfiguriert.

## 8. Offene Owner-Freigaben
(1) Manifest N3-D neu bestätigen (main #264). (2) UIA-Wächter: `config/*.example.toml`. (3) Konflikte mit #261 (`ui_events.py`, Manifest). (4) Ist „V12“ = Ultimate 1.1.0? Sonst Quelle bereitstellen. (5) Route `/view/nexus` und Pin-Erweiterung. (6) Dateien des separaten Agentenprojekts (A9) bereitstellen. (7) Windows-Lauf von `run-v2-prep-checks.ps1 -Execute` und der NEXUS-/GPU-Sichtprüfung.
