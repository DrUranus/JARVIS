# Typisierte Agenten-Artefakte (E5) – Stand 2026-11-12

**Standard: AUS** (`[agents] artifacts = false`). Dann sind alle Agentenergebnisse **byte-identisch** zu vorher, auch wenn ein Agent von sich aus einen `artifacts`-Block liefert.

## Was es tut (nur bei `artifacts = true`)
* **Ergänzung, kein Ersatz (D8 = A):** `output` bleibt wie es ist; Artefakte stehen zusätzlich unter `output["artifacts"]`.
* Der Orchestrator prüft bei **erfolgreichen** Aufgaben den Block mit `agents.artifacts.accept`: nur vom Agenten **deklarierte** Arten (`Agent.produces`), Hash/Länge, Größe je Art, höchstens 20, keine reservierten Schlüssel (`approval`, `confirm`, …), `file_ref` nur schlichte relative Pfade, Geheimnisse geschwärzt.
* Ungültige Artefakte werden verworfen und als `output["artifact_rejections"]` gemeldet: **nur Index, Code und Art** (nie Inhalt). Die Aufgabe bleibt `SUCCEEDED`.
* Würde der Block das gespeicherte Ergebnis über `agents.max_output_chars` heben, wird er verworfen (`output_too_large`), damit das bisherige Ergebnis nie seinetwegen gekürzt wird.
* Erzeuger ist nur der Research-Agent (`produces = {"research_data"}`, nur mit Schalter). `research/handoff.collect` bevorzugt ein **verifiziertes** `research_data`-Artefakt; manipuliert oder fehlend → bisheriger Weg, kein Fehlschlag. Business und Finance erhalten damit dieselben Zahlen.
* Ein Artefakt trägt kein Recht und ändert keinen Plan: sein Text ist Daten, nie eine Anweisung. Not-Aus, Abbruch und Recovery sind unverändert.

## Audit (D9 = A)
Es wird das bestehende Audit-System genutzt; E5 fügt kein neues Ereignis und kein neues Format hinzu.

## Nicht getan
Keine Änderung an PermissionEngine, X0, Audit, Sicherheitsstandards, `config/jarvis.toml`, `.github/`. Layering: nur Orchestrator, Research-Agent und Research-Handoff importieren `agents.artifacts` (Test `test_only_the_approved_modules_import_the_artifacts`); `jarvis.agents.artifacts` steht in der Importliste der Analyse-Strukturprüfung, weil es ein reines Datenmodul ist.
