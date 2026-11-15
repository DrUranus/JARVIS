# Abnahme #186: Nachweis-Matrix, Integrationsplan (Stand 2026-11-15)

Legende der Nachweisarten: **USER** = vom Owner am echten PC bestätigt (Datum) · **LOKAL-AUTO** = automatisierter Test/Befehl in dieser Arbeitskopie (Windows 11, Python 3.14.8), **kein** Nachweis für Handschritte · **HEADLESS** = Browser/Node ohne Mensch · **CI** = GitHub-Lauf (Runner ohne Mensch am Desktop) · **OFFEN** = nicht nachgewiesen. Nichts davon wird als interaktive Abnahme ausgegeben, wenn nicht **USER** dasteht. Die Entscheidung Go/No-Go trifft ausschließlich der Owner.

## 1. Kriterien aus Issue #186 (B9) und `docs/B9_WINDOWS_ACCEPTANCE_STATUS.md`
| # | Kriterium | Stand | Belege / Hinweise |
|---|---|---|---|
| B9-1a | Orb ↔ Dashboard manuell | **OFFEN (interaktiv)**; HEADLESS grün | Chromium-E2E (24+3 Tests, lokal grün), Node-DOM grün. Im echten Fenster nicht bestätigt. |
| B9-1b | automatische Umschaltung nach echter Aufgabenkomplexität | **OFFEN** | nur Node-DOM (Schwellen 3 Schritte / 2 Agenten). Test: mehrstufigen Auftrag starten (z. B. „Liste den Ordner workspace“, danach ein Auftrag mit ≥3 Schritten) und Anzeige beobachten. |
| B9-2a | Overlay: Größe, Always-on-Top | **Claude-Computer-Use 2026-11-15 (kein Owner-Nachweis)**: vor Fix 200x101 (FAIL, Ursache pywebview-`min_size`-Standard 200x100), nach Fix `c7192c8` 140x140, Orb sichtbar, `WS_EX_TOPMOST`, Verschieben ok (100 % DPI; 125/150 % nicht gemessen) | CI (Runner, 12.11.): ~140x140, Topmost. Details: `ABNAHME_186_COMPUTERUSE_UND_HANDTESTS.md`. |
| B9-2b | Overlay: Fokus, Klick öffnet Hauptfenster | **Claude-Computer-Use 2026-11-15**: Klick auf „Öffnen“ -> Edge-Verbindung zum Server; Owner-Bestätigung **OFFEN** | Runner belegt nur den Rückruf. |
| B9-3 | Freigaben: Sichtbarkeit, Ablehnen = Standard | **USER 2026-11-14** (Dialog erscheint, Genehmigung legt Ordner an, Ablehnung legt nichts an) | „Ablehnen als vorbelegte Standardauswahl“ nicht ausdrücklich bestätigt. |
| B9-3b | Timeout = abgelehnt | **USER 2026-11-14** (120 s) | |
| B9-3c | Schließen / Verbindungsverlust = abgelehnt | **OFFEN (interaktiv)**; HEADLESS/Engine-Tests grün | `test_control_center_approvals`, `_confirmation`, Browser-E2E. |
| B9-4 | Not-Aus aus Orb, Dashboard, Overlay | Claude-Computer-Use 2026-11-15: Dashboard und Overlay lösten `emergency_stop` im Audit aus; Aufheben und Owner-Bestätigung **OFFEN**; Engine/E2E grün | `test_emergency_stop` grün; Overlay-Klick auf Runner CI belegt. |
| B9-5 | 3D oder dokumentierter 2D-Fallback, reduzierte Animationen | Animationen reduzieren **USER 2026-11-14**; 2D-Fallback: Doctor dokumentiert „Canvas-2D, kein WebGL/Three.js“ (LOKAL-AUTO) | 3D ist nicht enthalten (Three.js gesperrt); Fallback = 2D, im echten Fenster sichtbar durch S1. |

## 2. V1-Abnahme (`docs/WINDOWS_V1_ABNAHME.md`, 14 Bereiche)
| Bereich | Zeilen | Stand |
|---|---|---|
| 1 Installation/Start | 1.1 Rauchtest | LOKAL-AUTO PASS (`smoke.py` BESTANDEN) |
| | 1.2 `jarvis doctor` | LOKAL-AUTO PASS (Exit 0, 0 Fehler) |
| | 1.3 NEXUS „verbunden/bereit“ | **OFFEN** (im Gebrauch, aber nicht ausdrücklich bestätigt) |
| | 1.4 Beenden schließt den Port | LOKAL-AUTO (`smoke.py`: „Port wieder geschlossen“) |
| 2 Python 3.14 | 2.1/2.2 | LOKAL-AUTO (alle Läufe dieser Sitzung auf 3.14.8; CI-Windows nutzt 3.13) · 2.3 venv-Update OFFEN |
| 3 OneDrive/Git-Lock | 3.1 Doctor | LOKAL-AUTO PASS („kein OneDrive-Ordner“) · 3.3 `gitlocks` LOKAL-AUTO (liest nur, keine Sperren im Worktree-Git-Ordner) · 3.2 OFFEN. **Hinweis:** das Git-Verzeichnis dieses Worktrees liegt unter `C:\Users\Admin\OneDrive\Dokumente\GitHub\JARVIS\.git\worktrees\V2` (OneDrive). |
| 4 NEXUS Premium | 4.1 Umschalten | OFFEN · 4.2 Animationen reduzieren **USER 2026-11-14** · 4.3 Setup-Panel ohne Schlüssel LOKAL-AUTO (`test_control_center_setup`) |
| 5 Overlay | 5.1–5.4 | OFFEN (CI-Runner für Größe/Topmost/Notaus-Klick, siehe oben) |
| 6 Sprache | 6.1 Satz erkannt, Antwort gesprochen | **USER 2026-11-14** (Mikrofon, Erkennung, Antwort + Sprachausgabe; Pegel bewegt sich nach Korrektur) · 6.2 Unterbrechen OFFEN · 6.3 Mikrofon trennen **OFFEN** · 6.4 Notaus beendet Sprachmodus OFFEN (Tests grün) |
| 7 Echtes LLM | 7.1–7.3 | OFFEN (Provider `mock`, kein Schlüssel; `nexus.live.example.toml` vorbereitet) |
| 8 Brave-Recherche | 8.1–8.3 | OFFEN (kein `BRAVE_SEARCH_API_KEY`; Tests mit Fake/lokalem Server grün) |
| 9 Datei/Office | 9.1 Lesen | LOKAL-AUTO (E2E über Server) · 9.2 Ablehnen, 9.3 Zustimmen **USER 2026-11-14** · 9.4 Office OFFEN (Tool-Tests grün) |
| 10 Computersteuerung | 10.1–10.3 | OFFEN (= Schritte S5/S6/S8; Tests grün, keine Handbedienung) |
| 11 Agentenstatus | 11.1–11.3 | Zeitleiste/Farben **USER 2026-11-14** (11.1) · 11.2 Fehlertext LOKAL-AUTO (Klartext-Tests) · 11.3 Abbrechen OFFEN |
| 12 Journal/Resume | 12.1–12.3 | LOKAL-AUTO (68 Tests: Absturz-Simulation, harter Prozessabbruch) · echter Neustart/Abbruch = S9 **OFFEN** |
| 13 Freigaben/Not-Aus | 13.1 Ablehnen wirkt, 13.2 Timeout | **USER 2026-11-14** · 13.3 Verbindungsverlust OFFEN · 13.4 NOTAUS in allen Ansichten OFFEN |
| 14 Stabilität | 14.1–14.3 | OFFEN |

## 3. V2-Schritte S1–S9 (`scripts\abnahme\run-abnahme.ps1`, `docs/WINDOWS_V2_ABNAHME_SITZUNG.md`)
| Schritt | Automatischer Teil | Handschritt |
|---|---|---|
| S1 | PASS (Smoke, Doctor, Server 96 Tests) | OFFEN (Screenshot `01-nexus.png`, Beobachtung) |
| S2 | 35 PASS + 1 NOT_CHECKED (Test „kein Mikrofon“) | Erkennung/Antwort **USER**, Pegel **USER (nach Korrektur)**; **OFFEN:** 5 Latenzmessungen, Mikrofon abziehen |
| S3 | PASS (45 Tests) | OFFEN (Hedda, Umlaute, befehlsähnlicher Text) |
| S4 | MEASURED (Windows-TTS wav: Median warm 466 ms, kalt 737 ms) | hörbar OFFEN |
| S5 | nicht ausgeführt (Fenster) | OFFEN |
| S6 | `whoami /groups` lesend (nicht erhöht, UAC aktiv) | OFFEN (nur Owner) |
| S7 | PASS (74 + E2E 3) | **USER 2026-11-14 PASS** (Fehler gefunden und behoben: Commit `1c36204`) |
| S8 | Teilgruppen grün, native GUI nicht ausgeführt | OFFEN |
| S9 | PASS (68 Tests) | OFFEN |
**Nicht ausgeführt, weil sie die Maus des Owners steuern:** `tests\test_control_center_native_windows.py` (`JARVIS_NATIVE_GUI=1`, bewegt den Cursor und klickt). Gehört in die Sammelabnahme (Hände weg von der Maus, ca. 1 min).

## 4. Sammelabnahme (gefuehrt, möglichst ohne Tippen)
**Start: Doppelklick auf `scripts/abnahme/Sammelabnahme-starten.cmd`** (normale, nicht erhöhte Sitzung; Trockenlauf ohne Wirkung: `powershell -File scripts/abnahme/sammelabnahme.ps1`). Das Skript startet NEXUS selbst (auch mit Overlay), spielt die Hörproben ab, zeigt je Schritt „Tu das / Erwartet“ und nimmt **eine Taste** entgegen: **J** bestanden, **N** nicht bestanden (dann kurze Notiz), **S** überspringen. Ein Ergebnis entsteht **ausschließlich aus deiner Taste**; es installiert nichts, ändert keine Richtlinien und bedient nie UAC. Einzige Eingaben außer Tasten: bei S2 der Median der fünf Stoppuhrzeiten.
Belege: `abnahme-v2/sammelabnahme.md` und `.json` (ignoriert, nie committen; vor dem Anhängen an #186 auf Schlüssel prüfen). Reihenfolge und Erfolgskriterien:
| Teil | Schritte | Erfolgskriterium (Kurzfassung) |
|---|---|---|
| A NEXUS-Fenster | S1, B9-1a, B9-1b, B9-3c, B9-4a, B9-2, B9-2b, B9-4b, B9-3d | „verbunden/bereit“, Umschalten ohne Hänger (2D lesbar), Auto-Umschaltung (nur mit echtem mehrstufigem Auftrag, sonst ehrlich „übersprungen“), Schließen/Verbindungsverlust = kein Ordner angelegt, NOTAUS in Dashboard/Kugel/Overlay wirkt, Overlay ~140x140, im Vordergrund, Klick öffnet Hauptfenster |
| B Sprache | S2a, S2b, S2c, S3a, S3b, S4 | Pegel bewegt sich, Satz erkannt; Median der 5 Zeiten; Mikrofon ziehen = verständliche Meldung und Sprache läuft danach wieder; deutsche Stimme, Umlaute; befehlsähnlicher Text wird nur gesprochen (Prozesse gleich, keine Datei); 5 hörbare Latenzwerte (MEASURED) |
| C Fenster lesen | S5, S6 | Notepad/Rechner/Einstellungen lesen oder klar ablehnen, nichts getippt; UAC-Fenster: klare Ablehnung, kein Hänger, JARVIS nicht erhöht |
| D Not-Aus/Resume | S8a, S8b, S9 | Sprachausgabe ≤ 1 s weg, Auftrag stoppt, `/resume` listet nur und fragt neu, Audit ohne Schlüssel |
Nicht im Skript (bewegt deine Maus): `JARVIS_NATIVE_GUI=1` Test `test_control_center_native_windows.py`; optional danach.
Zuordnung Skript-ID -> Matrix: S1/S2/S3/S4/S5/S6/S8/S9 = V2-Schritte, B9-* = Kriterien aus Issue #186 (Abschnitt 1).

## 5. Release-Kandidat: Commits und Stand der Branches (2026-11-15, nach `git fetch`)
* **Neu und wichtig:** **PR #260 wurde am 2026-11-15 um 17:47 UTC vom Owner gemergt** (Squash-Commit `c1a9715` „… (#260)“ in `claude/v2-integration`). Der Baum von `c1a9715` ist identisch mit `d87f0fa`; `d87f0fa` selbst ist wegen des Squash **kein** Vorfahre von `claude/v2-integration`. Die lokalen Commits **`1c36204` (S7-Fix), Commit A (Pegel) und Commit B (STT-Upgrade) sind in keinem Remote-Branch**.
* **Lokaler Stand:** Branch `claude/v2-186-windows-abnahme`: `d87f0fa` -> `1c36204` (S7) -> `10d4cea` (A: Pegel) -> B (STT-Upgrade, Matrix, V2-Plan, Sammelabnahme; SHA siehe Bericht/`git log`). Keine Änderung an `main`, `.github/`, PermissionEngine, Freigaben, Not-Aus.
* **Integrationsvorschlag (nicht ausgeführt):** einen **neuen** Branch von `origin/claude/v2-integration` (`c1a9715`) anlegen und die drei Commits `1c36204`, A, B per `cherry-pick` übernehmen (keine History-Umschreibung; Konflikte nicht zu erwarten, weil der Baum von `c1a9715` gleich `d87f0fa` ist), dann Push des neuen Branches und ein neuer Draft-PR gegen `claude/v2-integration`. Alternativ den alten Branch nicht mehr pushen: sein `origin`-Stand `d87f0fa` entspricht dem gemergten PR #260.
* **CI nach dem neuen Push (manuell, Links in `RELEASE_KANDIDAT_186.md` §4):** `tests` startet automatisch (Push auf `claude/**`), `pr-tests` (tests-linux + tests-windows) und `uia-compat` per „Run workflow“. Voraussetzungen geprüft: `tests-windows` installiert `.[dev,voice]` (numpy, sounddevice vorhanden), `tests-linux` nur `.[dev]` (die neuen Tests laufen auch ohne numpy/sounddevice/faster-whisper, lokal verifiziert); `uia-compat` ist von diesen Änderungen unabhängig (`ci/uia-compat/**` unverändert; Basis-SHA hat keinen Lauf).
