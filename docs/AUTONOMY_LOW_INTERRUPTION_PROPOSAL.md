# Vorschlag: weitgehend unterbrechungsfreie JARVIS-Entwicklung

Status: **Entwurf zur Prüfung, keine Freigabe und keine aktive Policy-Änderung**.

## Ziel
Claude Code soll normale, bereits im Backlog freigegebene Entwicklungsschritte ohne zusätzliche Rückfragen implementieren, gezielt testen, begrenzt reparieren und nach erfolgreichem CI/Merge automatisch fortsetzen. Eine Kette mit Budget 30 ist eine Obergrenze, kein Zwang, alle 30 auszuführen.

## Trennung von Entscheidungen
1. **Selbstständig:** lokale Implementierungsdetails, Testauswahl, dokumentierte Architektur-Defaults, Refactoring innerhalb des genehmigten Scopes, begrenzte Retry-/Fix-Schleifen und technische Dokumentation.
2. **Konservative Defaults statt Rückfrage:** Bei offenen Designfragen vorhandene sichere Empfehlungen übernehmen, soweit dies keine neue Berechtigung, keinen neuen Datenabfluss, keine Kostenfreigabe und keine Erweiterung des genehmigten Scopes bedeutet. Entscheidung mit Begründung dokumentieren.
3. **Weiterhin menschliche Entscheidung:** Änderungen an X0, PermissionEngine, Not-Aus, Credentials/Secrets, Cloud-Übertragung personenbezogener Daten, geschützten Pfaden, neuen kostenpflichtigen Diensten oder Backlog-Freigaben. Nicht genehmigte Schritte nicht stillschweigend als genehmigt markieren.
4. **Bei Blockern:** Wenn möglich unabhängige freigegebene Arbeiten fortsetzen; keinen riskanten Ersatzweg, keine Umgehung der Gates. Bei tatsächlichem Blocker mit konkreter minimaler Entscheidungsfrage anhalten.
5. **Berichtsdisziplin:** 'needs_human' nur für konkrete, nicht delegierbare Entscheidungen; normale erledigte Dokumentations-/Implementierungsschritte als 'continue' oder 'await_ci' melden, sofern Abnahmekriterien erfüllt sind. Nicht nachträglich Berichte umetikettieren, um Gates zu umgehen.

## Konkrete Umsetzung durch einen separaten Code-PR
- Controller- und Report-Verträge analysieren: Warum stoppt `llm-routing-design` nach erfolgreichem Merge?
- Für freigegebene Schritte eine überprüfbare Unterscheidung zwischen `nonblocking_design_choice` und `owner_gate` entwerfen; keine pauschale Umwandlung von `needs_human` in `continue`.
- Backlog-Abhängigkeiten und Scope vor jeder Fortsetzung prüfen; bei Unklarheit fail-closed.
- Regressionstests: sicherer Design-Default läuft weiter; echte Besitzerfreigabe stoppt; CI-Fehler stoppt; keine Doppeljobs; kein Überschreiten des Tages-/Kettenlimits; geschützte Pfade bleiben geschützt.
- Erst nach grünen Windows-/Linux-Checks und gesonderter PR-Prüfung in main übernehmen.

## LLM-Routing E1–E12
Für Implementierungsdetails zunächst die in `docs/LLM_ROUTING.md` dokumentierten restriktiven Empfehlungen verwenden, ohne dadurch eine ausdrückliche Besitzerentscheidung zu fingieren. Cloud-Datenfreigaben, Audioübertragung, Freigabemodelle und Kostengrenzen bleiben bis zu einer tatsächlichen Entscheidung unverändert. Falls ein Schritt ohne diese Entscheidung nicht sicher implementierbar ist, nur diesen Schritt blockieren.

## Nicht Bestandteil dieses PR
Keine Änderungen an `.github/automation`, `src/`, `config/`, `backlog.json` oder bestehenden Berechtigungen; kein Workflow-Dispatch, kein Merge, keine Abschaltung von Sicherheitsprüfungen.
