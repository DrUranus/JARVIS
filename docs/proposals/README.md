# Automatisierung: Patches zur Übernahme durch den Besitzer

Zwei Patches gegen `main` (in dieser Reihenfolge, beide auf frischem `origin/main` geprüft: `git apply` fehlerfrei, `.github/automation/tests` grün).
Geschützte Pfade (`CLAUDE.md`, `.github/**`) sind im Repository **unverändert**; dieser PR enthält nur die Patches.

| Patch | Inhalt |
|---|---|
| `01-regeln.patch` | Vereinfachte Regel in `CLAUDE.md`, `ROUTINE_PROMPT.md`, `build_routine_text()`: Claude darf `.github/workflows/**` und `.github/automation/**` bei ausdrücklichem Auftrag ändern (claude/*-Branch, PR gegen main). Tabu bleiben `CODEOWNERS`, `backlog.json`, `.claude/**`, `CLAUDE.md`, Secrets, Berechtigungen, Einstellungen, Sicherheitslimits, produktive Aktivierung. + 6 Konsistenztests |
| `02-automatisierung.patch` | `pr-tests.yml`, `junit_summary.py`, `merge_gate.py`, `jarvis-merge-gate.yml`, Controller um Korrekturaufträge erweitert, Protokollregel 7, angepasste Policy-Tests, 42 neue Tests |

## Was Patch 2 liefert
- **PR-Tests:** `pr-tests.yml` führt die volle Suite unter Linux (3.13) und Windows (3.13, `dev,voice`) auf genau dem Head-Commit des PR aus. Fehlgeschlagene Tests werden Annotationen; übersprungene zählen nie als bestanden.
- **Nachweis je Commit:** Das Gate liest die Check-Runs `tests-linux`/`tests-windows` der GitHub-Actions-App für den Head-SHA; fremde Apps und Check-Runs anderer Commits zählen nicht. Gemergt wird per API mit `sha` (GitHub lehnt ab, wenn der Branch weiterging).
- **Merge-Gate** (`jarvis-merge-gate.yml`, Code nur vom Standard-Branch, checkt nie PR-Code aus): merged nur, wenn gleichzeitig gilt: Freigabe für genau diesen Commit (Besitzer-Review „Approve“ **oder** Bericht eines Auftrags zu einem `approved: true`-Backlog-Schritt, der den Commit nennt), beide Pflichtprüfungen erfolgreich, keine Änderung an `.github/`, `CLAUDE.md`, `.claude/`, `config/jarvis.toml`, nicht hinter main, mergebar, nicht angehalten. Standard: **nur Statusbericht** (ein Kommentar im PR, wird aktualisiert); Merge nur mit Variable `JARVIS_AUTO_MERGE_ENABLED=true`.
- **Fehleranalyse und Korrektur:** Bei fehlgeschlagener Pflichtprüfung nennt der Bericht die Tests laut CI. Mit `JARVIS_AUTO_CONTINUE_ENABLED=true` stößt das Gate über den Controller einen Korrekturauftrag an (feste Vorlage, nur sanitisierte Test-IDs als Daten; Controller prüft alles neu; höchstens 3 je PR; nie bei geschützten Pfaden oder ohne Freigabe). Danach läuft `pr-tests` erneut auf dem neuen Commit.
- **Fortsetzung:** unverändert der bestehende Controller (nur Backlog, `approved: true`, Limits). Für Backlog-Schritte verlangt das Protokoll jetzt am Ende einen PR gegen main.

## Validierung (Linux, in dieser Sitzung)
- `python -m pytest .github/automation/tests`: 132 passed (vorher 84).
- JARVIS-Volllauf mit beiden Patches: `3529 passed, 76 skipped` (Skips: Windows-only/POSIX).
- Gegenproben: ohne Commit-Prüfung der Check-Runs bzw. ohne Pfadschutz schlagen die Gate-Tests an.
- Beim Testen gefunden und behoben: ein Check mit Ergebnis `skipped` hätte zum Merge geführt.
- **Nicht bewiesen:** kein Lauf der neuen Workflows auf GitHub (Windows-Nachweis ausstehend); `pr-tests` erst nach Merge der Patches wirksam; Merge-API, Check-Runs und Annotationen nur gegen Fakes getestet; kein Ende-zu-Ende-Lauf mit echter Routine.

## Nicht aktiviert / Besitzeraktionen
1. Patches nacheinander anwenden (`git apply docs/proposals/01-regeln.patch`, dann `02-…`), Tests laufen lassen, **diesen Weg als PR selbst mergen** (Code-Owner-Review). Routine-Prompt (Block in `ROUTINE_PROMPT.md`) in claude.ai ersetzen.
2. Branch-Schutz `main`: Required checks `tests-linux`, `tests-windows`; Review nur für Code-Owner-Pfade verlangen (sonst lehnt GitHub den Gate-Merge ab und das Gate meldet „blockiert“). Actions-Einstellung „Allow GitHub Actions to create and approve pull requests“ bleibt aus (nicht nötig).
3. Aktivierung erst nach Probe: zuerst nur Berichte beobachten; dann `JARVIS_AUTO_MERGE_ENABLED=true`, später `JARVIS_AUTO_CONTINUE_ENABLED=true`. Beides ist **nicht** aktiviert.
4. Notaus: `JARVIS_AUTOMATION_HALT=true` stoppt Gate, Reparatur und Folgeaufträge.

## Offene Risiken
- Ein PR kann Tests im selben Commit abschwächen; das Gate erkennt das nicht (nur Review/Regel „Tests nie abschwächen“).
- Backlog-Freigabe ersetzt den Review für Nicht-`.github`-PRs; `approved: true` also nur nach Prüfung setzen.
- Die Backlog-Aufträge (`autonomy-invariants`) laufen als Kette auf `claude/*`-Basisbranches; der Standard-Basisbranch `claude/inspiring-ritchie-8ljinw` ist nicht `main`. Wer PRs gegen `main` automatisch will, setzt `JARVIS_BASE_BRANCH=main` (nicht geändert).
- Der Gate-Workflow hat `contents: write` (nur für den Merge-Aufruf), und das Gate vertraut Check-Runs der Actions-App; ein PR, der `pr-tests.yml` ändert, fällt unter die geschützten Pfade und wird nie automatisch gemergt.
