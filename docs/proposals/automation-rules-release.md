# Vorschlag: Freigabe `.github/workflows/**` und `.github/automation/**` (zur Übernahme durch den Besitzer)

Patch: `docs/proposals/automation-rules-release.patch` (4 Dateien, +83/−5). Die drei geschützten Regeldateien sind im Repository **unverändert**;
der Patch liegt nur hier. Er wirkt erst, wenn der Besitzer ihn anwendet.

## 1. Änderungen
| Datei | Änderung | Grund |
|---|---|---|
| `CLAUDE.md` | Zeile „Nichts ändern unter `.github/`…“ ersetzt durch drei Zeilen: (a) Workflows/Automatisierung nur bei ausdrücklichem Auftrag, nur `claude/*`, PR gegen `main` nur auf Anweisung, nie mergen; (b) immer tabu: `CODEOWNERS`, `backlog.json`, `.claude/**`, `CLAUDE.md`, Secrets, Token-Rechte, Berechtigungen, Repo-/Branch-Einstellungen; (c) Freigabe = Entwicklung/Tests, keine produktive Aktivierung von Merges/Folgeaufträgen/Limit-Änderungen | neue Berechtigungsregel, alle Verbote erhalten |
| `ROUTINE_PROMPT.md` | „Immer:“-Absatz an dieselbe Regel angepasst | Routine-Prompt muss inhaltlich gleich sein |
| `build_routine_text()` | Protokollregel 2 neu gefasst, Regel 1 „Pull Requests **gegen main** nur…“. Berichtsformat, Auftragsvalidierung, Stopplogik, Statusautomat unverändert | Freigabe kommt im Routine-Protokoll an |
| `tests/test_rule_consistency.py` (neu) | 6 Tests: Freigabe in allen drei Stellen, „ausdrücklich“-Bedingung, alte Verbote erhalten, Aktivierungsverbot, Berichtsformat/Stopp unverändert, keine Tokens | Widerspruchsfreiheit dauerhaft prüfbar |

Bewusste Entscheidung: `backlog.json` bleibt tabu (liegt unter `.github/automation/**`, enthält aber die `approved`-Freigaben; sonst könnte sich die Routine selbst Folgeaufträge freigeben). `.claude/settings.json` und `CODEOWNERS` brauchen keine Änderung (Deny-Regeln für `.claude/**`, `main`-Push, Force-Push, `gh pr merge` bleiben).

## 2. Validierung (Linux, in dieser Sitzung ausgeführt)
- Vorher: `python -m pytest -q .github/automation/tests` → 84 passed (ohne Patch).
- Neue Tests zuerst rot (5 von 6 fehlgeschlagen), dann nach Patch und einer Test-Korrektur (Schleife 1 von 3; Fehler lagen im Test: Groß-/Kleinschreibung, Formulierung) → 90 passed.
- Frischer Klon: `git apply --check` + `git apply` fehlerfrei, 90 passed.
- Gegenprobe: Verbotstext aus dem Protokoll entfernt → `test_previous_prohibitions_are_kept_everywhere` schlägt an.
- **Nicht ausgeführt:** Haupt-Testsuite und Sicherheitsregression von JARVIS (kein JARVIS-Code geändert, Abhängigkeiten nicht installiert); Windows-Nachweis ausstehend; kein Ende-zu-Ende-Lauf mit echter Routine.

## 3. Offene Sicherheitsrisiken
- Das Protokoll ist eine Textvorgabe: Es erzwingt nichts. Durchgesetzt wird nur durch Branch-Schutz/Ruleset auf `main` mit Code-Owner-Review (`/.github/` → `@DrUranus`). Ohne diese Einstellung kann die Routine-Änderung an Workflows nicht abgefangen werden.
- Ein bösartig geänderter Workflow auf einem `claude/*`-Branch läuft erst nach Merge auf `main`; der Review durch den Besitzer ist die einzige Sperre. Workflow-Änderungen sorgfältig prüfen (Secrets-Zugriff, Trigger, Rechte).
- „Ausdrücklich verlangt“ wird von der Routine selbst beurteilt; der Auftragstext kommt aus Backlog/Besitzer. Backlog-Einträge mit `approved: true` daher nur nach Prüfung.
- `.claude/settings.json` verbietet nur einzelne Befehlsmuster (z. B. nicht `git push origin refs/heads/main`); die Remote-Seite (Branch-Schutz) bleibt maßgeblich.
- Der Test prüft Textfragmente, keine Bedeutung.

## 4. Manuelle Übernahme (Besitzer)
1. Branch aus `main` anlegen (z. B. `owner/automation-rules`), diesen Patch holen.
2. `git apply --check docs/proposals/automation-rules-release.patch && git apply docs/proposals/automation-rules-release.patch`
3. `python -m pytest -q .github/automation/tests` (erwartet: 90 passed), Diff prüfen.
4. Commit, PR gegen `main`, selbst reviewen und mergen (Code-Owner-Review).
5. Inhalt des ```-Blocks aus `ROUTINE_PROMPT.md` in der Routine-Konfiguration (claude.ai) ersetzen.
6. Prüfen, dass Branch-Schutz für `main` aktiv ist und `JARVIS_AUTO_CONTINUE_ENABLED` nicht `true` ist.
7. Dieses Verzeichnis `docs/proposals/` danach löschen.

## 5. Reihenfolge für den anschließenden großen Entwicklungsauftrag
1. Patch übernehmen (oben), Routine-Prompt aktualisieren.
2. Kleiner Testauftrag: `chain_budget=1`, `auto_continue=false`, nur lesen und berichten; Bericht und Issue-Zustand prüfen.
3. Großer Auftrag mit ausdrücklichem Text „darf `.github/workflows/**` und `.github/automation/**` ändern“ (Merge-Gate und Controller: nur Entwicklung und Tests), PR gegen `main`, **ohne** Aktivierung.
4. Owner-Review der PR, Windows-CI-Lauf abwarten, manuell mergen.
5. Erst danach und einzeln entscheiden: produktive Aktivierung von Auto-Merge/Folgeaufträgen (derzeit nicht freigegeben), danach `backlog.json` mit `approved: true` für Phase-14-Teilziele 3 und 4 (jeweils eigene Freigabe).
