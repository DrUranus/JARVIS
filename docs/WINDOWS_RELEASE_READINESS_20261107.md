# Windows-Release 21.11.2026 – Wiederanlauf und Abnahme (Stand 07.11.2026)

## Verifizierter Ausgangspunkt
- PR #212 wurde gemergt; `media-design` (#209) und `office-docs` (#211) sind im Backlog als erledigt markiert.
- Der genehmigte Backlog ist ausgeschöpft. `next` darf **keinen** neuen Claude-Job erzeugen, solange kein weiterer geeigneter Schritt ausdrücklich freigegeben ist.
- `cc-windows-smoke` (B9) ist nicht erledigt; es ist bis 07.12.2026 zurückgestellt. Das ist kein Windows-Desktop-Abnahmenachweis. Issue #186 bleibt für die echte Desktop-Abnahme maßgeblich.
- Offene, nicht genehmigte Schritte: `mcp-security-review`, `mail-provider`, `media-agent`, `audit-hash-chain`, `cli-confirm-timeout`, `smartphone-api-design`. Keine automatische Freigabe durch dieses Dokument.

## Kritischer Pfad vor der Deadline
1. **Windows-Desktop-Abnahme zuerst:** Issue #186 auf einem echten Windows-Desktop bearbeiten; GUI-Start, Sprache, Bestätigungsdialog, Not-Aus, Ereignisstrom und vollständigen Eingabe→Ausführung→Ergebnis-Ablauf einzeln protokollieren. Runner-Smoke ersetzt keine echte GUI-Abnahme. Wenn B9 wieder aufgenommen werden soll, vorher Deferral und Testbedingungen separat und ausdrücklich prüfen.
2. **Release-Gates:** nur echte, zum jeweiligen Commit gehörende Windows-CI-Ergebnisse als Nachweis; kein übersprungener Test als bestanden; bei Fehlschlag Logs auswerten und gezielt reparieren (max. drei Zyklen).
3. **Nutzbarkeit:** Priorität auf Fehlerbehebung der bestehenden Windows-Funktionen und End-to-End-Flows. Neue Mail-/Medien-/MCP-Funktionen erst nach separater Scope- und Besitzerfreigabe; keine Änderungen an PermissionEngine, Not-Aus oder X0 ohne eigenen Review.
4. **Auftragskette:** vor einem `workflow_dispatch` aktiven Ausführungsslot, Tracking-Issues, offene PRs und verfügbare genehmigte Backlog-Einträge prüfen. Keine Doppelstarts. Nur wenn tatsächlich ein freigegebener, noch nicht erledigter Auftrag existiert, die bestehende Kette über ihren dokumentierten Workflow starten.
5. **Merge:** PR nur bei geprüfter Diff, erforderlichen Reviews und grünen relevanten Checks mergen. Bei Blockern Meldung mit konkretem Run/Job und nächstem Reparaturschritt.

## Nächste Entscheidung des Besitzers
- Windows-Abnahme #186 auf echtem Windows-PC durchführen oder eine konkret eingegrenzte, neue Windows-Testaufgabe separat genehmigen.
- Für weitere autonome Entwicklung genau die gewünschten Backlog-Schritte mit Umfang und Abnahmekriterien einzeln genehmigen. Nicht pauschal alle offenen Schritte freischalten; Smartphone bleibt zuletzt.
- Nach Freigabe und erfolgreichem Merge erst prüfen, ob `next` einen Job wählen kann; **danach** den bestehenden Workflow starten.

## Statusregeln
`merged`, `CI grün`, `Windows getestet`, `Kette läuft` und `Release fertig` sind unterschiedliche Zustände. Nur nach Live-Nachweis so bezeichnen. Dieses Dokument startet keinen Workflow und verändert keine Berechtigung.
