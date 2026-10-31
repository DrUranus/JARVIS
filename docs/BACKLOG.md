# Backlog (Stand: Basis `1d39e65`)

Quelle der Wahrheit fuer die automatische Fortsetzung ist `.github/automation/backlog.json` (nur der Besitzer aendert sie per Pull Request). Diese Datei ist eine lesbare Zusammenfassung und fuehrt nur, was im Repository belegt ist. Die Teilziele von Phase 14 stehen in `docs/PHASE14_AUTONOMY.md`; jedes braucht eine ausdrueckliche Freigabe.

## Umgesetzt (im Code auf `main`)

| Schritt | Ergebnis | Beleg |
|---|---|---|
| Phase 14, Teilziel 1 und 2 | gemeinsamer Notaus; Sichtbarkeit laufender Arbeit (GUI) | `docs/PHASE14_AUTONOMY.md` |
| `autonomy-invariants` (Teilziel 3) | Autonomie-Invarianten als Tests | PR #13 |
| `session-budget` (Teilziel 4) | optionales Sitzungsbudget (Standard aus) | PR #30 |
| `windows-capture-tests` | echte Windows-Tests fuer mss-Aufnahme/Monitorliste | PR #34 (in `backlog.json` als `done`) |
| `coding-windows-process-tree` | Coding-Provider beendet unter Windows den Prozessbaum (Job Object, `winjob`) | PR #38 |
| `persistent-results` | optionaler SQLite-Verlauf abgeschlossener Arbeit (`[history]`, nur Anzeige, nichts wird fortgesetzt) | PR #41 |
| `onboarding-windows` | `jarvis doctor` und `/doctor`, Windows-Schnellstart | PR #48 |
| `memory-semantic-search` | lokales, netzfreies Suchbackend (gehashte TF-IDF-Vektoren, `memory.backend`) | PR #50 |
| `voice-barge-in-hotword` | `VoiceSession.interrupt`, austauschbarer Hotword-Baustein (kein Detektor mitgeliefert) | PR #52 |

Hinweis: `backlog.json` markiert derzeit nur `windows-capture-tests`, `autonomy-invariants` und `session-budget` als `done`; die uebrigen oben genannten Schritte sind gemergt, aber dort noch nicht als `done` vermerkt (das Aendern der Datei ist Sache des Besitzers).

## In Arbeit

- `docs-sync` (dieser Schritt): README, `docs/TESTING.md`, `docs/BACKLOG.md` mit dem Ist-Stand abgleichen.

- `int-vetting-policy`: `docs/INTEGRATIONS.md` (Pruefschema und Vorlage fuer externe Bibliotheken) und `tests/test_integration_docs.py`; nur Dokument und Test.

## Offen, nicht freigegeben (nicht begonnen)

| Schritt | Inhalt |
|---|---|
| `audit-hash-chain` | Audit-Log: Hash-Kette und Rotation |
| `cli-confirm-timeout` | CLI-Bestaetigung mit Zeitlimit |
| `llm-goal-planning` | Goal Engine: LLM-gestuetzte Zielzerlegung (setzt `persistent-results` voraus) |
| `coding-llm-edits` | Coding-Agent: eigene Aenderungsentwuerfe (setzt `llm-goal-planning` voraus) |
| `smartphone-api-design` | Phase 12: Entwurf der Smartphone-Schnittstelle, nur Dokument |

Sicherheitskritische Schritte sind bewusst nicht in `approved_items` der Freigabe.

## Bekannte offene Punkte (Windows/Hardware)

- Windows-Nachweis kommt ausschliesslich aus `tests-windows` bzw. `tests.yml`; Mikrofon, Lautsprecher, echter Browser und Barge-in/Hotword mit Hardware sind manuell (siehe `docs/TESTING.md`).
- Tk-Startfehler auf dem Windows-Runner (`tk.tcl`, `icons.tcl`, `init.tcl`): Ursache nicht geklaert, siehe `docs/TESTING.md`.
