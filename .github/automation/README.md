# JARVIS-Entwicklungsautomatisierung

Steuerung von Claude-Code-Routine-Aufträgen über GitHub. **Kein JARVIS-Anwendungscode** – nur `.github/`.
Es gibt **keinen automatischen Merge**; Ergebnisse landen auf `claude/*`-Branches und werden von dir geprüft und gemergt.

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
- Der `issue_comment`-Workflow checkt nur den Standard-Branch aus, hat keine Secrets und kein `contents: write`. Kein Workflow hat Merge-Funktion.
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
7. **Branch-Schutz für `main`** (Ruleset): PR + Review erforderlich, Code-Owner-Review (`.github/CODEOWNERS` liegt bei), keine Direkt-Pushes, kein Force-Push.
   Das ist die eigentliche Sperre gegen automatische Merges und Workflow-Manipulation.

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
