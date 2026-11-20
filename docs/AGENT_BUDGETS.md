# Budgets je Agent (WP02b) – Stand 2026-11-12

**Standard: AUS** (`[agents] agent_budgets_enabled = false`, `agent_budgets = []`). Dann gelten nur die globalen Grenzen, das Verhalten ist unverändert.

## Was es ist
Eine Tabelle `agent_budgets` mit Einträgen `"agent;max_seconds;max_tool_calls;max_calls_session;max_artifact_chars"` (leeres Feld = keine Grenze dieser Art, mindestens eine Grenze). Sie gilt nur mit `agent_budgets_enabled = true`.

| Grenze | Wirkung |
|---|---|
| `max_seconds` | verkürzt den Zeitgeber der Aufgabe; Ablauf → `BLOCKED` mit Code `agent_budget_exceeded` (ein kürzeres Aufgabenzeitlimit bleibt ein gewöhnliches `timeout`) |
| `max_tool_calls` | Werkzeugaufrufe je Aufgabe (zusätzlich zum globalen `tool_call_limit`) |
| `max_calls_session` | Werkzeugaufrufe des Agenten über alle Aufgaben der Sitzung; atomar, parallele Aufgaben können die Summe nicht überschreiten |
| `max_artifact_chars` | größte Länge eines Artefakts dieses Agenten (nur mit `agents.artifacts`, E5); größere werden verworfen (`agent_budget_exceeded`), die Aufgabe bleibt erfolgreich |

## Sicherheitseigenschaften
* **Nur senkend:** ein Wert über dem globalen Limit (`task_timeout_seconds`, `tool_call_limit`, Artefakt-Hartgrenze) lässt den Start scheitern; zur Laufzeit gilt immer das strengere. Es gibt kein Anheben, Zurücksetzen oder Setzen zur Laufzeit; eine neue Sitzung ist ein neuer Zähler.
* **Fail-closed:** ungültige Einträge, doppelte Agenten und Budgets für unbekannte Agenten verhindern den Start (`ConfigError` bzw. Agentenschicht „disabled“); ein zur Laufzeit nicht lesbares Budget blockiert die Aufgabe (`agent_budget_unavailable`) statt sie ungebremst laufen zu lassen.
* **Blockiert, nicht wiederholt:** `BLOCKED(agent_budget_exceeded)` wird weder wiederholt noch neu geplant (`recovery`: nie). Das gilt auch, wenn ein Agent die Ablehnung selbst abfängt und als Fehler meldet: der Orchestrator macht daraus `BLOCKED`.
* **Audit ohne Inhalte:** die erste Erschöpfung je Agent erzeugt genau ein `budget_exhausted`-Ereignis (`tool="agent"`) mit Agent, Art, verbraucht, Maximum und Aufgaben-ID – nie Ziel, Eingabe, Ergebnis oder Artefakttext. Ein ausfallender Audit-Sink macht aus einem Block keinen Lauf.
* Werkzeugaufrufe laufen weiter ausschließlich über `ToolRegistry.execute` → PermissionEngine; der Budgetcheck liegt davor und ersetzt keine Berechtigung.

## Geld
Dieses Paket kennt **keine Preise und keine Geldbeträge** und rechnet nichts in Geld um. Das LLM-Kostenbudget ist E6 (`llm_budget`); eine Zuordnung von LLM-Kosten zu einzelnen Agenten gibt es nicht, weil die LLM-Aufrufe nicht über den Agenten laufen. Das ist eine bewusste, hier ausgewiesene Lücke.

## Tests
`tests/test_agent_budgets.py` (Modell, Konfiguration, Zeit, Aufrufe je Aufgabe/Sitzung, Parallellast, Artefaktgröße, Audit, Fail-closed, Struktur).
