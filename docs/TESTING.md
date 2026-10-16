# Tests und CI

## Befehle (aus dem Repository-Stamm, Python >= 3.11)

```
pip install -e ".[dev]"                     # Windows zusaetzlich: ".[dev,voice]" (test_voice braucht sounddevice + numpy)
python -m pytest -rfEs --ignore=tests/test_gui_confirmation.py      # volle Suite
python -m pytest -rfEs -W error::pytest.PytestUnhandledThreadExceptionWarning \
  tests/test_self_improvement_keyfile.py tests/test_self_improvement_lock.py tests/test_self_improvement_process_tree.py \
  tests/test_self_improvement_security.py tests/test_security_paths_windows.py                              # Phase 15, gezielt
```

`tests/test_gui_confirmation.py` braucht `tkinter` und wird in der CI ausgeschlossen (unter Linux/Container fehlt es; unter Windows nicht geprueft).

## Gestufter Ablauf

1. Direkt betroffene Tests (`tests/test_<modul>_*.py`).
2. Sicherheitsregression: alle `*security*`-Tests.
3. Gezielte Windows-Tests (CI-Job `phase15-windows` oder die Phase-15-Dateien oben).
4. Volle Suite an Meilensteinen (CI-Job `suite`).

Pro Befund hoechstens drei gezielte Reparaturzyklen. Ein uebersprungener Test gilt nie als bestanden; Linux-Ergebnisse sind kein Windows-Nachweis.

## CI (`.github/workflows/tests.yml`)

| Ausloeser | Lauf |
|---|---|
| Push auf `claude/inspiring-ritchie-8ljinw` (nur bei Aenderungen in `src/`, `tests/`, `pyproject.toml`, Workflow) | `phase15-windows` (windows-latest, py3.13, Prozessbaum-Test 5x) |
| Push mit `[ci-full]` in der letzten Commit-Nachricht | zusaetzlich `suite`: Windows py3.13, Ubuntu py3.13, Ubuntu py3.11 |
| `workflow_dispatch` (nur nutzbar, wenn die Datei auf dem Standard-Branch liegt) | `scope` = phase15 / full / all, `repeat` 1-50 |

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

Die 38 Windows-Skips: POSIX-Symlinks/-Skripte/-Modusbits, X11/Xvfb, `playwright` nicht installiert (echte Browser-Tests laufen in der CI nicht), Linux-`/proc`-Test.

## Umgebungsbefunde (nicht mit Codefehlern verwechseln)

- Der Runner-Prozess laeuft selbst in einem Job Object (`LimitFlags 0x0`); die verschachtelte Zuweisung (Suspended-Start -> Job -> Resume) funktioniert dort.
- Das Runner-Konto hat die RID 500; `Get-Acl` schreibt es als SDDL-Alias `LA` (siehe `winsec.py`). Neue Dateien tragen dort einen expliziten OWNER-RIGHTS-Eintrag (S-1-3-4).
- PowerShell-Aufrufe sind auf dem gehosteten Runner sehr langsam (grob 20 s je Aufruf, Messung aus `--durations`): die ACL-Tests dominieren die Laufzeit (Phase-15-Job 4-18 min, volle Windows-Suite 16-33 min).

## Nicht abgedeckt / manuell

- Mikrofon, Lautsprecher, echte GUI-Interaktion, echter Browser (Playwright), X11-Tests unter Windows.
- Verhalten ausserhalb der Runner-Umgebung (andere Konten, Domaenen, Antivirus).
- Phase 15 bleibt ein deaktivierter Vorschlagsworkflow; es gibt keine Sandbox. Job Objects sind Eindaemmung, keine Isolation.
