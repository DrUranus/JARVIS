# V1-Integration: Review der geschützten Dateien (Stand 2026-11-20, Vorlage für den Owner)

Integration: `origin/main` (`d0c1dc4`) in `claude/v2-186-finalisierung` (`4d33fc9`). Konflikte: zwei, beide rein additiv aufgelöst (Import `time` und `uuid` in `ui_events.py`; beide Testblöcke in `tests/test_control_center_e2e_browser.py`). Keine Lockerung von X0, PermissionEngine, Not-Aus, `deny_pending` oder Reset.

## `src/jarvis/ui_contract/fake.py` (im Schutzmanifest)
- Das Merge-Ergebnis entspricht `origin/main` plus einem Block: `_do_stop_speech` (reiner Antwort-Befehl ohne Rechte, bereits am 20.11. im Manifest-Review freigegeben, Commit `664cc0a`).
- Neu gegenüber `4d33fc9` kommen aus `main`, und zwar strenger: Anfrage-IDs sind an die Sitzung gebunden (`session_id`), Ablauf wird vor jedem Befehl geprüft (`_expire`), und der Reset wird nur bei `allow_once` aufgehoben (vorher auch `allow_session`). Außerdem darf nur die Reset-Rückfrage während des Not-Aus bestätigt werden.
- **Hash:** alt `bbf6c3fc…ec017`, neu `93ae46e7…4885`. `test_protected_files` ist bis zur Erneuerung rot (nur `fake.py`).
- **Owner-Schritt (nicht von mir ausgeführt):** nach Prüfung `python -m tests.support.protected_manifest --write --confirm-owner-review --base-commit <SHA>`. Erwartet: genau eine Hash-Änderung (`fake.py`).

## `src/jarvis/bootstrap.py` (CODEOWNERS)
- Die Datei wurde durch den Merge **nicht** geändert; `main` hat sie nicht angefasst. Der Unterschied zu `main` (+65/−5) stammt aus dem V2-Stapel (PR #258) und war schon vor dem Merge so.
- Inhalt: `budgeted_provider` (nur mit `llm_budget.enabled`, sonst identisches Objekt), `agent_budget_audit`, `speech_guard` (liest nur Not-Aus), `voice_stopper` (Not-Aus beendet laufende Sprachausgabe, additiv), `build_voice_session(handler=…)`.
- Die AST-Invarianten und Sicherheitstests laufen grün (siehe Testliste im PR). Die Verdrahtung bleibt in `bootstrap.py`, kein Umgehen der Kontrollstelle.

## Weitere von `main` geänderte Dateien der Konfliktzone
`ui_events.py`, `gui_model.py`, `cli.py`, `server.py`, `app.js`, `launcher.py`, neu `_reset_prompt.py`: Auto-Merge ohne Konflikt, bis auf den Import. `deny_pending` schließt die Reset-Rückfrage weiterhin aus (`ui_events.py`: `not rec["reset"]`), der Abbruch (`_do_cancel`) lehnt also offene Freigaben ab, aber nicht die Reset-Rückfrage.
