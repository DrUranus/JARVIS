# JARVIS V2: Bestandsaufnahme und Zielarchitektur (Entwurf)

**Status: Entwurf. Nichts davon ist freigegeben, verdrahtet oder aktiviert.** Der Release-Freeze für Windows V1 bleibt bestehen (Ziel 21.11.2026; V1-Abnahme #186 offen). Stand der Analyse: `main` = `7cc65b0`.
Dieses Dokument ändert keine Berechtigung, keinen Standardwert und keine Backlog-Freigabe. Jeder V2-Schritt braucht eine ausdrückliche Besitzerfreigabe (siehe `CLAUDE.md`, `docs/PHASE14_AUTONOMY.md`). Der Backlog dazu: `docs/V2_BACKLOG.md`.

## 1. Leitprinzipien
1. **Wiederverwenden statt neu bauen.** V2 setzt auf den vorhandenen Schichten auf (ToolRegistry, PermissionEngine, Orchestrator, Goal Engine, Journal, Memory, NEXUS). Keine zweite Agenten-, Planungs- oder Gedächtnisimplementierung.
2. **Eine Kontrollstelle.** Jede Wirkung läuft über `ToolRegistry.execute` → `PermissionEngine`. V2 darf diese Stelle nicht umgehen, schwächen oder duplizieren. Verdrahtung nur in `src/jarvis/bootstrap.py`.
3. **Additiv und standardmäßig aus.** Neue Bausteine sind zuerst reine Daten-/Auswertungsmodule ohne Aufrufer. Anbindung ist ein eigener Schritt, opt-in, mit Tests.
4. **Verträge bleiben stabil.** Der UI-Vertrag X0 (`docs/UI_CONTRACT.md`) wird nicht erweitert; neue NEXUS-Sichten nutzen nur lesende `GET /view/*`-Endpunkte.
5. **CI-fähig vor Hardware-fähig.** Jedes Feature braucht einen Fake/Mock-Pfad, der in der GitHub-CI läuft. Windows-Hardware bleibt für das Nötigste.
6. **Obergrenzen bleiben hart.** `max_steps` ≤ 50, `max_attempts_per_step` ≤ 5, Agent-Recovery ≤ 3, `MAX_REPLANS` = 2, Sitzungsbudget, Notaus. V2 verlängert keine Leine.

7. **Open-Source-First.** Vor jeder Eigenentwicklung wird geprüft, ob ein geprüftes Open-Source-Projekt die Lücke schließt (Option A weiterverwenden, B integrieren, C Konzept/Code gezielt übernehmen, D selbst entwickeln). Ergebnis: `docs/V2_OPEN_SOURCE_BEWERTUNG.md`. Fremde Agenten dürfen nur hinter unserer Kontrollstelle laufen und erhalten keine eigenen Berechtigungen.

## 2. Bestandsaufnahme: V1 gegenüber dem V2-Ziel
Legende: **OK** = vorhanden und getestet · **TEIL** = teilweise · **FEHLT** = nicht vorhanden. Umfang aus dem Code gemessen (Zeilen je Paket in `src/jarvis`), Tests: 155 Testdateien, rund 39 000 Zeilen.

| Bereich | Bestand (Beleg) | Status | Lücke für V2 |
|---|---|---|---|
| **Planung** | `goals/` (2200 Z.): Vorlagen-Planer, optionale LLM-Zerlegung (`llm_planning`), kontrolliertes Neuplanen (`MAX_REPLANS`=2), Plan-Validierung (`validation.py`); `agents/planner.py` und `router.py` (Regeln, optional `LLMAgentPlanner`) | OK / TEIL | Kein Projekt-Ebene über Zielen; kein Planqualitäts-Test gegen echte Modelle (Standard `mock`); keine Kosten-/Risikoschätzung vor dem Lauf |
| **Orchestrierung** | `agents/orchestrator.py`: Abhängigkeiten, Priorität, Nebenläufigkeit, Zeitlimits, Abbruch, Cancel-Grace; Adapter `browser`, `coding`, `computer`, `files`, `research` (`agents/adapters/`) | OK | Kein typisierter Übergabeartefakt-Standard über Agenten hinweg (nur `research/handoff.py`); keine Budgets je Agent |
| **Fehlerbehandlung** | `agents/recovery.py`: Klassifikation, ≤ 3 Versuche, nie nach Ablehnung/Notaus/Abbruch; `goals/replanner.py` | OK | Kein Lernen aus Fehlern über Läufe hinweg (nur Journal) |
| **Kontrolle** | `tools/` + `permissions/` (1910 Z.): GREEN/YELLOW/RED, Bestätigung, Audit, Notaus, Sitzungsbudget, >800 Sicherheitstests | OK | unverändert lassen |
| **Journal / Resume** | `journal/` (545 Z.): SQLite, geschwärzt; `/resume` nur auf Befehl; Hard-Kill-Test (#226) | OK | Journal kennt keine Projekte; kein Verlauf je Agent über Sitzungen |
| **Gedächtnis** | `memory/` (991 Z.): SQLite, lokale TF-IDF-Suche, Regel-Extraktion, `SecretGuard`; Typen u. a. `PROJECT`, `DECISION`, `TASK_RESULT` | TEIL | Keine Projekt-Namensräume, keine Verdichtung/Zusammenfassung, keine Aufbewahrungsregeln, kein Kontextaufbau für Agenten (Abruf nur ausdrücklich, nur lesend) |
| **Recherche** | `research/` (1496 Z.): Brave-Suche (opt-in), Quellenwahl, Seiten über das Browser-Tool, Antwort mit Quellen, `handoff` zu Business/Finance; Echt-Browser-Tests (#222) | TEIL | **Keine Quellenbewertung** (Relevanz ja, Verlässlichkeit nein); kein Zitatabgleich; Suchtext regelbasiert; kein Cache |
| **Dateien / Office** | `files/` (1021 Z.), `office/` (776 Z.), `FilesAgent` (#216): lesen, anlegen, kopieren, verschieben, ersetzen; xlsx/docx **nur neu anlegen** | TEIL | Bestehende Office-Dateien ändern, PDF, Vorlagen, Versionierung; Mail ist nur Entwurf (`docs/MAIL_DESIGN.md`) |
| **Business / Finance** | `business/` (556 Z.), `finance/` (655 Z.): Analysen und Entwürfe, Paper-Trading, kein Senden/Order | TEIL | Prozess-Vorlagen, Berichte aus Recherche-Artefakten; Live-Daten bewusst nicht |
| **Coding** | `coding/` (2407 Z.): Anbieter hinter Schnittstelle, Windows-Prozessbaum (`winjob`); `self_repair/` (1515 Z.): Test → Diagnose → begrenzte Reparatur → Regressionstest | TEIL | Kein Schleife „Issue → Branch → PR → CI-Fix“ in der Laufzeit; Sandbox nur Entwurf (`docs/SANDBOX_DESIGN.md`); echte LLM-Vorschläge ungetestet |
| **Selbstverbesserung** | `self_improvement/` (3165 Z.): isolierter Branch, Pipeline, Freigabe durch den Menschen, Rücknahme; Sicherheitsgrenzen blockiert | TEIL | Bleibt in V2 unverändert; kein neuer Autonomiegrad |
| **Computersteuerung** | `computer/` (4201 Z., 475 Tests): Screenshots, Maus, Tastatur, Fenster, Programme, lesende UI-Automation (`ui`), UIA-Aktionen (`uia_actions.py`), Vision | OK / TEIL | Keine wiederverwendbaren, verifizierten GUI-Abläufe (Skills); keine App-Profile; echte Eingabe nur am PC prüfbar |
| **NEXUS** | `control_center/` (760 Z.) + `web/`: Orb, Dashboard, Aufgaben-/Ergebnisansicht (#221), Setup-Panel (#217), `/view/history`, `/view/audit`, `/view/doctor`; X0-Ereignisse `activity`, `routing`, `task_update`, `result`, … | OK / TEIL | Keine Agenten-Zeitleiste, keine Werkzeugaufruf-Spur je Aufgabe, keine Budgetanzeige |
| **CI / GitHub** | Workflows `tests`, `pr-tests`, `fresh-install`, `browser-research`, `control-center-gui-e2e`, `uia-compat`; Controller und Merge-Gate in `.github/automation/` (nicht Teil der Laufzeit) | OK | Controller-Backlog ist von V2-Plänen getrennt (Besitzer pflegt `backlog.json`); keine nächtliche Voll-CI |

**Schlussfolgerung:** V1 enthält fast alle V2-Bausteine in einfacher Form. V2 ist deshalb überwiegend **Verdichtung und Verbindung** (Projektkontext, typisierte Übergaben, Bewertung, Sichten), nicht Neubau. Ein hochautonomer Betrieb bleibt an die bestehenden Freigabe- und Obergrenzen gebunden.

## 3. Zielarchitektur
```
                         NEXUS (X0 unverändert) + lesende Sichten  /view/agents, /view/trace   [V2-12]
                                      │ Ereignisse / GET
  Nutzer ──► Assistent ──► Ziel/Projekt ──► GoalEngine ──► AgentRouter ──► AgentOrchestrator ──► Agent-Adapter
                              │  ▲              │ validate_plan                    │                    │
                       Projektkontext   Plan-Evaluation                    typisierte Artefakte        ToolGateway
                         [V2-03]          [V2-02]                             [V2-06]                    │
                              │                                                                    ToolRegistry
                  MemoryStore (Projekt-Namensräume,                                                      │
                  Verdichtung) [V2-07]  ◄── Journal ──►  Resume                                   PermissionEngine ► Not-Aus ► Audit
```
Unverändert: alles rechts von „Agent-Adapter“. V2-Bausteine liegen **links** (Planung, Kontext, Bewertung, Sichten) oder sind reine Daten.

### 3.1 Säulen und Komponenten
| Säule | Wiederverwendet | Neu oder erweitert (Schritt-ID) |
|---|---|---|
| 1 Autonome Planung, kontrollierte Ausführung | `goals/*`, `agents/router.py`, Journal | Projektkontext als Eingabe (V2-03), Plan-Evaluationsharness (V2-02), Kosten-/Risikovorschau je Plan (V2-05) |
| 2 Multi-Agenten | `AgentOrchestrator`, `handoff.py`, `recovery.py` | typisierte Artefakte und Übergabestandard (V2-06), Budgets je Agent (V2-08) |
| 3 Coding, Test-/Reparaturzyklen | `coding/`, `self_repair/`, `self_improvement/` (Isolierung, Freigabe) | lokale Schleife Test → Reparatur → PR-Entwurf mit menschlicher Freigabe (V2-09), Sandbox zuerst (`docs/SANDBOX_DESIGN.md`) |
| 4 Recherche, Quellenbewertung | `research/*`, Browser-Regeln | **Quellenbewertung (V2-01)**, Zitatabgleich und Mehrfachanfragen (V2-10) |
| 5 Dateien, Office, Business | `files/`, `office/`, `FilesAgent`, `business/` | Office-Bearbeitung auf Kopien mit Versionierung, PDF lesen (V2-11) |
| 6 Windows-Computersteuerung | `computer/*`, `ui`-Tool, UIA-Aktionen | Skill-Bibliothek verifizierter GUI-Abläufe als Daten, App-Profile (V2-13) |
| 7 Langzeitgedächtnis, Projektkontext | `memory/*` (Typ `PROJECT`), `SecretGuard` | Projekt-Namensräume, Verdichtung, Aufbewahrung (V2-07), Kontextaufbau (V2-03) |
| 8 NEXUS-Agentenüberwachung | `control_center/*`, `ReadViews`, Audit, Verlauf | lesende Sichten `GET /view/agents`, `GET /view/trace` (V2-12), kein neues Ereignis |

### 3.2 Entwurfsregeln für neue Bausteine
- **Reine Module zuerst:** stdlib, keine I/O, deterministisch, JSON-tauglich, kein globaler Zustand (so sind sie unter die vorhandenen Layering-Tests gestellt, z. B. `tests/test_analysis_security.py`).
- **Verdrahtung später:** Anbindung nur in `bootstrap.py`, opt-in, Standard aus, mit Test „kein Aufrufer ohne Freigabe“.
- **Daten sind keine Anweisungen:** Seitentext, Dateiinhalt, Modellantworten werden nie als Befehl gelesen; Wirkung entsteht nur über Werkzeugaufrufe mit Freigabe.
- **Erklärbarkeit:** Bewertungen nennen ihre Gründe (Signale), damit NEXUS sie anzeigen kann.

## 4. Sicherheitsmodell (unverändert)
V2 ändert **nicht**: `PermissionEngine`, Notaus, X0-Vertrag, `config/jarvis.toml`-Defaults (`enabled = false`, `security.*`, `paper_trading_only`, `audit_strict`), `.github/`, Backlog-Freigaben. Neue Autonomie (Selbststart, Hintergrundziele, Selbständerung ohne Freigabe) ist **nicht Teil dieses Plans**. Jeder Schritt, der einen höheren Autonomiegrad bräuchte, steht im Backlog als „Besitzerentscheidung“.

## 5. Besitzerentscheidungen (offen)
1. Reihenfolge und Freigabe der V2-Phasen (`docs/V2_BACKLOG.md`).
2. Soll die Quellenbewertung (V2-01) später in Antworten sichtbar werden (Anbindung V2-10)?
3. Sandbox-Entwurf (`SANDBOX_DESIGN.md`) und Mail-Entwurf (`MAIL_DESIGN.md`) bleiben offen und blockieren V2-09 beziehungsweise Mail.
4. Echtes LLM: welcher Anbieter für die Plan-Evaluation (V2-02) mit manuellen Läufen?
5. Ob und wann der Controller-Backlog (`backlog.json`) V2-Schritte aufnimmt (nur der Besitzer ändert ihn).
