# JARVIS-Entwicklungsautomatisierung

Steuerung von Claude-Code-Routine-Aufträgen über GitHub. **Kein JARVIS-Anwendungscode** – nur `.github/`.
Ergebnisse landen auf `claude/*`-Branches und in Pull Requests. Gemergt wird **nur** durch das Merge-Gate (`merge_gate.py`, Variable `JARVIS_AUTO_MERGE_ENABLED=true`)
und nur bei vollständigem Nachweis; ohne die Variable erstellt das Gate nur Statusberichte. Änderungen an geschützten Pfaden mergt immer der Besitzer.

## Ablauf

```
Actions → "Trigger Claude Code Routine" (workflow_dispatch: context, base_branch, auto_continue, chain_budget, timeout_minutes)
  1. Prüfungen: Halt-Variable, Größe, genau ein aktiver Auftrag, Tageslimit, kein Doppelstart desselben Laufs, Basis-Branch existiert
  2. job_id erzeugen, Tracking-Issue anlegen (Label jarvis-job + jarvis:queued, Zustand als Marker im Issue-Text)
  3. Fire-API aufrufen (Fire-Token nur hier; der Routine-Text enthält keine Secrets), Session-ID/-URL und Frist im Issue vermerken (jarvis:running)
Routine arbeitet, führt Tests aus und postet GENAU EINEN Bericht-Kommentar im Tracking-Issue (Marker + JSON, siehe ROUTINE_PROMPT.md)
  4. jarvis-report.yml (issue_comment): Absender, Auftrags-ID, Session-ID, Schema prüfen → Status completed|partial|failed|blocked,
     Issue schließen, Zusammenfassung als gequoteter Text kommentieren. Ungültig → Ablehnung, Auftrag bleibt running.
  5. Nur wenn akzeptiert: jarvis-controller.yml wird angestoßen (workflow_dispatch, nicht der Berichtstext).
  6. Controller entscheidet aus Issue-Zustand + Backlog (siehe unten) und startet höchstens einen Folgeauftrag ODER beendet die Kette mit Begründung.
  7. jarvis-watchdog.yml (alle 15 min): Frist überschritten → timeout; nie gestartet → start_failed; Label jarvis:stop → stopped;
     verpasste Berichte nachholen; verlorenen Controller-Anstoß (≤ 2 h) wiederholen. Der Watchdog startet nie einen Auftrag.
```

Zustände: `queued → running → completed | partial | failed | blocked | timeout | stopped`, `queued → start_failed | stopped`.
Endzustände sind endgültig (Statusautomat in `set_state`, getestet). Jeder Auftrag ist über sein Issue vom Start bis zum Ende nachvollziehbar
(Zustandsblock, Statuskommentare, Session-Link, Berichtskommentar, Eltern-/Kind-Verweise).

## Vollautomatische Kette (Auftrag → CI → Merge → nächster Auftrag)

```
Controller startet Schritt N (Backlog, approved=true, nicht done)  →  Routine implementiert, testet, öffnet PR [JARVIS] <Schritt>, berichtet
  →  pr-tests: tests-linux + tests-windows auf genau dem Head-Commit  →  Merge-Gate (alle 20 min / nach pr-tests):
       grün + freigegeben + nicht hinter main + keine geschützten Pfade  →  Squash-Merge mit geprüfter SHA, Vermerk `merged` im Auftrags-Issue
       rot  →  Korrekturauftrag auf demselben Branch (höchstens 3 je PR), danach „blockiert – Besitzer nötig“
  →  Gate stößt den Controller genau einmal an  →  Controller startet Schritt N+1 **auf main** (nicht auf dem gemergten Branch)
```

Mit `JARVIS_AUTO_MERGE_ENABLED=true` und `auto_continue` startet ein Folgeauftrag **erst nach dem Merge** des PR des Vorgängers (`merge_gated`): Bericht und Watchdog
stoßen den Controller vorher nicht an. Wird der PR nie gemergt (rot, Konflikt, geschützter Pfad, kein Merge-Recht), endet die Kette sichtbar am PR-Statuskommentar und am
Auftrags-Issue; es wird nichts erraten oder umgangen. Erledigte Schritte stehen mit `"done": true` im Backlog und werden nie erneut gestartet.

**Nie automatisch gemergt** (immer Besitzer): `.github/`, `CLAUDE.md`, `.claude/`, `config/jarvis.toml`, `src/jarvis/permissions/`, `src/jarvis/bootstrap.py`,
`tests/test_emergency_stop.py`, `tests/test_security_*`, `tests/test_autonomy_invariants.py` (`PROTECTED_PATHS`).
Grenzen der Kette: `chain_budget` hart ≤ 5 Aufträge je Kette, `JARVIS_MAX_JOBS_PER_DAY` (Standard 10, hart ≤ 50), ein aktiver Auftrag, höchstens 3 Versuche je Schritt,
Stopp per `JARVIS_AUTOMATION_HALT=true` oder Label `jarvis:stop`. Neustart-fest: der Zustand liegt in den Tracking-Issues; der Watchdog (15 min) holt verlorene Berichte,
Timeouts und verlorene Controller-Anstöße (≤ 2 h) nach.

## Einmalig freigegebener Entwicklungsplan

`backlog.json` enthält einen Plan-Block (`plan`: `id`, `approved`, `approved_items`). Die **einzige** Besitzeraktion ist, `plan.approved` auf `true` zu setzen (eine Zeile in
einer CODEOWNERS-geschützten Datei). Danach gelten genau die in `approved_items` gelisteten Schritte als freigegeben; jeder hat Abnahmekriterien (`acceptance`), Abhängigkeiten
(`depends_on`), Zeitlimit und höchstens 3 Versuche. Die Liste ist im Test festgenagelt (`PINNED_PLAN`): ein weiterer Schritt braucht eine bewusste Änderung von Besitzer und Test.
Sicherheitskritische Schritte stehen nicht im Plan und bleiben `approved: false`.

Start: Actions → „Trigger Claude Code Routine“ mit `backlog_item = next` (oder einer Schritt-ID), `auto_continue = true`, `chain_budget = 5`. Der Auftragstext samt Abnahmekriterien kommt aus
dem Backlog (nie aus Berichten). Weitere Schritte folgen automatisch nach Merge (Variablen `JARVIS_AUTO_CONTINUE_ENABLED` und `JARVIS_AUTO_MERGE_ENABLED`); eine Kette hat höchstens 5 Aufträge,
bei 7 Plan-Schritten ist deshalb ein zweiter Start nötig. Ein Schritt gilt mit Auto-Merge erst als erledigt, wenn sein PR gemergt ist (`merged`); auch ein vom Besitzer selbst gemergter PR
setzt die Kette fort (das Gate prüft alle 20 min). Schritte, die geschützte Pfade berühren, mergt weiter nur der Besitzer; die Kette wartet dann.

## Folgeaufträge (nur wenn **alle** Bedingungen gelten – `decide_followup`)

- Start mit `auto_continue=true` **und** Repository-Variable `JARVIS_AUTO_CONTINUE_ENABLED=true`
- nicht angehalten (`JARVIS_AUTOMATION_HALT`), kein Label `jarvis:stop`
- Auftragsstatus `completed`, Bericht `next_action.type = continue`, mindestens ein Test `passed` und keiner `failed`
- Kettenbudget (`chain_budget`, hart ≤ 5, Variable `JARVIS_MAX_CHAIN_JOBS`) und Tageslimit (`JARVIS_MAX_JOBS_PER_DAY`, Standard 10) nicht ausgeschöpft
- gemeldeter Branch existiert und passt auf `claude/…`
- Der nächste Schritt kommt **ausschließlich aus `backlog.json`** (auf dem Standard-Branch): `approved: true`, Abhängigkeiten erledigt.
  Text aus Berichten wird nie als Auftrag verwendet.
- Wiederholung nach `failed` nur für Backlog-Schritte, höchstens `max_attempts` (hart ≤ 3) Versuche je Schritt.
- Idempotenz: Die Entscheidung wird im Eltern-Issue markiert (`followup`); ein zweiter Controller-Lauf ändert nichts. Controller-Läufe sind serialisiert.

## Sicherheitsgrenzen

- Secrets: `ROUTINE_FIRE_URL` / `ROUTINE_FIRE_TOKEN` nur in `claude-routine-fire.yml` und `jarvis-controller.yml`, nur im Lauf auf dem Standard-Branch,
  nie im Routine-Text, nie im Log. **Kein OpenAI-Schlüssel**: Es gibt keine OpenAI-Auswertung, sie ist bewusst nicht gebaut.
- Berichte/Kommentare sind Daten: Absender (Login muss in `JARVIS_TRUSTED_REPORTERS`, Standard: Repository-Besitzer), Issue vom Bot angelegt, Label,
  Auftrags-ID, Session-ID, Schema, Längen, Branch-Regex, PR-URL nur dieses Repos. Ausgabe nur gequotet (Backticks entfernt, `@` entschärft).
- Der `issue_comment`-Workflow checkt nur den Standard-Branch aus, hat keine Secrets und kein `contents: write`. Nur `jarvis-merge-gate.yml` darf mergen (`contents: write`, ohne Fire-Secrets, ohne PR-Code).
- Routine-Protokoll verbietet Änderungen unter `.github/`, Pushes auf `main`, Merges, Folgeaufträge. Durchgesetzt wird das nur durch Branch-Schutz/CODEOWNERS (unten) – nicht durch dieses Repo allein.
- Stopp: Variable `JARVIS_AUTOMATION_HALT=true` (blockiert Start, Berichte, Folgeaufträge) oder Label `jarvis:stop` am Issue (Watchdog beendet den Auftrag, Kette endet).

## Manuelle Einstellungen (einmalig, ich habe nichts davon geändert)

1. **PR mergen** – die Workflows (`workflow_dispatch`, `issue_comment`, `schedule`) wirken erst auf dem Standard-Branch.
2. **Routine-Prompt ersetzen** (claude.ai → Routine bearbeiten): Inhalt von `ROUTINE_PROMPT.md`. Der bisherige Prompt ist eine read-only-Analyse
   und behandelt den Fire-Text als reine Daten – ohne diese Änderung führt die Routine keine Aufträge aus.
3. **Routine-Zugriff prüfen**: Repository `DrUranus/JARVIS` angebunden, GitHub-Zugriff, der **Kommentare in Issues** erlaubt (Claude-GitHub-App: Issues → Read & write).
   Eigene Branches `claude/*` darf die Routine pushen; sie braucht keine Rechte für `main`, Actions, Secrets, Administration.
4. **Actions-Einstellungen**: Settings → Actions → General → Workflow permissions: „Read repository contents“ als Standard, **„Allow GitHub Actions to create and approve pull requests“ aus**;
   Actions erlaubt (das Repo darf Workflows ausführen). Die Workflows setzen ihre Rechte selbst (`issues: write`, `actions: write` nur für den Controller-Anstoß).
5. **Secrets** (existieren laut bestehendem Workflow bereits): `ROUTINE_FIRE_URL`, `ROUTINE_FIRE_TOKEN`. Empfohlen: als Environment-Secrets mit Branch-Beschränkung auf `main`.
6. **Variablen** (Settings → Variables, alle optional):
   `JARVIS_TRUSTED_REPORTERS` (Standard: Repository-Besitzer; **falls die Routine als App-Konto postet, dessen Login eintragen**, z. B. `claude[bot]`),
   `JARVIS_BASE_BRANCH` (Standard `claude/inspiring-ritchie-8ljinw`), `JARVIS_AUTO_CONTINUE_ENABLED` (erst `true`, wenn der erste Einzelauftrag sauber lief),
   `JARVIS_MAX_CHAIN_JOBS`, `JARVIS_MAX_JOBS_PER_DAY`, `JARVIS_AUTOMATION_HALT`.
7. **Branch-Schutz für `main`** (Ruleset): PR erforderlich, **Pflichtprüfungen `tests-linux` und `tests-windows`**, „Require review from Code Owners“ mit **0 erforderlichen Approvals**
   (dann braucht nur ein PR mit Dateien aus `.github/CODEOWNERS` den Besitzer; alle anderen kann das Gate mergen), keine Direkt-Pushes, kein Force-Push.
   Bei „1 Approval für alle PRs“ lehnt GitHub den Gate-Merge ab (HTTP 405, im PR-Statuskommentar sichtbar) – dann läuft nichts automatisch.
8. **Auto-Merge einschalten** erst nach dem ersten grünen Trockenlauf (Statuskommentar „Bereit zum Merge“): Variablen `JARVIS_AUTO_MERGE_ENABLED=true` und `JARVIS_AUTO_CONTINUE_ENABLED=true`.
   Start der Kette: Actions → „Trigger Claude Code Routine“ mit `auto_continue=true`, `chain_budget` (≤ 5). Notbremse: `JARVIS_AUTOMATION_HALT=true`.

## Erster Test (klein, nach dem Merge)

Start mit `chain_budget=1`, `auto_continue=false` und einem harmlosen Auftrag („Lies README.md auf dem Basis-Branch und berichte nur“).
Erwartung: Issue `[JARVIS] job-…` → Session-Link → Berichtskommentar → Status `completed`. Schlägt es fehl, nennt das Issue den Grund
(`start_failed`, abgelehnter Bericht, `timeout`).

## Offene, ungetestete Annahmen

- Unter welchem Konto die Routine kommentiert und ob die Routine-Umgebung Issue-Kommentare schreiben darf (Rechte der GitHub-Anbindung).
- Ob die Routine ihre Session-ID kennt (Format der `claude_code_session_id` aus der Fire-API vs. Session-URL; der Vergleich normalisiert `session_`-Präfix und URL-Form).
- Dass der Fire-`text` als Auftrag ausgeführt wird (hängt vom Routine-Prompt ab) und die Fire-API experimentell bleibt (Beta-Header kann sich ändern).
- Verhalten bei sehr langen Läufen/Plan-Limits der Routine.

## Tests

`pytest .github/automation/tests` (Linux, ohne Netzwerk/Secrets; läuft in `automation-ci.yml`): Fake-GitHub für Start, Berichtsprüfung,
Statusautomat, Watchdog, Controller/Idempotenz/Limits sowie Regeln für die Workflow-Dateien (Rechte, gepinnte Actions, keine Interpolation in `run`, Secrets nur an erlaubten Stellen).
Das ersetzt keinen Ende-zu-Ende-Lauf mit echter Routine.
