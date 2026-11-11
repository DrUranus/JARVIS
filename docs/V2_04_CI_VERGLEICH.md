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
