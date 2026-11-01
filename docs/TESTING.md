# Tests und CI

## Befehle (aus dem Repository-Stamm, Python >= 3.11)

```
pip install -e ".[dev]"                     # Windows zusaetzlich: ".[dev,voice]" (test_voice braucht sounddevice + numpy)
python -m pytest -rfEs                                               # volle Suite (GUI-Tests ueberspringen sich ohne tkinter/Anzeige selbst)
python -m pytest -rfEs -W error::pytest.PytestUnhandledThreadExceptionWarning \
  tests/test_self_improvement_keyfile.py tests/test_self_improvement_lock.py tests/test_self_improvement_process_tree.py \
  tests/test_self_improvement_security.py tests/test_security_paths_windows.py                              # Phase 15, gezielt
```

GUI-Tests: `tests/test_gui_model.py` (ohne Tk, ueberall), `tests/test_gui_view.py` und `tests/test_gui_confirmation.py` (echtes Tk-Fenster; ohne `tkinter`/Anzeige uebersprungen). Lokal unter Linux ohne Tk-Python: `apt install python3-tk xvfb`, dann `xvfb-run -a python3 -m pytest tests/test_gui_*.py`.

## Gestufter Ablauf

1. Direkt betroffene Tests (`tests/test_<modul>_*.py`).
2. Sicherheitsregression: alle `*security*`-Tests.
3. Gezielte Windows-Tests (CI-Job `phase15-windows` oder die Phase-15-Dateien oben).
4. Volle Suite an Meilensteinen (CI-Job `suite`).

Pro Befund hoechstens drei gezielte Reparaturzyklen. Ein uebersprungener Test gilt nie als bestanden; Linux-Ergebnisse sind kein Windows-Nachweis.

## CI-Workflows (Stand: Basis `1d39e65`)

| Workflow | Ausloeser | Zweck |
|---|---|---|
| `pr-tests.yml` | Pull Request gegen `main` aus einem `claude/*`-Branch des Repositories (opened/synchronize/reopened/ready_for_review); `workflow_dispatch` nur fuer `claude/*`-Branches (vom Merge-Gate nach "Branch aktualisieren") | Pflichtpruefung: volle Suite, Job `tests-linux` (ubuntu-latest) und Job `tests-windows` (Windows, mit `.[dev,voice]`), je auf dem Head-Commit des PR, JUnit-Berichte als Artefakt |
| `jarvis-merge-gate.yml` | Push auf `main`, Abschluss von `pr-tests`, Zeitplan alle 20 Minuten, `workflow_dispatch` | Merge-Gate: merged einen `claude/*`-PR nur, wenn `tests-linux` und `tests-windows` auf genau dem Head-Commit gruen sind; sensible Pfade (z. B. `src/jarvis/permissions/`) nur mit konkreter Freigabe, sonst merged der Besitzer selbst |
| `jarvis-gate-resume.yml`, `jarvis-controller.yml`, `jarvis-report.yml`, `jarvis-watchdog.yml`, `claude-routine-fire.yml`, `automation-ci.yml` | siehe `.github/automation/README.md` | Automatisierung der Routinen-Auftraege (Kette, Berichte, Pruefung der Automatisierungsskripte) |
| `tests.yml` | siehe unten | gezielte Windows-Laeufe (GUI, Phase 15) und volle Suite auf Abruf |

Ein Windows-Nachweis entsteht nur durch einen gruenen `tests-windows`-Job (oder `tests.yml`) auf dem betreffenden Commit; Linux-Laeufe in einer Routinen-Sitzung ersetzen ihn nicht.

## `tests.yml`

| Ausloeser | Lauf |
|---|---|
| Push auf einen `claude/**`-Branch (nur bei Aenderungen in `src/`, `tests/`, `pyproject.toml`, Workflow) | `gui-windows` (windows-latest, py3.13, ca. 1-2 min): GUI-, Voice-, Notaus- und Berechtigungs-Tests |
| Push, dessen letzte Commit-Nachricht das Stichwort in eckigen Klammern `ci-phase15` enthaelt | zusaetzlich `phase15-windows` (ACL/Job-Object/Junction-Tests, Prozessbaum-Test 5x; langsam) |
| Push, dessen letzte Commit-Nachricht das Stichwort `ci-full` in eckigen Klammern enthaelt | zusaetzlich `suite`: Windows py3.13, Ubuntu py3.13, Ubuntu py3.11 |
| `workflow_dispatch` (nur nutzbar, wenn die Datei auf dem Standard-Branch liegt) | `scope` = gui / phase15 / full / all, `repeat` 1-50 |

Achtung: Die Stichwoerter wirken, sobald sie irgendwo in der Commit-Nachricht stehen (auch in einer Beschreibung). Wer sie nur erwaehnen will, schreibt sie ohne eckige Klammern.

Nur `contents: read`, keine Secrets; Actions sind auf Commit-SHAs gepinnt. Jeder Lauf prueft zuerst, dass der Phase-15-Stand im Checkout steckt, schreibt den Commit-SHA in die Zusammenfassung und laedt JUnit-Berichte als Artefakt hoch (auch bei Fehlschlag). Der Job scheitert auch, wenn kein bestandener Windows-Pflichttest vorhanden ist.

## Ergebnisse auf echten Runnern (GitHub, Oktober 2026)

| Lauf | Commit | Ergebnis |
|---|---|---|
| Phase 15, Windows, py3.13 | 866d1bc | 13 failed / 146 passed / 2 skipped (ACL-Alias `LA`, Fake-Resume-Tests) |
| Phase 15, Windows, py3.13 | d58be3f | 2 failed / 163 passed / 2 skipped |
| Phase 15, Windows, py3.13 | d62e486 | **165 passed / 2 skipped** |
| Volle Suite, Windows, py3.13 | 648422f | 1 failed (numpy fehlte fuer test_voice) / 3472 passed / 38 skipped |
| Volle Suite, Windows, py3.13 | dc2d3d6 | **3473 passed / 38 skipped** |
| Volle Suite, Ubuntu py3.13 und py3.11 | dc2d3d6 | **je 3437 passed / 74 skipped** |
| GUI + Voice, Windows, py3.13 (Tk 8.6, Anzeige 1024x768) | dfffaf9 | **105 passed / 0 skipped** (alle Fenstertests liefen wirklich, ca. 6 s) |
| GUI + Voice + Notaus + Berechtigungs-Regression, Windows, py3.13 | 3ef61ac (Lauf 39032720754) | **410 passed / 4 skipped** (POSIX-Symlinks); Fenstertests mit echter Engine liefen wirklich, ca. 8 s |
| GUI + Voice + Notaus + Berechtigungs-Regression, Windows, py3.13 | 4885171 (Lauf 39153201869) | 414 passed / 5 skipped: **ein** Fenstertest wurde einmalig uebersprungen, weil Tk auf dem Runner `tk.tcl` nicht fand (nicht reproduziert) |
| dito, nach `JARVIS_GUI_TESTS_REQUIRED=1` (ein nicht startendes Tk faellt jetzt durch statt zu skippen) | 85b036f (Lauf 39153347774) | **415 passed / 4 skipped** (nur POSIX-Symlinks) ; Tk 8.6 startete, alle 17 Fenstertests bestanden, keiner uebersprungen. Spaetere Commits (z. B. b6f7805) aendern nur Dokumentation (`src/`, `tests/`, `.github/`, `pyproject.toml` sind baumgleich) und loesen wegen des Pfadfilters keinen Lauf aus. |
| GUI + Notaus + Regression nach Teilziel 2 (Laufende Arbeit), Windows, py3.13 | 33c5cc0 (Lauf 39219813871) | 433 passed / 4 skipped / **1 error**: Tk startete fuer *einen* Fenstertest nicht (`tk.tcl`/`icons.tcl` nicht lesbar) - Umgebungsfehler, kein Fehler im Code |
| dito, mit Tk-Start-Retry | 8f0b2dd (Lauf 39220035919) | **434 passed / 4 skipped / 1 warning** (Tk brauchte bei einem Test 2 Versuche: `init.tcl`); alle 23 Fenstertests, 46 Modelltests, 39 Notaus-Tests und die 18 Aktivitaets-/Abbruchtests bestanden |
| Volle Suite, Windows, py3.13 | dfffaf9 | **3525 passed / 38 skipped** (31 min) |
| Volle Suite, Ubuntu py3.13 und py3.11 | dfffaf9 | **je 3476 passed / 87 skipped** (GUI-Fenstertests ohne tkinter uebersprungen) |
| Phase 15, Windows, py3.13 | dfffaf9 | **165 passed / 2 skipped** (19 min) |

Die 38 Windows-Skips (Stand dc2d3d6, vor Phase 11): POSIX-Symlinks/-Skripte/-Modusbits, X11/Xvfb, `playwright` nicht installiert (echte Browser-Tests laufen in der CI nicht), Linux-`/proc`-Test.

### Linux-Lauf der Routine docs-sync (Basis `1d39e65`, Python 3.13, ohne Tk/Anzeige, ohne Windows)

| Lauf | Ergebnis |
|---|---|
| `python -m pytest -rfEs tests/test_*security*.py tests/test_emergency_stop.py` | **801 passed / 23 skipped** (Windows-Junction-/ACL-Tests werden auf Linux uebersprungen) |
| `tests/test_history_store.py test_doctor.py test_memory_semantic.py test_voice_bargein_hotword.py test_coding_process_tree.py test_computer_capture_win32_real.py` | **80 passed / 11 skipped** (Windows-only-Tests uebersprungen) |

Das ist ausdruecklich **kein** Windows-Nachweis: Windows-Nachweis ausstehend, bis `tests-windows` bzw. `tests.yml` fuer den Merge-Commit gruen ist. Eine volle Suite lief in dieser Sitzung nicht; die Zahlen der Tabelle oben stammen aus frueheren Laeufen auf den genannten Commits und wurden hier nicht neu erhoben (die Phase-11-Zeilen sind aelter als die Phasen History/Doctor/Memory-Suche/Barge-in).

## Umgebungsbefunde (nicht mit Codefehlern verwechseln)

- Der Runner-Prozess laeuft selbst in einem Job Object (`LimitFlags 0x0`); die verschachtelte Zuweisung (Suspended-Start -> Job -> Resume) funktioniert dort.
- Das Runner-Konto hat die RID 500; `Get-Acl` schreibt es als SDDL-Alias `LA` (siehe `winsec.py`). Neue Dateien tragen dort einen expliziten OWNER-RIGHTS-Eintrag (S-1-3-4).
- PowerShell-Aufrufe sind auf dem gehosteten Runner sehr langsam (grob 20 s je Aufruf, Messung aus `--durations`): die ACL-Tests dominieren die Laufzeit (Phase-15-Job 4-18 min, volle Windows-Suite 16-33 min).

## Nicht abgedeckt / manuell

- **Manuell (Notaus):** Mit einer laufenden, langen Aktion (z. B. `/run coding action=test` auf einem langsamen Testlauf) im GUI-Fenster NOTAUS druecken: Zustand "NOTAUS", Bericht im Chat; pruefen, dass ein laufender Testprozess wirklich endet (Taskmanager) und dass bereits Ausgefuehrtes bestehen bleibt. Reset ueber den Dialog pruefen.
- **Manuell (GUI/Voice, nicht automatisierbar):** (1) `jarvis-gui` starten: Fenster erscheint, Skalierung/Lesbarkeit pruefen. (2) Text senden, Zustandspunkt wechselt Bereit -> Verarbeiten -> Bereit. (3) Eine Aktion ausloesen, die Bestaetigung braucht (z. B. `/run` mit einem YELLOW-Tool): Dialog erscheint, Zustand "Wartet auf Bestaetigung", Ablehnen/Erlauben wirkt. (4) Mit echtem Mikrofon und `voice.stt_provider != console`: "Sprache starten", sprechen, Zuhoeren -> Verarbeiten -> Sprechen, Lautsprecher hoerbar, "Sprache beenden". (5) Fenster waehrend einer laufenden Anfrage schliessen: Rueckfrage erscheint. (6) Barge-in/Hotword mit echter Hardware (nur manuell, Fake-Tests: `tests/test_voice_bargein_hotword.py`): waehrend einer Sprachausgabe `VoiceSession.interrupt()` ausloesen, Ausgabe bricht ab (nur Windows/sounddevice); ein registrierter lokaler Detektor mit echtem Mikrofon reagiert nur auf das Hotword und fuehrt nie eine bestaetigungspflichtige Aktion ohne Dialog aus.
- Mikrofon, Lautsprecher, echter Browser (Playwright), X11-Tests unter Windows.
- Windows-Runner: ein Fenstertest wurde einmal wegen eines nicht auffindbaren `tk.tcl` uebersprungen (Lauf 39153201869, nicht reproduziert). Seit 85b036f scheitert der Job in so einem Fall sichtbar. Es trat danach in 2 von 3 Laeufen wieder auf (jedes Mal ein anderer Test, `tk.tcl`, `icons.tcl`, `init.tcl`); seit 8f0b2dd wird der Start bis zu dreimal versucht und jeder Wiederholungsversuch als Warnung ausgegeben. Die Ursache ist **nicht ermittelt** (Verdacht: transienter Dateizugriff auf dem Runner, z. B. Virenscanner); eine Wiederholung hat bisher jedes Mal geholfen.
- Verhalten ausserhalb der Runner-Umgebung (andere Konten, Domaenen, Antivirus).
- Phase 15 bleibt ein deaktivierter Vorschlagsworkflow; es gibt keine Sandbox. Job Objects sind Eindaemmung, keine Isolation.

## Echte Windows-Aufnahmetests (Computer-Provider)

`tests/test_computer_capture_win32_real.py` prueft den mss-Provider (Monitorliste, Screenshot je Monitor, Fehlerfaelle) auf einem echten Windows-Desktop. Nur Lesen: keine Maus-/Tastatureingabe, kein Start fremder Programme. Auf Nicht-Windows, ohne `mss` oder ohne interaktiven Desktop wird mit Grund uebersprungen. `mss` kommt unter Windows ueber das Extra `dev` (`pyproject.toml`). Windows-Nachweis liefert nur der CI-Windows-Lauf.

`tests/test_computer_uia_provider.py` prueft den lesenden UIA-Provider (Schritt `uia-provider-readonly`). Linux und Windows: Protokoll mit einem Test-Worker, Zeitlimit, Notaus, Sitzungsbudget, Passwortfelder ohne Wert, fehlende Bibliothek, Strukturtests (keine Eingabe, kein Klick). Nur Windows: `TestRealWindow` liest ein per Subprozess gestartetes Notepad-Fenster mit pywinauto (Extra `uia`, in `dev` unter Windows enthalten); ist die Bibliothek nicht installiert, schlaegt der Test fehl, er wird nicht uebersprungen. Kein Tk-Fenster (Tk-Startfehler auf dem Runner sind ein bekannter, ungeklaerter Umgebungseffekt). Windows-Nachweis liefert nur der CI-Windows-Lauf.
