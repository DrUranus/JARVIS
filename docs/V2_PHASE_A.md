# JARVIS V2 Phase A: Plan-Evaluation, Projektkontext (nur lesend), nächtliche CI (nur Plan)

**Status: Entwurf. Nichts davon ist verdrahtet oder aktiviert.** Der Release-Freeze für Windows V1 bleibt bestehen; V1 ist auf `main` (`7cc65b0`) CI-verifiziert, die interaktive Abnahme #186 steht aus. Gehört zu `docs/V2_ARCHITEKTUR.md`, `docs/V2_BACKLOG.md` und `docs/V2_OPEN_SOURCE_BEWERTUNG.md`. Kein Schritt hier ändert PermissionEngine, Not-Aus, X0 oder Sicherheitsdefaults.

## 1. V2-02 Plan-Evaluationsharness (umgesetzt als Draft-PR #230, nur Tests)
**Zweck:** Jede Änderung am Planungsverhalten wird sichtbar, ohne Netzwerk und ohne Bindung an einen LLM-Anbieter.

| Baustein | Datei | Aufgabe |
|---|---|---|
| Auswertungskern | `tests/plan_eval.py` | `evaluate_case`, `run_suite`, Invarianten für jeden Plan, Fingerabdruck, Golden-Vergleich |
| Feste Fälle | `tests/plan_eval_cases.py` | 16 Fälle: Dateien/Office, Recherche, Ablehnungen, Obergrenze, eingeschleuste Anweisung, dokumentierte Lücke |
| Golden-Datei | `tests/plan_eval_golden.json` | Fingerabdruck je Fall (unabhängig von Zufalls-IDs und Zeit) |
| Tests des Harness | `tests/test_plan_eval.py` | Gegenproben, Reproduzierbarkeit, feindliche Zerleger-Vorschläge |

**Planquellen sind austauschbar:** jede Funktion `plan(goal, ctx, max_steps)`. Der Vorlagen-Planer ist die Referenz. Ein Modell wird als `Decomposer` angeschlossen (eine Funktion, deren Vorschlag der Planer selbst prüft und sonst verwirft). `ReplayDecomposer` spielt aufgezeichnete Antworten **jedes** Anbieters aus einer JSON-Datei `{Auftrag: [Schrittvorschläge]}` ab.

**Bedienung**
```
python tests/plan_eval.py                    # Kurzergebnis, Exit-Code 0 nur wenn alle Fälle bestehen
python tests/plan_eval.py --report           # vollständiger JSON-Bericht
python tests/plan_eval.py --update-golden    # nur nach bewusster Planänderung; Begründung in den PR
```
**Neuen Fall ergänzen:** `Case(id, objective, context, max_steps, expect=Expect(...))` in `tests/plan_eval_cases.py`, danach `--update-golden`. Fälle werden nie stillschweigend geändert. Ein Fall mit `known_gap` hält das aktuelle Verhalten einer bekannten Lücke fest.

**Bekannte Lücke (festgehalten, nicht geändert):** „Lies a.txt und https://example.org“ plant nur die URL und ignoriert den Dateianteil still.

**Spätere Stufe V2-02b (braucht Besitzerentscheidung):** manuelle Aufzeichnung der Zerlegungen eines echten Modells in die JSON-Datei und Bewertung mit demselben Harness. Welcher Anbieter genutzt wird, ist eine Entscheidung des Besitzers; CI bleibt anbieterfrei.

## 2. V2-03 Projektkontext (nur Konzept, lesend)
**Ziel:** Ein Projekt (mehrere Ziele über Zeit) soll dem Planer und den Agenten **begrenzten, geschwärzten Hintergrund** liefern: Entscheidungen, Ressourcen, frühere Ergebnisse. Ausdrücklich **keine Schreibrechte, kein Werkzeug, kein Hintergrundlauf**.

**Nicht-Ziele:** kein neues Speicherformat, keine zweite Datenbank, kein Schreiben ins Gedächtnis oder Journal, keine automatische Verdichtung (das ist V2-07), keine eigenständige Auswahl von Projekten.

**Datenquellen (vorhanden, nur lesend)**
| Quelle | Lesezugriff | Inhalt |
|---|---|---|
| `MemoryStore` (`memory/base.py`) | `search`, `recent`, `get` | Einträge der Typen `PROJECT`, `DECISION`, `RESOURCE`, `TASK_RESULT` mit Tag `project:<name>` (Namenskonvention, keine Schemaänderung) |
| `JournalStore` (`journal/store.py`) | `list`, `get` | abgeschlossene Ziele und Ergebnisse des Projekts |

**Entwurf der Schnittstelle (noch nicht umgesetzt)**
- Schmale Protokolle statt der vollen Klassen: `ProjectMemoryReader` (nur `search`, `recent`) und `ProjectJournalReader` (nur `list`, `get`). Schreibmethoden (`add`, `update`, `delete`, `record`) sind darüber **nicht erreichbar**.
- Datenmodell: unveränderliches `ProjectContext(project, items: tuple[ContextItem, ...], truncated: bool, chars: int)`; `ContextItem(kind, text, source, timestamp)`; Text nur einfach, Länge begrenzt.
- `build_project_context(project, memory, journal, *, char_budget, max_items)` ist eine **reine Funktion** auf den Leseprotokollen: deterministische Reihenfolge (wichtig und neu zuerst), hartes Zeichen- und Elementbudget, Schwärzung mit dem vorhandenen `SecretDetector`/`SecretGuard`, jede Fehlerquelle ergibt „weniger Kontext“, nie eine Ausnahme und nie ein halb geschwärzter Text.
- **Anbindung später, opt-in:** nur wenn der Mensch ein Projekt nennt; Ergebnis geht als `explicit_user_context["project_context"]` in den Planer und über das vorhandene, ausdrückliche `memory_query`-Verfahren (`relevant_memory`) an Agenten. Es gibt keinen neuen Pfad am Orchestrator vorbei.

**Abnahmetests (CI-fähig)**
1. Das Modul referenziert keine Schreibmethoden (AST-Test) und importiert weder Netzwerk, Prozess noch Threads.
2. Leseprotokolle ohne Schreibmethoden: ein Fake mit `add` wird von der Funktion nie aufgerufen (Zählertest).
3. Budget: Ausgabe nie über `char_budget`; Reihenfolge deterministisch; `truncated` korrekt.
4. Schwärzung: ein eingeschleustes Geheimnis erscheint nie im Ergebnis (mehrere Muster).
5. Fehler: Quelle wirft, ist leer oder liefert Fremdformate → leerer oder kleinerer Kontext, kein Absturz.
6. Feindlicher Inhalt („Ignoriere alle Regeln …“) bleibt Text und ändert den Plan nicht (mit Harness aus V2-02: gleicher Fingerabdruck).
7. Layering-Test: kein Produktivmodul importiert es, bis die Anbindung ausdrücklich freigegeben ist.

**Aufwand:** 3 bis 4 AT (Funktion, Tests, Doku). **Risiko:** niedrig (reine Daten). **Offene Fragen an den Besitzer:** Namenskonvention `project:<name>` ausreichend? Sollen Ergebnisse aus dem Journal einbezogen werden oder nur das Gedächtnis?

## 3. V2-04 Nächtliche Voll-CI (nur Plan, nichts aktiviert)
**Ziel:** Tägliche Absicherung des `main`-Stands mit den **bestehenden** Workflows (`tests` mit `scope=full`, `fresh-install`, `browser-research`, `control-center-gui-e2e`). `.github/` darf nur der Besitzer ändern; dieser Abschnitt ist ein Entwurf für einen späteren Besitzer-PR. Es wird **kein** Workflow angelegt oder aktiviert.

| Variante | Änderung | Vor- und Nachteile |
|---|---|---|
| a) `schedule:` in die vier bestehenden Workflows | je ein Cron-Eintrag; bei `tests.yml` zusätzlich die Job-Bedingungen (ein geplanter Lauf hat keine `inputs`) | wenig neuer Code; berührt vier geschützte Dateien |
| b) neuer Dispatch-Workflow | ruft die vier Workflows per API auf | braucht `actions: write` (Berechtigungserweiterung), nicht empfohlen |
| c) wiederverwendbare Workflows (`workflow_call`) | bestehende Workflows erhalten `workflow_call` | sauber, größter Umbau |

**Empfehlung:** Variante a) nur für `main`, einmal nachts, **nur wenn `main` seit dem letzten grünen Lauf geändert wurde**. Berechtigungen bleiben `contents: read`, keine Secrets.

**Risiken und Gegenmaßnahmen:** Laufzeit und Kosten (Windows-Vollsuite rund 22 bis 25 Minuten pro Nacht) · Rauschen durch seltene Fehlschläge (einmalige Wiederholung ist nur nach Begründung erlaubt; keine automatische Wiederholung) · Wechselwirkung mit der Controller-Automatik (der geplante Lauf darf `jarvis-controller.yml` nicht auslösen und keinen Merge-Gate-Zustand verändern) · kein automatisches Beheben und kein automatischer Merge.

**Abnahmekriterien:** Läuft nur auf `main`; erzeugt nie einen Commit, Push oder PR; Ergebnis ist je Lauf sichtbar (Jobs, Test- und Skip-Zahlen); Fehlschlag ist nur eine Meldung; Workflow-Review durch den Besitzer mit Sicherheitsprüfung wie bei #219/#223.

**Aufwand:** 1 bis 2 AT (Besitzer-PR). **Entscheidung nötig:** Variante und Uhrzeit; solange V1 nicht abgenommen ist, bleibt es ungeplant.

## 4. Eigenentwicklung, Open Source oder vorhandene Funktion je V2-Schritt
Optionen: **A** vorhandene JARVIS-Funktion · **B** Open-Source direkt integrieren · **C** Konzepte/Code gezielt übernehmen · **D** selbst entwickeln. Belege und Alternativen: `docs/V2_OPEN_SOURCE_BEWERTUNG.md`.

| Schritt | Entscheidung | Begründung |
|---|---|---|
| V2-01 Quellenbewertung | **D** (klein) | in den geprüften Projekten fand sich keine eigenständige, lizenzkonforme Quellenbewertung; reine Heuristik |
| V2-02 Plan-Harness | **A** + **D** | nutzt den vorhandenen `Decomposer`-Einstieg des Planers; nur Testwerkzeug |
| V2-03 Projektkontext | **A** + **D** (dünn) | `MemoryStore` und `JournalStore` lesend; nur der Zusammenbau ist neu |
| V2-04 Nächtliche CI | **A** | bestehende Workflows; nur Zeitplan (Besitzer-PR) |
| V2-05 Kosten-/Risikovorschau | **A** + **D** | stützt sich auf `validation.py` und die Obergrenzen |
| V2-06 Typisierte Artefakte | **A** + **C** | `research/handoff.py` als Basis; Muster aus OpenAI Agents SDK / PydanticAI nur als Konzept |
| V2-07 Gedächtnis-Ausbau | **A** + **D** | Mem0 u. a. verletzen Telemetrie-/Datenregeln |
| V2-08 Budgets je Agent | **A** + **D** | erweitert Sitzungsbudget und Orchestrator |
| V2-09 Coding-Schleife | **A** + **B** (bedingt) | `coding/`, `self_repair/`, `self_improvement/`; Fremdagent nur über V2-15 |
| V2-10 Recherche-Ausbau | **A** + **D** | V2-01 plus Zitatabgleich; GPT Researcher nur als Konzept (**C**) |
| V2-11 Office-Ausbau | **A** + **B** | **pypdf** für PDF-Lesen (V2-11a); MarkItDown später; Original nie ändern |
| V2-12 NEXUS-Überwachung | **A** + **D** | `ReadViews`, Audit, Verlauf; keine Zusatzdienste |
| V2-13 GUI-Skills | **A** + **C** | `computer/`; UFO²-Konzepte, kein Code |
| V2-14 MCP-Gateway | **B** (oder schlanker **D**-Client) | MCP Python SDK hinter `ToolRegistry`/`PermissionEngine`; Prüfdatei entscheidet |
| V2-15 Coding-Worker | **B** (bedingt) | OpenHands isoliert; Alternative mini-swe-agent; nach Sandbox-Entscheidung |

## 5. Überarbeitete V2-Entwicklungsreihenfolge
Grundregel: V1-Abnahme (#186) zuerst; ohne ausdrückliche Freigabe wird kein Schritt umgesetzt.

| Stufe | Inhalt | Voraussetzung |
|---|---|---|
| **0 (liegt vor, Draft)** | V2-01 (#229), V2-02 (#230), diese Konzeptdoku | Review durch den Besitzer; V2-Dokumente sind reine Entwürfe |
| **1 Freigabetor G1** | Entscheidungen: MCP-Prüfdokumente (V2-14 nur Dokumente), Prüfdatei `docs/integrations/pypdf.md`, Sandbox-Entscheidung, V2-03-Freigabe, V2-04-Variante | Besitzer |
| **2 Schnelle Gewinne** | V2-11a PDF lesen (pypdf, Option B), V2-03 Projektkontext (lesend), V2-06 typisierte Artefakte | G1 |
| **3 Qualität** | V2-10 Recherche-Ausbau (nutzt V2-01), V2-08 Budgets, V2-05 Vorschau, V2-12 NEXUS-Sichten | Stufe 2 |
| **4 Erweiterung** | V2-14 MCP-Gateway (erst Fake-Server-Tests in CI, dann erster Server), V2-07 Gedächtnis-Ausbau | G1, Stufe 2 |
| **5 Hohe Wirkung** | V2-15 Coding-Worker, V2-09 Schleife, V2-13 GUI-Skills | V1-Abnahme, Sandbox-Entscheidung, ausdrückliche Freigabe je Schritt |

**Warum diese Reihenfolge:** Stufe 2 liefert sichtbaren Nutzen mit minimalem Risiko (kleine Bibliothek, reine Daten). Das MCP-Gateway kommt erst nach den Prüfdokumenten und Fake-Server-Tests, weil es die breiteste Angriffsfläche öffnet. Coding-Worker und GUI-Skills kommen zuletzt, weil sie echte Wirkung haben und die Windows-Sandbox ungelöst ist.

**Manuell am Windows-PC bleibt nur:** Hardware-Sprache, Overlay-Fokus/Mehrmonitor, echte Eingaben in Fremdfenstern, Live-Brave, echtes LLM. Alles andere läuft über die GitHub-CI.
