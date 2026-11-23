# PR #270 – rote Tests, Manifest-Differenz, UIA-Wächter, Simulation von #261 (Owner-Vorlagen)

Stand: Branch `claude/v2-post186-preparation`. **Nichts davon ist angewendet:** das Manifest ist unverändert, der historische UIA-Test ist unverändert, PR #261/#258/#259 und `main` sind unberührt. Hashes sind SHA-256 über den auf LF/ohne BOM normalisierten Dateiinhalt (Verfahren von `tests/support/protected_manifest.py`).

## 1. Die zwei bekannten roten Tests

| Test | Wo rot | Genaue Ursache | Kleinste sichere Lösung | Wer |
|---|---|---|---|---|
| `test_protected_files::test_the_protected_files_on_disk_match_the_manifest_exactly` | CI Linux **und** Windows, lokal | Genau **ein** Manifesteintrag weicht ab: `src/jarvis/ui_contract/fake.py`. Das Manifest enthält den Stand vor #264; `main` (#264) hat die Datei geändert. Alle anderen 33 Einträge stimmen. | Den einen Eintrag nach Owner-Review neu bestätigen (Abschnitt 2). Sonst nichts ändern. | Owner |
| `test_computer_uia_tools::test_the_ui_tool_only_touches_computer_and_documentation_files` | nur lokal mit `origin/main`; in der CI **übersprungen** („kein origin/main“) | Der Test meldet `config/nexus.live.example.toml` (neu durch #260, schon auf `claude/v2-integration`). Die Regel verbietet pauschal jede Datei unter `config/`. `bootstrap.py` ist durch Option B in Ordnung. Auch die V2.0-Basis ist lokal rot. | Beispielkonfigurationen nach **Inhalt** zulassen (Abschnitt 3), nicht nach Pfad. | Owner (Test ist im Manifest N3-D) |

## 2. Manifest-Differenz und Owner-Freigabevorlage (nur Vorbereitung)

### Exakte Differenz
| Eintrag | Manifest (aktuell) | Tatsächlicher Stand (`main` #264 = dieser Branch) |
|---|---|---|
| `src/jarvis/ui_contract/fake.py` | `939e9978cde0f8f76b419c5320f9db5c9b8ce65217dab2a3799fd7fd6bf41f8c` | `8904b0f694ae321bceee003efe97c2a39ff1fae87c2069462577916d0cf7d68e` |

Belege: Der Manifest-Hash ist **identisch** mit dem Hash der Datei auf `7cc65b0` (vor #264); der neue Hash ist identisch mit der Datei auf `main` `81a027e`. `python -m tests.support.protected_manifest --check` meldet genau „geaendert: src/jarvis/ui_contract/fake.py“ (1 Abweichung). `base_commit` im Manifest ist `7cc65b0…`.

### Was #264 an der Datei ändert (13 Zeilen hinzu, 3 geändert; nur die Test-Attrappe des Vertrags)
1. `FakeUiBackend` bekommt eine Sitzungskennung (`uuid`); Anfrage-IDs werden `"<sitzung>.<zähler>"` (verhindert Verwechslung von Freigaben zwischen Sitzungen).
2. Bei aktivem Not-Aus wird ein `confirm` **nur** angenommen, wenn es die Antwort auf die **Reset-Rückfrage** (`kind == "emergency_reset"`) ist; alles andere bleibt mit `emergency` abgelehnt.
3. Nur `allow_once` hebt den Not-Aus auf (vorher jede „erlaubende“ Antwort, z. B. `allow_session`).
4. Offene Rückfragen laufen vor jedem Befehl ab (`_expire`): unbeantwortet = Zeitüberschreitung (fail closed).
Gegenstück im echten Pfad (nicht geschützt): `interface/ui_events.py` und `interface/_reset_prompt.py`. Vertragsreview: `docs/NEXUS_RESET_VERTRAGSREVIEW.md`; Test: `tests/test_ui_reset_contract.py` (läuft grün).
**Bewertung:** alle vier Punkte **verschärfen oder präzisieren** (nichts wird gelockert); der Not-Aus-Latch selbst (`permissions/emergency.py`) und die `PermissionEngine` sind unverändert. Das ist meine technische Einschätzung, keine Freigabe.

### Vorlage zur Freigabe
> Ich habe `docs/NEXUS_RESET_VERTRAGSREVIEW.md` und den Diff von `src/jarvis/ui_contract/fake.py` (`7cc65b0..81a027e`) gelesen und bestätige den neuen Stand als geschützte Basis.

Ausführung durch den Owner (ein Befehl, im Repository-Stamm, auf dem zusammengeführten Stand):
```
python -m tests.support.protected_manifest --write --confirm-owner-review --base-commit 81a027e<…vollständiger SHA von main…>
```
Erwartete Ausgabe: genau eine Zeile `geaendert: src/jarvis/ui_contract/fake.py`. Danach: `python -m tests.support.protected_manifest --check` (OK) und `python -m pytest tests/test_protected_files.py`. Unabhängige Gegenprobe: `--verify-against origin/main` zeigt genau den einen geänderten Eintrag. **Rückbau:** Manifestdatei auf den vorigen Stand zurücksetzen (`git checkout <alter Commit> -- tests/support/protected_manifest.json`).

## 3. Historischer UIA-Wächter und Beispielkonfiguration
Befund: `config/nexus.live.example.toml` enthält nur die Abschnitte `control_center`, `assistant`, `agents`, `goals`, `journal`, `files`, `llm`, `browser`, `research` (kein `[security]`, keine Schlüssel, keine Sicherheitsoptionen). Eine pauschale Ausnahme für `config/` wäre falsch: dort liegt `config/jarvis.toml` mit den Sicherheitsdefaults.
Vorschlag (nicht angewendet, `tests/test_v21_uia_guard_proposal.py`): Eine Datei unter `config/` ist erlaubt, **nur wenn** (1) ihr Name exakt `config/<name>.example.toml` ist (eine Ebene; nie `jarvis.toml`, kein Unterordner), (2) sie gültiges TOML und höchstens 20 KB groß ist, (3) nur die Abschnitte der Erlaubnisliste enthält, (4) keinen Sicherheitsschlüssel (`audit_strict`, `confirmation`, `allowed_roots`, `paper_trading_only`, `allow_activation`, `private_hosts_allowed` …) und keinen Geheimnis-Schlüssel (`token`, `api_key`, `*_secret` …) enthält und (5) der Geheimnis-Detektor nichts findet. 14 Negativtests (u. a. `[security]`, `audit_strict=false`, `confirmation="allow"`, `allowed_roots`, `paper_trading_only=false`, Geheimnis, kaputtes TOML, falscher Name) bleiben verboten; alle anderen geschützten Pfade bleiben auch zusammen mit einer erlaubten Beispieldatei verboten. `config/policy.example.toml` (Abschnitt `[rule]`) wird bewusst **nicht** erfasst.
Anwendung (Owner-Entscheidung, weil `tests/test_computer_uia_tools.py` im Manifest steht): dieselben vier Zeilen wie bei Option B plus Aufruf von `example_config_problems`; danach Manifest neu bestätigen (Abschnitt 2, zusätzlich Eintrag `tests/test_computer_uia_tools.py`).

## 4. Simulation der Integration mit PR #261 (Wegwerf-Worktree, nichts verändert)
Reproduzierbar: `python scripts/v2/simulate_pr_merge.py origin/claude/v2-186-finalisierung` (detached Worktree, Merge wird immer abgebrochen, Test belegt „kein Branch/Index/Worktree verändert“).
Ergebnis (Basis dieser Branch, 68 Dateien von #261):
| Konflikt | Auflösung (geprüft) |
|---|---|
| `src/jarvis/interface/ui_events.py`: beide Seiten ergänzen eine Importzeile (`uuid` aus main #264, `time` aus #261) | beide behalten: `import time` und `import uuid` – eindeutig |
| `tests/support/protected_manifest.json`: nur die Kopfzeilen (`base_commit`, `generated_at`) | Kopf egal; die Hashes ließen sich automatisch zusammenführen |
Zusätzlich folgt aus #261 (Datei `bootstrap.py`, Sprachsteuerung: `build_voice_session(..., handler=None)` und `VoiceSession(handler or core, …)`, 3 Zeilen):
- Der **Wirings-Pin** `tests/test_v21_bootstrap_wiring.py` (Fingerabdruck = V2.0-Stand) schlägt an, weil `bootstrap.py` sich legitim geändert hat. Neuer Fingerabdruck für „V2.0 + #261“: `8abcf5328e577b447084b2bb169b9282df8305b06b08475469d381c85ff9ece1` (alt: `cff1cd58e8462dfe6071bdc8e64d1ade5da28651476af5971ea6fc930a7f78e8`). Das ist eine Owner-Entscheidung, weil der Pin im Manifest steht.
- Das Manifest muss neu erzeugt werden: nach der Zusammenführung weichen **zwei** Einträge ab: `src/jarvis/ui_contract/fake.py` → `93ae46e78ecf98c04958b5aba5f903f7ec0e58b6e523940f859b932ab04b4885` (main #264 + #261 zusammengeführt, in keinem der beiden Manifeste) und `tests/test_v21_bootstrap_wiring.py` → `8271cc012d1c947f49e50e3b4c9c822afb57042d25729b843784a36da4476e72` (nach neuem Pin).
Gezielte Tests im simulierten Stand (alle grün): `test_ui_reset_contract`, `test_ui_event_bus`, `test_ui_contract`, `test_voice_level_meter`, `test_stop_speech`, `test_voice_stop_cancel`, `test_voice_text_route`, `test_voice_filename_dictation`, `test_stt_upgrade`, `test_resume_audit`, `test_nexus_feed`, `test_v2_agent_conformance`, `test_v2_goal_retry_safety`, `test_control_center_mission`, `test_nexus_ultimate_preview`; nach neuem Pin und neuem Manifest zusätzlich `test_protected_files` und `test_v21_bootstrap_wiring`. Offen blieb im simulierten Stand nur der UIA-Wächter (Abschnitt 3).
**Reihenfolge-Empfehlung:** #261 zuerst (Konflikt 1 trivial), danach `main` in `v2-integration`, danach **einmal** Wirings-Pin und Manifest nach Owner-Review neu bestätigen (ein gemeinsamer Schritt, zwei Dateien).

## 5. Wiederholungslogik: Prüfung und Lücken
Geprüft: abgebrochene Schreibaktionen (Timeout, Absturz), fehlgeschlagene Aktionen, Neuplanung, Wiederaufnahme.
| Frage | Befund |
|---|---|
| Wird ein Schreibschritt nach `timeout`/`step_failed`/`agent_crashed` automatisch wiederholt? | Nein (seit dem ersten Commit dieses PR); Warnung im Ergebnis |
| Wird er durch eine **Neuplanung** (LLM-Ersatzplan) umgangen? | **Lücke gefunden und geschlossen:** vorher wurde der Ersatzplan trotzdem angefordert (2 Modellaufrufe im Test) und hätte die Aktion erneut enthalten können. Jetzt keine Neuplanung, Warnung „not replanned“ |
| Darf ein Schritt wiederholt werden, dessen Agent **nie gestartet** wurde (`executor_failed`, `queue_full`)? | Ja, auch bei Schreibschritten – dort kann nichts doppelt geschehen (Code-Liste `NEVER_STARTED_CODES`, Test) |
| Wiederaufnahme nach Absturz: Schreibschritt mit Status `FAILED`, `TIMEOUT`, `RUNNING`, `CANCELLED`, `PENDING` | In allen fünf Fällen verlangt die Wiederaufnahme eine **neue Bestätigung**; ohne Zustimmung startet nichts (neue Tests); lesende Schritte ohne Rückfrage |
| Orchestrator: doppelter Start derselben Aufgabe | verhindert (bestehender Test `a task never runs twice`) |
Nicht geprüft/nicht abgedeckt: Wiederholungen **innerhalb** eines Agenten (z. B. Wiederholung eines Werkzeugaufrufs im Agenten), Verhalten bei echtem Dateisystem/Programmstart (nur Fakes), Windows.

## 6. CI-Status PR #270
Head `d57cd96`: Linux 6401 bestanden / 120 übersprungen / 1 fehlgeschlagen; Windows 6481 / 46 / 1. In beiden fehlt **nur** der Manifest-Test (Ursache 1 oben). Der UIA-Wächter wird in der CI übersprungen. Die V2.0-Baseline ist 5820/120 (Linux) und 5900/46 (Windows): Skips unverändert.

## 7. NEXUS ohne zusätzliche Freigaben verbessert
`nexus_feed` ist jetzt zusätzlich gegen den **echten** Assistenten-Adapter (`ControllerUiBackend`) und die echten V2-Ansichten getestet (Ereignisse ohne abgelehnte Einträge, echte Agentenregistrierung inkl. `strategist`, Not-Aus sichtbar, keine erfundenen Aufgaben/Freigaben). Weitere Verbesserungen (Route, JS) brauchen die Pin-Erweiterung und bleiben Owner-Entscheidungen.
