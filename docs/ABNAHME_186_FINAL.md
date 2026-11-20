# #186 – Abschlussübersicht (Stand 2026-11-20, Commit 792d832, PR #261)
Ehrliche Bewertung gegen Issue #186 (B9-Punkte) und `docs/WINDOWS_V1_ABNAHME.md`, Abschnitt 16. Belege: `docs/ABNAHME_186_MATRIX.md`. Nichts hier ersetzt eine Owner-Entscheidung.

## BESTANDEN (Owner am echten Windows-Desktop, soweit „USER“)
| Kriterium aus #186 | Beleg |
|---|---|
| Orb ↔ Dashboard manuell (B9-1a) | USER 2026-11-18 |
| automatische Umschaltung nach Aufgabenkomplexität (B9-1b) | USER 2026-11-18 (Ziel mit 3 Schritten) |
| Overlay: Größe, Fokus, Öffnen des Hauptfensters, Always-on-Top (B9-2/2b) | USER 2026-11-18 (nach Fix `min_size`) |
| Freigabe: Dialog, Ablehnen = Standard (B9-3), Timeout (3b) | USER 2026-11-14 |
| Schließen/Neuladen = abgelehnt (B9-3c); Strg+C bei offener Frage = nichts ausgeführt (3d) | USER 2026-11-18 |
| Not-Aus aus Dashboard, Orb, Overlay (B9-4a/b/c) und Aufheben mit Rückfrage (Reset) | USER 2026-11-18 (Reset-Knopf in `744384f` ergänzt) |
| Animationen reduzieren; 2D-Fallback dokumentiert (B9-5) | USER 2026-11-14; Doctor „Canvas-2D“ |
| Dateiauftrag per Tastatur: Dialog, Ablehnen, Zustimmen (S5) | USER 2026-11-15/20 |
| Resume: Liste, `unknown_task`, neue Frage, Ablehnen (S9) | USER 2026-11-18/20; Audit: `confirmation_requested` 12:16:58 und `confirmation_rejected` 12:17:15 UTC für `resume_step` |
| Sprache: Start/Beenden, „Antwort stoppen“, Dateifreigabe per Sprache, Rückfrage bei unklarem Dateibefehl, Ablehnen | USER 2026-11-20 (laut Owner-Bericht) |
| CI auf 792d832: `tests`, Control Center GUI E2E | grün (GitHub-API) |
| CI auf 664cc0a: `uia-compat` | grün |

## Geprüft ohne Befund
- **Resume nach Ablehnen:** Journal: Ziel `g-291cc289694f` weiter `WAITING` (Agenten-Task `RUNNING` aus dem früheren Abbruch), keine neue Ausführung, `workspace\b93d_retry2.txt` existiert nicht, kein `permission_granted`/`execution_result`. Status ist damit „offen, nicht ausgeführt“, nicht „abgeschlossen“; Aufräumen bleibt Owner-Entscheidung (F-S9-2).
- **`FilesError`/`invalid_input` (2 Einträge am 20.11., 1 am 18.11.):** Ursache belegt: `file_exists` – `files.create` überschreibt nie (`files/controller.py`), und `workspace\notizen.txt` (seit 15.11.) bzw. `b93c.txt` existierten schon. Die Ablehnung passiert vor der Freigabefrage (fail-closed, keine Datei verändert). Kein Sicherheits- oder V1-Blocker; die Meldung an den Nutzer („invalid_input“) ist schwach, eine Verbesserung wäre ein späteres Komfortthema.

## OFFEN (nicht als bestanden zu werten)
1. **`pr-tests`** (Windows + Linux): für 664cc0a zuletzt „in Bearbeitung“, für 792d832 nicht gestartet. Das Release-Kriterium verlangt Pflicht-CI auf dem Release-Commit; Owner startet `pr-tests` (und zur Vollständigkeit `uia-compat`) einmal für den endgültigen Commit.
2. **`docs/WINDOWS_V1_ABNAHME.md`:** Die Spalte „PC-Ergebnis“ ist durchgehend `PENDING`. Die Belege liegen in der Matrix, sind aber nicht in dieses Formblatt übertragen. Für Go verlangt Abschnitt 16 PASS in den Schritten 1, 3, 4, 9, 11, 12, 13. Ohne Owner-Beleg bleiben mindestens offen: 3 (OneDrive/`gitlocks`), 9.1 und 9.4 (Lesen, Office zurücklesen), 11.3 (Abbrechen), 12.3 (Gedächtnis nach Neustart).
3. **Einzelne Sprachtests mit echtem Inhalt:** S2b (5 Zeiten), S3, S4, S8a – bisher nur mit Mock-Antworten möglich.

## BEWUSST ZURÜCKGESTELLT (kein V1-Muss laut Abschnitt 16, nur mit ausdrücklicher Owner-Entscheidung und Eintrag in der Release-Notiz „N/A“)
- **Echtes LLM / `gpt-4o-mini` (Schritt 7):** Nicht Teil der #186-Kriterien und nicht in der Go-Liste; Dateiaufträge, Freigaben, Not-Aus, Resume laufen ohne LLM. Der minimale Einzeltest (`abnahme-v2\openai-einzeltest.py`) ist vorbereitet, aber nicht ausgeführt (kein Schlüssel konfiguriert). Ohne ihn gibt es keinen Beleg für inhaltliche Antworten.
- **Windows-UAC (S6):** Nicht in der Go-Liste und nur der Owner kann es auslösen; bleibt OFFEN, bis er es durchführt oder als N/A einträgt.
- Wake-Word ohne Klick, Barge-in per Stimme, DPI 125/150 % (nicht Pflicht), Aufräumen der sieben WAITING-Ziele.

## BLOCKIERT
- Nichts technisch. Nur Owner-Entscheidungen und Nachweise (siehe OFFEN).

## Merge-Bereitschaft
**PR #261 ist technisch mergefähig** (mergeable_state `clean`, `tests` und GUI E2E grün, Manifest vom Owner freigegeben), **aber die Abnahme #186 ist noch nicht abgeschlossen**, weil (a) `pr-tests` auf dem Release-Commit fehlt, (b) das Formblatt Abschnitt 16 nicht ausgefüllt ist und (c) N/A-Entscheidungen für LLM, UAC und die Restsprachtests fehlen. Mit diesen drei Punkten entscheidet allein der Owner; Claude merged nicht und schließt #186 nicht.
**Absolut notwendige letzte Schritte:** 1) `pr-tests` für den End-Commit (Run workflow), 2) Owner: PASS/N/A je Schritt 1, 3, 4, 9, 11, 12, 13 sowie 6/7/10 im Formblatt oder Release-Notiz festlegen (offene Einzelpunkte: 3.x, 9.1/9.4, 11.3, 12.3, optional S2b–S8a, S6), 3) Owner-Freigabe zum Merge.
