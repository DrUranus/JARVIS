# Abnahme #186: Computer-Use-Bericht und Handtest-Anleitung (Stand 2026-11-15, Commit c7192c8)
Kein Owner-Nachweis: keine J/N/S-Taste wurde stellvertretend gedrückt, die Sammelabnahme wurde nicht im Echtmodus gestartet. Go/No-Go trifft der Owner.

## 1. Tatsächlich beobachtet (Claude, Computer Use / eingebauter Browser)
| Schritt | Ergebnis |
|---|---|
| S1 / B9-1a | „verbunden“, „bereit“, Orb; Umschalten Orb/Dashboard rendert (eingebauter Browser, nicht Owner-Fenster) |
| B9-4a | NOTAUS im Dashboard: rotes Banner, Audit `emergency_stop`; Chat-Auftrag danach legte keinen Ordner an. Aufheben nicht getestet |
| B9-2 vor Fix | **FAIL:** 200x101 statt 140x140, Orb abgeschnitten |
| B9-2 nach Fix | **PASS (Beobachtung):** 140x140 (Fenster = Client), Orb, „Öffnen“, NOTAUS sichtbar; Always-on-Top; Verschieben um 53 px ok. Nur 100 % DPI gemessen |
| B9-2b | Klick „Öffnen“ -> Edge-Verbindung zum Server |
| B9-4b | NOTAUS im Overlay: Audit `emergency_stop` 18:51:31 |

**Ursache/Fix:** pywebview-Standard `min_size=(200, 100)` klemmte das Fenster; `overlay_options()` setzt `min_size` jetzt gleich der Fenstergröße (Skalierung mit demselben DPI-Faktor). Regressionstest `test_options_min_size_equals_window_size`; nativer Test prüft zusätzlich „quadratisch“.

| B9-3c | **PASS (Beobachtung):** Freigabedialog (Ablehnen vorbelegt) offen, Seite ohne Antwort neu geladen -> `confirmation_rejected`, `permission_denied`, `Abnahme3` nicht angelegt (Neuladen statt Tab-Schließen) |
| B9-3d | **PASS (Beobachtung):** Frage `Abnahme4` offen, eigener jarvis-cc-Prozess beendet -> `Abnahme4` nicht angelegt (Strg+C-Fenster nicht benutzt) |

**Nicht ausführbar durch Claude:** Aufheben des Not-Aus (nur über Owner-Rückfrage), B9-1b (Konfiguration ohne Browser erzeugt keinen mehrstufigen Auftrag), S2-S4/S8a (Mikrofon/Gehör), S6 (UAC), S5/S9 offen. CI: `pr-tests` und `uia-compat` brauchen manuelles „Run workflow“ (kein Token); für 3b5d596 lief nur `Control Center GUI E2E`.

## 2. Nur automatisiert
Overlay-, Not-Aus-, Freigaben-, Abnahme-Skript- und alle `*security*`-Tests lokal ohne Fehler (nur Skips: POSIX-Symlinks/Rechte). Der native GUI-Test (`JARVIS_NATIVE_GUI=1`, bewegt die Maus) lief **nicht**.

## 3. CI für c7192c8
`tests`: success. `Control Center GUI E2E`: success. `pr-tests` (Linux+Windows) und `uia-compat`: **nicht gelaufen** (manuell per „Run workflow“ nötig). Windows-Nachweis ausstehend, bis `pr-tests` grün ist. Vorgänger 82ae913 hatte `pr-tests` grün.

## 4. Noch nicht geprüft: Handtests (nur Owner)
Start: Doppelklick `scripts\abnahme\Sammelabnahme-starten.cmd` (nicht erhöht). Je Schritt eine Taste J/N/S. Bereits bestanden (USER 14.11.): B9-3, B9-3b, S7, S2-Erkennung. Nicht wiederholen.
1. **Teil A (B9):** B9-1a im echten Fenster; B9-1b (nur mit mehrstufigem Auftrag, sonst S); B9-3c Tab schließen = Ordner `Abnahme3` fehlt; B9-4a/4b NOTAUS und danach Aufheben; B9-2/2b kurz bestätigen (140x140, Klick öffnet); B9-3d Strg+C während Frage = `Abnahme4` fehlt.
2. **Teil B (Sprache, Headset):** S2a Pegel+Satz; S2b Median von 5 Stoppuhrzeiten; S2c Mikrofon abziehen/einstecken; S3a deutsche Stimme; S3b befehlsähnlicher Text nur gesprochen; S4 fünf hörbare Latenzwerte (MEASURED).
3. **Teil C:** S5 Notepad/Rechner/Einstellungen lesen (Freigaben mit Nein; `[computer]` ist in der Testkonfiguration aus, ein Nein/Ablehnung ist erwartbar); S6 Notepad als Administrator selbst starten, UAC selbst entscheiden, JARVIS bleibt nicht erhöht.
4. **Teil D:** S8a NOTAUS während Sprachausgabe (≤1 s); S8b NOTAUS im Auftrag; S9 hartes Schließen, `/resume`, dann `/resume <Nr>`, Audit ohne Schlüssel.
5. Optional: `JARVIS_NATIVE_GUI=1 python -m pytest tests\test_control_center_native_windows.py` (Hände weg von der Maus, ca. 1 min).
Ergebnis: `abnahme-v2\sammelabnahme.md` (ignoriert, vor Weitergabe auf Schlüssel prüfen).

## 5. CI-Stand (2026-11-15 ~20:50 UTC, Owner startete die Workflows manuell)
Lauf auf 3b5d596 (nur Doku-Änderung gegenüber c7192c8): `uia-compat` success; `pr-tests`: `tests-linux` success, `tests-windows` zuletzt `in_progress` (Abfrage danach durch GitHub-Rate-Limit blockiert, Endergebnis **nicht bestätigt**). `Control Center GUI E2E` auf c718353 success. S3b automatisiert: Prozesse 3/3, `datei.txt` nicht vorhanden (Befehlstext nur gesprochen; Höreindruck offen).

## 6. S5, S9, B9-1b (2026-11-15, nach CI-Meldung des Owners)
* **S9: PASS (Beobachtung, kein Owner-Nachweis):** siehe Matrix. Die offene Frage wurde nicht beantwortet.
* **S5: nicht prüfbar:** `[computer]` ist in `nexus.voice-test.toml` aus; Einschalten wäre eine Berechtigungsänderung (nicht erlaubt). Owner: Konfiguration bewusst aktivieren und Schritt ausführen.
* **B9-1b: nicht prüfbar:** die Zielvorlagen (Web/Coding/Bildschirm) brauchen Browser-, Coding- oder Computer-Werkzeug, die in dieser Konfiguration aus sind; kein mehrstufiger Auftrag erzeugbar. Nur Node-DOM-Test belegt (Schwellen 3 Schritte/2 Agenten).
