# V2-04: Tägliche gezielte Tests gegen seltenere Vollsuite (Vergleich, nur Plan)

**Status: Entscheidungsgrundlage. Es wird kein Workflow angelegt, geändert oder aktiviert.** `.github/` darf nur der Besitzer ändern (`CLAUDE.md`); alles Folgende ist Stoff für einen späteren Besitzer-PR. Release-Freeze und V1-Abnahme #186 haben Vorrang. Ergänzt `docs/V2_PHASE_A.md` Abschnitt 3.

## 1. Gemessene Ausgangslage (aus echten Läufen am 2026-11-11)
| Lauf | Dauer (ca.) | Beleg |
|---|---|---|
| `tests-linux` (Vollsuite, Ubuntu) | 3 bis 4 Minuten | PR-Läufe #229, #232, #233 (08:31–08:35, 08:45–08:49) |
| `tests-windows` (Vollsuite) | 22 bis 25 Minuten | Läufe auf `7cc65b0`; Windows 5248 bestanden / 45 übersprungen |
| `gui + voice + emergency stop` (Windows, gezielt) | rund 1 Minute | Lauf 42987672361 |
| `real-browser` (Ubuntu / Windows) | unter 1 bis 1,5 Minuten | Lauf 42987707166 |
| Fresh Install, Browser Research, GUI E2E | nicht einzeln neu vermessen | |

Diese Zahlen sind Stichproben, keine Statistik; Laufzeiten schwanken mit der Runner-Auslastung.

## 2. Varianten
| | **V-Täglich-voll** | **V-Täglich-gezielt + Wöchentlich-voll** | **V-Bei-Änderung** |
|---|---|---|---|
| Täglich | Vollsuite beider Systeme + Release-Matrix | gezielte Läufe: Sicherheitsregression (`tests/test_*security*.py`, `test_emergency_stop.py`), GUI/Voice/Not-Aus (Windows), Linux-Vollsuite | wie täglich-voll, aber nur wenn `main` sich seit dem letzten grünen Lauf änderte |
| Selten | – | Windows-Vollsuite + Fresh Install + Browser Research + GUI E2E, einmal pro Woche und vor jedem Release | – |
| Windows-Minuten/Woche (grob) | 7 × 25 = rund 175 | 7 × 1 + 1 × 25 = rund 32 | höchstens 7 × 25, meist deutlich weniger |
| Zeit bis Fehler sichtbar | höchstens 1 Tag | Sicherheits-/Not-Aus-Fehler: 1 Tag; reine Windows-Spätfehler: bis 1 Woche | höchstens 1 Tag nach der Änderung |
| Risiko übersehener Windows-Regression | gering | **mittel** (Lücke bis zu 6 Tage für Fehler, die nur die Windows-Vollsuite zeigt) | gering |
| Rauschen/Kosten | höchste Kosten, nachts leer, wenn nichts geändert | niedrig | niedrig bis mittel |
| Aufwand `.github/` | Cron in den bestehenden Workflows | zwei Cron-Einträge, zwei Bereichsvarianten (`scope`) | Cron plus Änderungsprüfung (SHA-Vergleich) |

Die bestehende `tests.yml` unterscheidet bereits `scope` (gui, phase15, full, all) bei `workflow_dispatch`; ein geplanter Lauf hat keine `inputs`, die Bedingungen müssten angepasst werden (Besitzer-PR).

## 3. Empfehlung (Entscheidung beim Besitzer)
**V-Bei-Änderung**, kombiniert mit der Vollsuite vor jedem Release: höchstens einmal nachts, nur wenn `main` seit dem letzten grünen Lauf geändert wurde, nur `main`, `contents: read`, keine Secrets, kein Commit/Push/PR, keine automatische Wiederholung und keine Berührung von `jarvis-controller.yml`. **Solange V1 nicht abgenommen ist und `main` eingefroren bleibt, ändert sich `main` nicht; die Regel würde dann gar nicht auslösen.** Wenn Windows-Minuten knapp sind, ist V-Täglich-gezielt + Wöchentlich-voll die günstigere Rückfalllösung, mit dem benannten Risiko der Spätentdeckung.

## 4. Abnahmekriterien (für den späteren Besitzer-PR)
1. Läuft nur auf `main`; erzeugt nie Commit, Push, PR, Issue-Kommentar oder Merge-Gate-Änderung.
2. Berechtigungen `contents: read`; keine neuen Secrets oder Berechtigungserweiterungen (kein `actions: write`).
3. Ergebnis je Lauf sichtbar: Jobs, bestanden/übersprungen, Skip-Gründe.
4. Fehlschlag ist nur eine Meldung; Beheben nur durch Menschen oder gesonderten Auftrag.
5. Sicherheitsprüfung des Workflows wie bei den bisherigen Workflow-PRs.

## 5. Offene Entscheidungen
Variante (siehe 3), Uhrzeit (außerhalb der Arbeitszeit), ob Windows-Minuten ein Budget haben, und ob Ergebnismeldungen an einen bestimmten Ort gehen sollen. Solange nichts entschieden ist, bleibt es ungeplant.

## 6. Übersprungene Tests (Linux-Vollsuite lokal, 2026-11-11)
Lokal (Linux, `python -m pytest -rs tests`): **0 Fehlschläge, 93 übersprungen**; die CI-Ubuntu-Läufe melden 119 Skips (Abweichung durch andere installierte Zusatzpakete, hier **nicht itemisiert**). Gründe der lokalen 93:
| Anzahl | Grund |
|---|---|
| 23 | NTFS-Junctions/Reparse Points nur unter Windows (`tests/test_security_paths_windows.py`; POSIX-Symlink-Tests decken Linux ab) |
| 13 + 1 + 1 + 1 | Windows-Pfadsemantik bzw. Windows-Prozesssemantik |
| 11 | optionale Bibliotheken fehlen (`pip install -e '.[computer]'`) |
| 8 | echte Windows-ACL-Mechanik (PowerShell/icacls) |
| 8 + 5 | Windows Job Objects / `taskkill` |
| 6 | echte Windows-Desktopaufnahme (mss/GDI) |
| 6 | UI Automation nur unter Windows |
| 4 | echte Win32-API |
| 2 | natives pywebview-Fenster nur Windows |
| 2 | `tkinter` nicht importierbar (Umgebung) |
| 1 + 1 | öffentliche Web-Prüfung braucht `JARVIS_TEST_PUBLIC_WEB=1` und Internet; `trafilatura` fehlt |
Die Windows-spezifischen Skips sind **auf Linux kein Nachweis** und werden nur vom Windows-CI-Lauf belegt (dort 45 Skips auf der Vollsuite; ihre Gründe wurden hier **nicht itemisiert**). Ein übersprungener Test gilt nie als bestanden.

## 7. Windows-Skips (Job `tests-windows`, PR #229, Lauf 42987707150, 2026-11-11)
Ergebnis laut Log: **5270 bestanden, 46 übersprungen, 0 Fehlschläge** (21:18 Min.). Die V1-Referenz auf `main` meldete 45 Skips; **der eine Unterschied ist nicht belegt**. Vermutung (ungeprüft): der Test `test_computer_uia_tools.py:384` („kein origin/main in diesem Checkout“) überspringt im PR-Checkout, weil dort `origin/main` fehlt. Gründe aller 46 (aus der Zusammenfassung des Logs):
| Anzahl | Grund | Bedeutung für den Nachweis |
|---|---|---|
| 13 | POSIX-Symlinks bzw. -Semantik (`test_security_paths.py` 7, `test_security_engine.py` 3, `test_computer_controller.py` 1, `test_computer_tools.py` 1, `test_security_tools.py` 1) | Windows-Entsprechung: NTFS-Junctions/Reparse Points in `test_security_paths_windows.py` (laufen unter Windows) |
| 11 | echtes X11/Xvfb nur unter Linux (`test_computer_x11_real.py`) | Linux-CI deckt ab; Windows nicht zutreffend |
| 7 | `playwright` fehlt im Job `tests-windows` (`test_analysis_real`, `test_browser_real`, `test_control_center_e2e_browser` 2, `test_research_real_browser`, `test_browser_basics` 2) | wird im eigenen Job `real-browser (windows-latest)` belegt (in #229 grün) |
| 5 | POSIX-Shellskripte (`test_computer_providers.py` 4, `test_computer_security.py` 1) | nicht zutreffend unter Windows |
| 2 | `JARVIS_NATIVE_GUI=1` fehlt (`test_control_center_native_windows.py`) | **nur auf einem interaktiven Windows-Desktop belegbar, gehört zur Abnahme #186; nicht bestanden, nur übersprungen** |
| 1 | `trafilatura` nicht installiert (`test_research_extract_backend.py`) | optionale Bibliothek; Backend-Test läuft nicht |
| 1 | Symlink-Erzeugung braucht unter Windows ein Recht (`test_office.py:411`); „der Windows-CI-Lauf ist der Plattformnachweis“ | Lücke: Symlink-Fall dort nicht ausgeführt |
| 1 | kein `origin/main` im Checkout (`test_computer_uia_tools.py:384`) | Umgebungseffekt des Checkouts |
| 1 | `no X11 on Windows` (`test_computer_integration.py:151`) | nicht zutreffend |
| 1 | `git` und POSIX-Shellskript nötig (`test_coding_real.py:282`) | nicht zutreffend |
| 1 | POSIX-Dateimodus-Bits (`test_self_improvement_keyfile.py:239`); Windows-Entsprechung sind die ACL-Tests | Ersatztests laufen |
| 1 | Prozessbaum: unter Windows wird die echte Win32-Schicht genutzt (`test_self_improvement_process_tree.py:136`) | Ersatztests `win_*` laufen |
| 1 | Nachfahrenerkennung über `/proc` nur Linux; „Windows is untested“ (`test_self_improvement_workspace.py:451`) | **echte Lücke**: Windows-Fall dieser Funktion ungetestet |
Zwei Skips sind **echte Windows-Lücken** (Symlink-Recht in `test_office.py`, `/proc`-Nachfahrenerkennung im Workspace-Test) und zwei hängen an der interaktiven Abnahme (#186). Alle übrigen sind plattformbedingt oder durch Ersatztests/andere Jobs abgedeckt. Ein übersprungener Test gilt nie als bestanden.
