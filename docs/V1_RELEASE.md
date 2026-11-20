# JARVIS V1 – Release-Vorbereitung (Stand 2026-11-20)

**Status: Entwurf, kein Release.** Kein Merge, kein Tag, kein GO. Die Entscheidung liegt beim Owner.
Kandidat: Branch `claude/v1-release` = `claude/v2-186-finalisierung` (Abnahme-Commit `4d33fc9`) plus Merge von `origin/main` (`d0c1dc4`). Den genauen Commit nennt der PR.

## 1. Release Notes (V1 / V2-Grenze)
**Teil von V1 (Windows-first, lokal):**
- NEXUS Control Center (Kugel, Dashboard, Overlay, Freigabe-Dialog, Not-Aus, Reset mit Rückfrage), lokal auf `127.0.0.1` mit Token.
- Text- und Sprachsteuerung (lokale Spracherkennung, Windows-Sprachausgabe, "Antwort stoppen").
- Datei-, Office- und Computeraufträge nur über `ToolRegistry` und `PermissionEngine`. Alles mit Wirkung fragt nach, Ablehnen ist Standard.
- Aufgabenstatus, Journal, `/resume` (nur auf ausdrücklichen Befehl, mit neuer Freigabe), Gedächtnis.
- Optional und standardmäßig aus: NEXUS Ultimate (reine Leseansicht aus `main`).

**Nicht Teil von V1 (auf V2 verschoben, Owner-Entscheidung 20.11.2026):**
- Echtes LLM (Abnahmebereich 7). V1 antwortet mit dem Standard-Anbieter `mock`.
- Live-Brave-Recherche und Webrecherche mit Schlüssel (Bereich 8).
- Die Integrationen bleiben im Code, sind aber deaktiviert (`enabled = false`). Es gibt keine Schlüssel in Dateien und keine Live-Aufrufe.
- V2-Pakete im Code (Agenten-Artefakte, Agenten- und LLM-Budgets, Business-Finder, Plan-Evaluation): standardmäßig aus, nicht als V1 freigegeben und nicht abgenommen.

**Hinweis für Nutzer:** In V1 kommen die Antworten nicht von einem echten Sprachmodell. Freie Fragen werden nur eingeschränkt beantwortet, und es gibt keine Internetrecherche.

## 2. Known Limitations
- Kein echtes LLM, keine Live-Recherche (siehe oben). Der natürlichsprachige Abruf des Gedächtnisses ist im Mock-Modus nicht belegt (nur der Persistenznachweis, Eintrag `36bd8ba5510e`).
- Kein Weckwort ohne Klick, keine Unterbrechung der Sprachausgabe per Stimme (nur Knopf "Antwort stoppen" und Not-Aus).
- Abbruch (11.3) wirkt kooperativ an der Freigabe-Grenze. Ein langer Rechenschritt ohne Freigabe ist so nicht abgedeckt.
- Not-Aus ist rein im Speicher: ein Neustart löscht ihn. Das Aufheben verlangt eine Rückfrage.
- Sieben liegengebliebene Journal-Ziele im Status WAITING (F-S9-2) sind nicht aufgeräumt.
- Abnahmezeilen PENDING: 2.3, 5.4, 11.2 (Handbeleg), 14.1, 14.3. Details in `docs/WINDOWS_V1_ABNAHME.md`.
- Tk-Startfehler auf dem CI-Runner sind ein bekannter, ungeklärter Umgebungseffekt.
- Windows-Nachweise liefern nur Owner-Läufe und der CI-Windows-Lauf. Linux ist kein Windows-Nachweis.

## 3. Installation und Start (Windows)
Ausführlich: `docs/WINDOWS_QUICKSTART.md`, `docs/WINDOWS_V1_KONFIGURATION.md`.
```powershell
cd C:\dev\JARVIS
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,voice,ui]"
.\.venv\Scripts\jarvis.exe doctor
.\.venv\Scripts\jarvis-cc.exe -c config\nexus.example.toml --open
```
- JARVIS außerhalb von OneDrive ablegen. Python 3.11 oder neuer (3.13 und 3.14 getestet).
- Keine API-Schlüssel setzen. Das Beenden geht mit Strg+C.

## 4. Rollback
Nur lokal, nichts löschen und kein Force-Push:
1. NEXUS beenden (Strg+C) und prüfen, dass kein `jarvis`-Prozess läuft.
2. Datenordner sichern, solange nichts anderes läuft: `Copy-Item data, logs -Destination ..\jarvis-backup -Recurse` (nicht überschreiben).
3. Zum vorherigen Stand wechseln: `git switch --detach <letzter-guter-Commit>`, zum Beispiel der Abnahme-Commit `4d33fc9` oder der letzte `main`-Stand `d0c1dc4`. Danach `pip install -e ".[dev,voice,ui]"` und `jarvis doctor`.
4. Das Journal und Gedächtnis bleiben in `data\` bestehen. Wiederaufnahme nur mit `/resume <id>` und neuer Freigabe.
5. Ein Merge auf `main` wird nicht automatisch zurückgesetzt. Ein Revert-Commit per PR ist der vorgesehene Weg (Owner).

## 5. GO/NO-GO-Checkliste (nur der Owner entscheidet)
| # | Kriterium | Stand |
|---|---|---|
| 1 | Release-Commit festgelegt, Git sauber | offen (PR-SHA) |
| 2 | Pflicht-CI auf dem Release-Commit grün (`tests`, `pr-tests` Windows und Linux, `uia-compat`, GUI E2E) | siehe PR |
| 3 | Schutzmanifest: `fake.py` vom Owner geprüft, Manifest neu erzeugt | **offen (Owner)**, `test_protected_files` ist bis dahin rot |
| 4 | Schritte 1, 3, 4, 9, 11, 12, 13 PASS im Formblatt | PASS, außer 11.2 (PENDING, Handbeleg) |
| 5 | Schritte 2, 5, 6, 7, 8, 10, 14: PASS oder N/A per Owner-Entscheidung in dieser Notiz | 7 und 8 N/A entschieden. 2.3, 5.4, 14.1, 14.3 offen. |
| 6 | Kein Sicherheitsverhalten weicht ab (Freigaben, Ablehnen, Timeout, Not-Aus) | kein Abweichen bekannt |
| 7 | Nachtest auf dem Merge-Build (Reset-Rückfrage, Abbruch, Dashboard) | offen, siehe unten |
| 8 | Release-Notiz mit V1-/V2-Grenze und Known Limitations | dieses Dokument |

**Nachtest auf dem Owner-PC (nur die vom Merge betroffenen Bereiche):** (a) NEXUS starten, "verbunden"; (b) NOTAUS und "Not-Aus aufheben" mit Rückfrage (Reset-Rückfrage kommt aus `main`); (c) Abbruch eines Auftrags mit offener Freigabe (11.3); (d) Dashboard nach Abschluss ohne altes RUNNING, auch nach F5. Alles andere gilt aus der Sammelabnahme auf `4d33fc9`.
