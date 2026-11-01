# Backlog (Stand: Release-Plan)

Quelle der Wahrheit fuer die automatische Fortsetzung ist `.github/automation/backlog.json` (nur der Besitzer aendert sie per Pull Request). Diese Datei ist eine lesbare Zusammenfassung und fuehrt nur, was im Repository belegt ist. Die Teilziele von Phase 14 stehen in `docs/PHASE14_AUTONOMY.md`; jedes braucht eine ausdrueckliche Freigabe.

## Umgesetzt (im Code auf `main`)

| Schritt | Ergebnis | Beleg |
|---|---|---|
| Phase 14, Teilziel 1 und 2 | gemeinsamer Notaus; Sichtbarkeit laufender Arbeit (GUI) | `docs/PHASE14_AUTONOMY.md` |
| `autonomy-invariants` (Teilziel 3) | Autonomie-Invarianten als Tests | PR #13 |
| `session-budget` (Teilziel 4) | optionales Sitzungsbudget (Standard aus) | PR #30 |
| `windows-capture-tests` | echte Windows-Tests fuer mss-Aufnahme/Monitorliste | PR #34 |
| `coding-windows-process-tree` | Coding-Provider beendet unter Windows den Prozessbaum (Job Object, `winjob`) | PR #38 |
| `persistent-results` | optionaler SQLite-Verlauf abgeschlossener Arbeit (`[history]`, nur Anzeige) | PR #41 |
| `onboarding-windows` | `jarvis doctor` und `/doctor`, Windows-Schnellstart | PR #48 |
| `memory-semantic-search` | lokales, netzfreies Suchbackend (gehashte TF-IDF-Vektoren, `memory.backend`) | PR #50 |
| `voice-barge-in-hotword` | `VoiceSession.interrupt`, austauschbarer Hotword-Baustein (kein Detektor mitgeliefert) | PR #52 |
| `docs-sync` | README, TESTING, BACKLOG mit dem Stand abgeglichen | PR #55 |
| `int-vetting-policy` | Pruefschema fuer externe Bibliotheken (`docs/INTEGRATIONS.md`, `tests/test_integration_docs.py`) | PR #58 |
| `uia-vetting` | Pruefbericht pywinauto 0.6.9 (`docs/integrations/windows-uia.md`), isolierter Windows-Kompatibilitaetstest (`ci/uia-compat`, `docs/uia-compat-results.md`) | PR #60, #61 (Auftrag #59 war blockiert, Bericht manuell) |
| `uia-model-fake` | UI-Automation-Modell, lesende Schnittstelle `UiTreeProvider`, Fake-Provider (nur Modell) | PR #62 |
| `uia-provider-readonly` | lesender Provider mit pywinauto 0.6.9 im Worker-Prozess (Extra `uia`, `computer.uia_enabled`, Standard aus); Freigabezeile in PR #63 | PR #63, #65 |
| `uia-tools-readonly` | lesendes Tool `ui` (`windows`, `tree`, `find`), YELLOW, Sperrliste, Passwortschutz, Redaktion, Notaus, Budget; nur mit `uia_enabled` | PR #66 |

In `backlog.json` sind diese Schritte als `done` markiert (ein Schritt ohne Vermerk wuerde von der Automatik erneut gestartet). Alle Schritte von `plan.approved_items` sind erledigt: es ist **kein freigegebener Schritt offen**.

## In Arbeit und freigegeben (offen)

Reihenfolge, in der die Automatik die Schritte waehlt (Reihenfolge in `backlog.json`; Planung, Rechte und Risiken: `docs/RELEASE_PLAN.md`):

1. **LLM-Kette** (freigegeben mit PR #69, Kette gestartet): `llm-compat-vetting`, `llm-compat-provider`, `llm-routing-design`, `llm-routing-policy`.
2. **Lokale Sprache:** `stt-vetting`, `stt-local-provider` (Besitzer-Freigabezeile im Pruefdokument noetig), `stt-vad-endpointing`.
3. **Recherche:** `research-vetting`, `research-search-interface`, `research-extract-backend` (Besitzer-Freigabezeile noetig), `research-search-provider` (Suchquelle waehlt der Besitzer).
4. **UI-Aktionen (sicherheitskritisch):** `uia-actions`, `uia-agent-integration`, `uia-windows-e2e`.
5. **Zielplanung und Coding (sicherheitskritisch):** `llm-goal-planning` (haengt zusaetzlich von `llm-routing-policy` ab), `coding-llm-edits`.

## Offen, nicht freigegeben (nicht begonnen)

| Schritt | Inhalt |
|---|---|
| `audit-hash-chain` | Audit-Log: Hash-Kette und Rotation (sicherheitskritisch) |
| `cli-confirm-timeout` | CLI-Bestaetigung mit Zeitlimit (sicherheitskritisch) |
| `smartphone-api-design` | Phase 12: Entwurf der Smartphone-Schnittstelle, nur Dokument (zuletzt) |
| `mcp-security-review`, `os-sandbox-design`, `mail-design`, `office-design`, `media-design` | spaetere Entwuerfe (nur Dokumente) |

Sicherheitskritische Schritte stehen nur dann in `approved_items`, wenn der Besitzer sie ausdruecklich freigibt.

## Bekannte offene Punkte (Windows/Hardware)

- Windows-Nachweis kommt ausschliesslich aus `tests-windows` bzw. `tests.yml`; Mikrofon, Lautsprecher, echter Browser und Barge-in/Hotword mit Hardware sind manuell (siehe `docs/TESTING.md`).
- Tk-Startfehler auf dem Windows-Runner (`tk.tcl`, `icons.tcl`, `init.tcl`): Ursache nicht geklaert, siehe `docs/TESTING.md`.
