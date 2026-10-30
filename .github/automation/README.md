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
Zwischenzustand `awaiting_ci` (`running → awaiting_ci → completed | blocked | timeout | stopped`): Ein Bericht vor dem CI-Ergebnis seines PR beendet die Kette nicht mehr.

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

**Sensible Pfade** (`.github/`, `CLAUDE.md`, `.claude/`, `config/jarvis.toml`, `src/jarvis/permissions/`, `src/jarvis/bootstrap.py`, Sicherheits-/Notaus-/Invariantentests) haben **keine pauschale Dateisperre mehr**:
sie werden automatisch gemergt, wenn der genehmigte Auftrag sie konkret freigibt (siehe „Sensible Pfade im genehmigten Auftrag“). `backlog.json`, `.github/CODEOWNERS`, `CLAUDE.md` und `.claude/**` sind nie per Auftrag freigebbar.
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
setzt die Kette fort (das Gate prüft alle 20 min). Sensible Pfade ohne konkrete Freigabe im Auftrag mergt der Besitzer; die Kette wartet dann.

## Bericht vor Abschluss der CI (`awaiting_ci`)

Die Routine berichtet direkt nach dem Öffnen des PR, die CI läuft dann noch. Früher wurde das als `partial / needs_human` gewertet und beendete die Kette endgültig (Issue #33).
Jetzt gilt: Berichtet die Routine `status success`, `next_action.type = await_ci`, PR, Branch, Commits und (bei Schritten mit Abnahmekriterien) jedes Kriterium im Feld `acceptance`
(`met` | `awaiting_ci` | `not_met`), wechselt der Auftrag nach `awaiting_ci`: Er hält den einen Auftrags-Platz, löst keinen Folgeauftrag aus und hat eine Frist (`CI_WAIT_MIN` = 180 min, danach `timeout`).
Ein ungültiger `await_ci`-Bericht (z. B. ein Kriterium `not_met`, Kriterien unvollständig, kein PR) fällt sicher auf `partial / needs_human` zurück.

Das Merge-Gate (alle 20 min und nach jedem `pr-tests`-Lauf) löst `awaiting_ci` selbst auf, ausschließlich anhand der Prüfungen der GitHub-Actions-App für den **gemeldeten Commit**:

| Lage | Folge |
|---|---|
| CI läuft / fehlt noch | weiter warten (bis zur Frist) |
| `tests-linux` und `tests-windows` erfolgreich | Auftrag `completed` (`ci.result = success`); das Gate mergt nur mit `JARVIS_AUTO_MERGE_ENABLED` und ohne geschützte Pfade, mit der geprüften SHA; danach startet der Controller den nächsten Schritt |
| CI fehlgeschlagen | Auftrag `completed` (`ci.result = failed`), kein Merge; die begrenzte Korrekturschleife (höchstens 3) übernimmt; danach hält die Kette sicher an (nie gemergt = nie fortgesetzt) |
| PR vom Besitzer gemergt | Auftrag `completed` (`owner_merged`), die Kette setzt fort |
| PR geschlossen, Branch seit dem Bericht verändert, PR nicht gefunden | Auftrag `blocked`, Kette endet |

Ein Auftrag, der `awaiting_ci` durchlaufen hat, setzt **immer erst nach dem Merge** fort (`ci_gated`), auch ohne `JARVIS_AUTO_MERGE_ENABLED`. Die Fortsetzung verlangt außerdem vollständig belegte
Abnahmekriterien (`awaiting_ci`-Kriterien zählen erst nach dem Merge). Kettenbudget, Tageslimit, ein aktiver Auftrag und höchstens 3 Versuche gelten unverändert. Beachte: Die Kriterien selbst bewertet
die Routine; maschinell geprüft werden Vollständigkeit, `not_met`, CI je Commit, Branch/PR-Zuordnung und geschützte Pfade, nicht der Inhalt eines Kriteriums.

## Sensible Pfade im genehmigten Auftrag (statt pauschaler Dateisperre)

Ein PR darf sensible Dateien nur ändern, wenn der **genehmigte Backlog-Schritt, zu dem er gehört,** das konkret freigibt. Die Freigabe steht im Plan (`backlog.json`) beim Schritt, nicht in einer Pfadliste des Gates:

```json
"sensitive_edits": {
  "src/jarvis/bootstrap.py":            {"mode": "additive", "added": ["<Zeilenmuster>"], "max_added": 6},
  "src/jarvis/permissions/audit.py":    {"mode": "free", "max_changed": 150},
  ".github/workflows/pr-tests.yml":     {"mode": "free"}
},
"scope": ["src/jarvis/history/", "tests/test_history"]      // optional: nur diese Pfade darf der PR ändern (plus die deklarierten sensiblen Dateien)
```

- **`additive`:** nur hinzugefügte Zeilen, höchstens `max_added`; jede Codezeile muss einem deklarierten engen Muster entsprechen und darf kein Sicherheitswort enthalten (Berechtigung, Not-Aus, Budget, Bestätigung, Audit, Geheimnis/Token/Passwort, `environ`, Prozess-/Netz-/Datei-Zugriff, Policy, Lockdown, Halt/Reset).
- **`free`:** beliebige Änderung genau dieser Datei (oder dieses Verzeichnis-Präfixes), aber: kein Löschen/Umbenennen, höchstens `max_changed` Zeilen (Standard 200, hart 1000), **Sicherheitstests nur additiv** (kein Test wird abgeschwächt),
  und Workflows/Automatisierungscode dürfen **keine neuen Secret-Zugriffe, `pull_request_target` oder Schreibrechte** hinzufügen. Das gilt auch für freigegebene Schritte.
- Das Gate prüft den **echten Patch** gegen genau diese Freigabe, bei jedem Kopf neu. Eine sensible Datei, die der Schritt nicht deklariert, macht den ganzen PR zur Besitzer-Sache; ein PR ohne genehmigten Auftrag
  (z. B. eine Änderung an der Automatisierung selbst) ebenso, und ein Besitzer-Review allein ersetzt die Auftragsbindung nicht.
- **Nie per Auftrag freigebbar** (sie legen fest, wer was genehmigen darf bzw. was Claude darf; sonst könnte die Automatik ihre eigenen Genehmigungen erweitern): `.github/automation/backlog.json`, `.github/CODEOWNERS`, `CLAUDE.md`, `.claude/**`.
  Sie sind auch beim Laden des Backlogs nicht deklarierbar, und das Gate lässt einen PR mit diesen Dateien nie automatisch durch.
- Der Backlog lehnt unsichere Deklarationen schon beim Laden ab: Pfade außerhalb der sensiblen Bereiche oder zu breit, unbekannte Felder, zu weite Muster (alles, was `import subprocess`, `core.permissions = x` oder `exec(x)` zuließe), > 5 Muster, > 20 Zeilen, > 10 Einträge.
- **Aktivierung (einmalig, Besitzer):** Die Deklarationen der Plan-Schritte wirken erst, wenn `plan.scopes_approved` auf `true` steht. Die Datei liefert die geprüfte Deklaration für `persistent-results` mit `scopes_approved: false`, es ist nichts aktiv.
- Weiter nötig wie immer: freigegebener Schritt mit Bericht zum Commit, `tests-linux`/`tests-windows` für genau diesen Commit, Branch aktuell, Merge mit geprüfter SHA.

## Veralteter PR-Branch (`behind`)

Das Ruleset „Jarvis main protection“ verlangt **aktuelle Branches** (`strict_required_status_checks_policy`) und die Pflichtprüfungen `tests-linux` und `tests-windows` der GitHub-Actions-App. Ein PR, der nach einem
anderen Merge hinter `main` liegt, ist deshalb nicht mergebar, bis er aktualisiert und neu getestet ist. Das Gate erledigt das für **freigegebene** PRs selbst (auch für geschützte Pfade, die der Besitzer dann ohne
„Branch aktualisieren“ mergen kann):

1. `PUT /pulls/{n}/update-branch` mit dem erwarteten Kopf (`expected_head_sha`); bei Konflikt oder verändertem Kopf Stopp mit GitHubs Meldung im Statuskommentar (kein Raten, keine Schleife).
2. Die Aktualisierung ist asynchron: das Gate wartet bis zu 60 s auf den neuen Kopf.
3. Ein Push mit `GITHUB_TOKEN` löst **kein** `pull_request`-Ereignis aus. Das Gate startet deshalb `pr-tests` für den neuen Kopf selbst (`workflow_dispatch`, nur für `claude/*`-Branches; höchstens einmal je Kopf).
4. Erst wenn beide Pflichtprüfungen für genau diesen neuen Kopf erfolgreich sind, mergt das Gate (mit dieser SHA), sofern der PR keine geschützten Pfade berührt. Danach startet der Controller den nächsten Schritt.

Die Freigabe bleibt an den gemeldeten Stand gebunden: Ein neuer Kopf gilt nur, wenn er höchstens `MAX_BRANCH_UPDATES` (3) reine Merges des Standard-Branches auf den gemeldeten Commit sind (zwei Eltern, das zweite
schon in `main`). Zusätzliche Commits oder fremde Eltern heben die Freigabe auf. Höchstens 3 Aktualisierungen je Auftrag, danach „Besitzer muss eingreifen“. Bei fehlgeschlagener CI hat die Korrekturschleife
(≤ 3) Vorrang vor der Aktualisierung. Fehlermeldungen der GitHub-API (z. B. warum ein Merge abgelehnt wurde) stehen als Daten im Statuskommentar.

## Nach einem Merge (Besitzer oder Gate)

Das Merge-Gate läuft jetzt auch bei **jedem Push auf `main`** (zusätzlich zu `pr-tests`-Ende, Zeitplan und manuellem Start). Grund: Ein Merge erzeugte bisher kein Ereignis für das Gate, und die
Zeitpläne laufen auf GitHub unregelmäßig (beobachtet: Abstände von 3 bis 6 Stunden statt 15/20 Minuten). Ein Merge durch den Besitzer (geschützte Pfade!) setzt die Kette deshalb sofort fort.

Ablauf: PR gemergt → Gate prüft Repository, Basis `main`, Branch und PR-Nummer gegen den Bericht → vermerkt `merged` im Auftrags-Issue → stößt den Controller einmal an → Controller wählt den nächsten
freigegebenen, offenen Schritt. Ein ohne Merge geschlossener PR vermerkt `abandoned` (Kette endet, Schritt **nicht** erledigt, darf bewusst erneut gestartet werden).

**„Erledigt“ ist abgeleitet, nicht in `backlog.json` geschrieben:** Ein Schritt gilt als erledigt, wenn sein Auftrag `completed` ist **und** sein PR als gemergt vermerkt ist (bei Aufträgen, die auf die CI
gewartet haben, immer). `backlog.json` ist CODEOWNERS-geschützt; ein automatisch erzeugter Änderungs-PR bräuchte bei jedem Schritt einen Besitzer-Merge und würde die Pin-Tests brechen. Das Flag `done: true` in der Datei bleibt
ein manueller Override (Besitzer). Ein Schritt, der schon einen laufenden Auftrag hat oder auf den Merge seines PR wartet, wird weder per `backlog_item` noch vom Controller ein zweites Mal gestartet.

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

## Wiederaufnahme des Gates nach der CI

Startet das Gate die CI selbst (nach „Branch aktualisieren“), löst der mit `GITHUB_TOKEN` per `workflow_dispatch` gestartete `pr-tests`-Lauf **kein** `workflow_run`-Ereignis aus
(GitHub: Ereignisse von `GITHUB_TOKEN` starten keine Workflows, außer `workflow_dispatch`/`repository_dispatch`); der 20-Minuten-Zeitplan läuft auf GitHub nur unregelmäßig (Stunden-Abstände beobachtet).
Darum startet das Gate zusammen mit der CI `jarvis-gate-resume.yml` (Code des Standard-Branches, `actions: write` + `checks: read`, keine Secrets, kein PR-Code). Dieser Lauf wartet höchstens 65 Minuten
auf `tests-linux` und `tests-windows` des Commits und stößt das Gate danach **genau einmal** an (auch nach Zeitüberschreitung, dann berichtet es den Stand). Er entscheidet nichts; Freigabe,
exakte Commit-Prüfung, Merge und Not-Aus (`JARVIS_AUTOMATION_HALT`) bleiben im Gate. Keine Rekursion: das Gate startet den Warte-Lauf je Kopf höchstens einmal (`ci_dispatched`, höchstens
`MAX_BRANCH_UPDATES + 1` je Auftrag), der Warte-Lauf startet nur das Gate. Push auf `main` und Zeitplan bleiben das Netz darunter.

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
