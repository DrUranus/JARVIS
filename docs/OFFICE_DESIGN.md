# Entwurf: Tabellen und Dokumente (`office-design`)

**Status: reiner Entwurf. Kein Code, nichts implementiert, nichts aktiviert, keine Abhaengigkeit aufgenommen** (`pyproject.toml` unveraendert). Dieses Dokument legt Kandidaten, Grenzen, Anforderungen und Abnahmetests fest, bevor ein Schritt `office-docs` ueberhaupt in Betracht kommt.

**Entscheidung des Besitzers erforderlich.** Dieser Entwurf trifft keine verbindliche Wahl und gibt nichts frei. `office-docs` bleibt **nicht freigegeben** (`docs/BACKLOG.md`) und braucht einen eigenen Backlog-Eintrag mit `approved: true`. Bis dahin gilt: kein Office-Code, keine Konfiguration `[office]`, kein Tool `office`.

## 1. Ausgangslage (belegt)

| Befund | Wo |
|---|---|
| Kein Tabellen-/Dokumentcode im Repository; `office-docs` ist "vorbereitet, nicht freigegeben, erst nach Entwurf und Entscheidung des Besitzers" | `docs/BACKLOG.md` |
| Keine Laufzeit-Abhaengigkeiten (`dependencies = []`); Zusatzfunktionen sind optionale Extras, lazy importiert | `pyproject.toml` |
| Dateizugriffe nur im Workspace: `security.allowed_roots` erweitert, `denied_paths` sperrt, leere Liste = alles verboten; `PathGuard` loest Symlinks auf | README "Dateisystem", "Workspace-Grenzen" |
| Workspaces nur in `coding.workspace_roots` **und** `security.allowed_roots` ("zwei Mauern") | README "Coding Agent" |
| Alle Tool-Aktionen laufen ueber `ToolRegistry.execute` -> `PermissionEngine`; Verdrahtung nur in `src/jarvis/bootstrap.py` | `CLAUDE.md` |
| GUI-Automation sperrt Standard-Shells; Office-Makros per Oberflaeche sind dort nicht pauschal gesperrt (Eingaben werden bestaetigt) | README "GUI-Automation" |

Abgrenzung: Dieser Entwurf betrifft **Dateien** (`.xlsx`, `.docx`) im Workspace, nicht das Bedienen einer laufenden Office-Anwendung per GUI (das regelt die bestehende GUI-Automation).

## 2. Kandidaten

Stand der Pruefung: 2026-11-07, Abfrage der PyPI-JSON-Schnittstelle (`https://pypi.org/pypi/<paket>/json`) und der Projektseiten. Versionen aendern sich; vor einer Aufnahme neu pruefen und mit Obergrenze festlegen.

| Kandidat | Zweck | Version (PyPI) | Lizenz | Abhaengigkeiten | Windows | Quelle |
|---|---|---|---|---|---|---|
| **openpyxl** | `.xlsx` lesen/schreiben (reines Python) | 3.1.5 (2024-06-28) | MIT | `et-xmlfile` | ja, ohne Office | https://pypi.org/project/openpyxl/ , https://openpyxl.readthedocs.io/ |
| **python-docx** | `.docx` lesen/erzeugen (reines Python) | 1.2.0 (2025-06-16) | MIT | `lxml>=3.1.0`, `typing_extensions>=4.9.0` | ja, ohne Office (lxml-Wheels fuer Windows) | https://pypi.org/project/python-docx/ , https://python-docx.readthedocs.io/ |
| **pywin32** (Office-COM) | laufende Office-Anwendung fernsteuern (`win32com`) | 312 (2026-06-04) | PSF-2.0 laut README-Abzeichen; PyPI: "Python Software Foundation License"; das Paket enthaelt "eine Mischung unterschiedlich lizenzierten Codes", massgeblich sind die Lizenzdateien im Quellbaum | keine | nur Windows, **braucht installiertes Microsoft Office** | https://pypi.org/project/pywin32/ , https://github.com/mhammond/pywin32 (README "Licenses") |

Hilfskandidaten (nur falls ein Kandidat sie verlangt):

| Paket | Zweck | Version | Lizenz | Quelle |
|---|---|---|---|---|
| defusedxml | Schutz vor XML-Angriffen beim Einlesen | 0.7.1 (2021-03-08) | PSF (PSFL) | https://pypi.org/project/defusedxml/ |
| XlsxWriter | nur Schreiben neuer `.xlsx` (kein Lesen) | 3.3.1 (2026-10-28) | BSD-2-Clause | https://pypi.org/project/XlsxWriter/ |

Hinweise zur Lizenzpruefung: Die Angaben stammen von PyPI-Metadaten, nicht aus einer Rechtspruefung. Fuer pywin32 ist der Lizenztext im Quellbaum massgeblich; vor Aufnahme ist er zu lesen. Alle drei Hauptkandidaten sind freie Lizenzen ohne Copyleft-Pflicht fuer JARVIS; **Microsoft Office selbst ist lizenzpflichtig** (Kosten und Lizenz liegen beim Benutzer, JARVIS liefert es nicht).

### 2.1 openpyxl

- Liest und schreibt `.xlsx`/`.xlsm` ohne Excel. Zellwerte, Formeln als Text, Formate, Blaetter.
- `data_only=True` liefert nur die beim letzten Speichern von Excel **zwischengespeicherten** Formelwerte; openpyxl rechnet nichts. Neu erzeugte Formeln haben bis zum Oeffnen in Excel keinen Wert.
- Offizielle Warnung (Dokumentation, Abschnitt zur Sicherheit): openpyxl schuetzt standardmaessig **nicht** gegen "quadratic blowup" und "billion laughs"; dafuer `defusedxml` installieren. -> Anforderung A7.
- Makros: `.xlsm` nur mit `keep_vba=True` zu erhalten; das ist **nicht** Ausfuehren, aber auch kein Pruefen. Der Entwurf verlangt `keep_vba=False` (Standard) und lehnt `.xlsm` ab (A2).
- Beim erneuten Speichern bestehender Dateien koennen nicht unterstuetzte Inhalte (z. B. Diagramme, Bilder) verloren gehen (aus der Erinnerung an die Projektdokumentation, in dieser Sitzung nicht abgerufen; vor Aufnahme pruefen). Konsequenz: bestehende Dateien nie in-place ueberschreiben (A5).

### 2.2 python-docx

- Liest und schreibt `.docx` (Absaetze, Tabellen, Stile, Bilder einfuegen). Kein `.doc`, keine Makrodokumente (`.docm` nicht vorgesehen), kein PDF.
- Abhaengigkeit `lxml` ist eine native Erweiterung (Wheels vorhanden, auf Windows pruefen). Auch hier gilt: untrusted XML -> Groessen-/Strukturlimits (A7).
- Rendern, Seitenzahlen, Inhaltsverzeichnis-Aktualisierung gibt es nicht (kein Layout-Motor).

### 2.3 pywin32 / Office-COM

- Steuert die **echte** Anwendung (Excel/Word) per COM: volle Funktion (Berechnung, Export nach PDF, Diagramme), aber:
  - **Makros und Add-ins:** Die Anwendung kann beim Oeffnen Code ausfuehren (VBA-AutoOpen, Add-ins, aktive Inhalte, externe Verknuepfungen). Ohne zusaetzliche Haertung (`AutomationSecurity` auf "alle Makros deaktivieren", keine Verknuepfungs-Updates, `DisplayAlerts` aus) ist "Makros nie ausfuehren" **nicht technisch erzwungen**. Auch mit Haertung bleibt eine grosse Angriffsflaeche (komplexer Parser in einer Desktop-Anwendung).
  - **Prozess:** startet eine sichtbare/unsichtbare Anwendungsinstanz; haengende Instanzen, Dialoge, Benutzersitzung, geteilte Instanz mit dem Benutzer. Notaus/Zeitlimit sind schwerer zu erzwingen als bei einer reinen Bibliothek.
  - **Kosten/Verfuegbarkeit:** nur Windows, nur mit installiertem, lizenziertem Office; nicht in CI testbar ohne Office (die GitHub-Windows-Runner enthalten nach unserem Kenntnisstand kein verlaesslich nutzbares Office; vor Planung pruefen).
  - Weitere Anbindungen (OLE, DDE) sind nicht Teil dieses Entwurfs und bleiben ausgeschlossen.

## 3. Bewertung und Empfehlung (nicht bindend)

| Kriterium | openpyxl | python-docx | Office-COM (pywin32) |
|---|---|---|---|
| Makros nie ausfuehrbar (technisch) | ja: Bibliothek kennt keine Makroausfuehrung | ja | **nein** ohne Haertung, auch mit Haertung nicht beweisbar |
| Braucht Office-Installation | nein | nein | ja |
| Test in CI (Linux und Windows) | ja, ohne Office | ja | nein (Office fehlt) |
| Ein Prozess / Zeitlimit / Notaus | im Prozess | im Prozess | Fremdprozess |
| Funktionsumfang | Daten, einfache Formate | Text, Tabellen | voll |
| Verdrahtung ueber Registry/Engine | ja | ja | ja, aber hoeheres Risiko |

Empfehlung zur Entscheidung (E1): **Stufe O1 mit openpyxl und python-docx**; **Office-COM wird in diesem Entwurf nicht zugelassen** und waere ein eigener Entwurf mit eigener Freigabe (O3, siehe 4). Gruende: "Makros nie ausfuehren" ist nur dort technisch durch die Bauart gegeben, und beide Bibliotheken sind ohne Office in CI testbar.

## 4. Stufen

| Stufe | Inhalt | Status |
|---|---|---|
| **O0** | Nichts (heutiger Zustand). | gilt |
| **O1 (Ziel von `office-docs`, nach Freigabe)** | **Lesen** von `.xlsx` und `.docx` im Workspace als Text/Tabelle (begrenzt); **Erzeugen neuer** Dateien im Workspace. Keine Aenderung bestehender Dateien. | nach Freigabe |
| **O2 (spaeter, eigener Entwurf)** | Bestehende Datei aendern, immer als **neue** Datei daneben (Kopie mit Aenderung), Vergleichsvorschau. | nicht Teil dieses Entwurfs |
| **O3 (spaeter, eigener Entwurf)** | Office-COM (Berechnung, PDF-Export). | nicht Teil dieses Entwurfs |

Keine Stufe schaltet die naechste frei; jede ist eigene Konfiguration, eigener Schritt, eigene Tests.

## 5. Anforderungen (verbindlich fuer einen spaeteren Schritt `office-docs`)

**A1 Standard aus.** `[office] enabled = false`; unbekannte Schluessel werden abgelehnt. Kein Hintergrund-Abruf, keine Ueberwachung von Ordnern, kein Selbststart, keine Ziele aus Dokumentinhalten (keine neue Autonomie).

**A2 Makros nie ausfuehren.** Es werden **nie** Makros, VBA, Skripte, aktive Inhalte, Add-ins, DDE/OLE-Objekte, externe Verknuepfungen oder Datenverbindungen ausgefuehrt, aktualisiert oder aufgeloest. Technisch erzwungen, nicht nur per Regel:
- Zugelassene Endungen ausschliesslich `.xlsx` und `.docx` (Allow-List). Makrohaltige Formate (`.xlsm`, `.xlsb`, `.xls`, `.docm`, `.dotm`, `.xltm`, `.doc`) werden abgelehnt, auch bei umbenannter Endung: vor dem Laden wird der Container geprueft (ZIP-Eintrag `vbaProject.bin`, ActiveX-Verzeichnisse, eingebettete Objekte -> Ablehnung mit Meldung, ohne die Datei zu laden).
- `keep_vba` nie `True`. Es wird **keine** Anwendung gestartet (kein COM, kein `os.startfile`, kein Shell-Aufruf) und kein Dokument "geoeffnet" im Sinn einer Anwendung.
- Formeln werden nur als **Text** behandelt; beim Schreiben werden Zellwerte, die mit `=`, `+`, `-`, `@` beginnen, als Text mit fuehrendem Apostroph/Textformat geschrieben ("Formel-Injektion"); Formeln schreibt nur eine ausdrueckliche Aktion mit sichtbarer Vorschau.
- Ein Test prueft strukturell, dass kein Modul `win32com`, `subprocess`, `os.startfile` im Office-Code importiert (analog zu den Strukturtests der bestehenden Tools).

**A3 Schreiben nur im bestaetigten Workspace.** Jeder Schreibzugriff geht nur in den bestaetigten Workspace (`security.allowed_roots`/`coding.workspace_roots`-Prinzip, "zwei Mauern"): PathGuard der Engine mit aufgeloestem echtem Pfad (Symlinks, Junctions, Gross-/Kleinschreibung unter Windows); relative Pfade nach den bestehenden Workspace-Regeln (`..`, absolute Pfade, `~`, `:`/NTFS-Streams, Geraetenamen werden abgelehnt); Zielverzeichnis muss bereits im Workspace existieren, es werden keine Verzeichnisse ausserhalb angelegt. **Lesen** gilt dieselbe Mauer (Lesen ausserhalb ist verboten). Pfade der Engine als `PATH`-Ressource, damit Grants an genau eine Datei gebunden sind. Schreiben ohne gesetzten, bestaetigten Workspace -> verweigert.

**A4 Berechtigungen.** Lesen: mindestens **YELLOW** (Dokumente enthalten personenbezogene Daten). Erzeugen/Schreiben: mindestens **YELLOW** mit Einzelbestaetigung inkl. Zielpfad, Dateityp, Groesse und Vorschau (Blatt-/Absatzzahl, erste Zeilen); Sitzungsfreigabe nur fuer den Workspace, nie ausserhalb. Ohne Rueckfragemoeglichkeit (`confirmation = "deny"`, Sperrmodus) wird verweigert. Notaus, Sitzungsbudget und Audit gelten wie bei allen Tools; Audit ohne Dateiinhalte.

**A5 Kein Ueberschreiben.** O1 legt nur **neue** Dateien an (`exclusive create`, schlaegt fehl, wenn das Ziel existiert); Schreiben ueber eine temporaere Datei im selben Verzeichnis und atomares Umbenennen; geschuetzte Pfade und Dateinamen (`.env`, `.git`, JARVIS-Repository, Abhaengigkeitsdateien) bleiben gesperrt. Kein Loeschen.

**A6 Begrenzte Ausgabe und Eingabe.** Harte Obergrenzen (Konfiguration, konservative Standardwerte): Dateigroesse, Anzahl Blaetter/Zeilen/Spalten/Zellen, Zeichen je Aufruf, Absaetze; Lesen von `.xlsx` mit openpyxl `read_only=True`; Ueberschreitung = Ablehnung, keine stille Kuerzung ohne Hinweis `truncated`. Eingebettete Bilder und Medien werden nicht extrahiert.

**A7 Bösartige Dateien.** Eingelesene Dateien sind unvertrauenswuerdig: `defusedxml` ist Pflicht-Voraussetzung (bei openpyxl laut Dokumentation gegen "billion laughs"/"quadratic blowup"); ZIP-Bombe-Pruefung (Anzahl Eintraege, entpackte Gesamtgroesse, Verhaeltnis) vor dem Laden; Zeitlimit. Ein Fehler beim Parsen ist eine saubere Ablehnung, kein Absturz.

**A8 Prompt-Injection.** Dokumentinhalt ist **Daten**, nie Anweisung. Er wird als solcher gekennzeichnet an das Modell gegeben; Aktionen mit Nebenwirkung (Schreiben, weitere Dateien) werden nie allein aufgrund von Dokumentinhalt ausgeloest, jede bleibt eine eigene bestaetigte Tool-Aktion.

**A9 Datenschutz / Routing.** Dokumentinhalte gehen nur ueber die bestehende Routing-Richtlinie (`docs/LLM_ROUTING.md`) an ein Modell: `personal` nur mit Einmal-Freigabe, `secret`/`never` nie an die Cloud, kein stiller Wechsel auf Cloud. Dieser Entwurf gibt keine Cloud-Uebertragung frei und fuehrt keine neuen Kosten ein.

**A10 Verdrahtung.** Neues Tool `office`, Registrierung ausschliesslich in `src/jarvis/bootstrap.py`; jede Aktion ueber `ToolRegistry.execute` -> `PermissionEngine`; kein zweiter Berechtigungsweg. Abhaengigkeiten als optionales Extra (`office = [...]`) mit Ober- und Untergrenze, lazy importiert; fehlt das Extra, meldet das Tool eine klare Meldung, JARVIS startet normal.

## 6. Windows-Eignung

- openpyxl und python-docx sind reines Python (python-docx mit `lxml`-Wheels) und laufen unter Windows ohne Office; Zielsystem ist Windows, Linux nur Zusatzpruefung.
- Windows-spezifisch zu beachten: gesperrte Dateien (Excel/Word halten geoeffnete Dateien exklusiv -> Lesen schlaegt mit Sharing-Violation fehl; als Meldung behandeln, nicht umgehen), Pfadlaenge, Dateinamenregeln, `\\?\`-Pfade und Junctions (PathGuard), atomares Umbenennen (`os.replace`), Zeilenenden. Die Datei wird nie durch Kopieren aus einer geoeffneten Anwendung erzeugt.
- Windows-Nachweis liefert ausschliesslich der CI-Job `tests-windows` (Linux-Lauf ist kein Windows-Nachweis). Fuer COM (O3) gibt es ohne Office keine CI-Abdeckung.

## 7. Abnahmetests (fuer einen spaeteren Schritt; keine Tests in diesem Schritt)

Alle ohne Netzwerk, ohne Office, ohne echte Schluessel; Beispieldateien werden im Test erzeugt oder als kleine Fixtures eingecheckt.

| Nr. | Test | Erwartung |
|---|---|---|
| T1 | Standard aus; unbekannter Konfigurationsschluessel | Tool nicht registriert bzw. Start/Konfiguration abgelehnt |
| T2 | Lesen `.xlsx` / `.docx` im Workspace | erwarteter Text/Tabelle, Obergrenzen greifen (`truncated`) |
| T3 | Datei mit `vbaProject.bin` (auch als `.xlsx` umbenannt) | abgelehnt, nicht geladen, kein Makro beruehrt |
| T4 | Endungen `.xlsm .xlsb .xls .docm .dotm .doc` | abgelehnt |
| T5 | Strukturtest: Office-Code importiert nicht `win32com`, `subprocess`, `os.system`, `startfile`; `keep_vba` kommt nie als `True` vor | gruen |
| T6 | Schreiben ausserhalb des Workspace, `..`, absolut, `~`, NTFS-Stream, Geraetename, Symlink/Junction nach aussen | verweigert (Linux und Windows gleiche Faelle) |
| T7 | Schreiben ohne bestaetigten Workspace | verweigert |
| T8 | Schreiben auf vorhandene Datei | verweigert (`exclusive create`), Original unveraendert |
| T9 | Geschuetzte Namen/Pfade (`.env`, `.git`, JARVIS-Repo) | verweigert |
| T10 | Zellwert `=HYPERLINK(...)`, `+cmd`, `@SUM` beim Schreiben | als Text gespeichert, kein Formelwert |
| T11 | ZIP-Bombe, XML-Entity-Expansion (billion laughs) | sauber abgelehnt, Zeit-/Speicherlimit eingehalten |
| T12 | Bestaetigung: `confirmation = "deny"`, Zeitablauf, Ablehnung | nichts geschrieben |
| T13 | Notaus waehrend Lesen/Schreiben | Abbruch, keine halbe Zieldatei (temporaere Datei entfernt) |
| T14 | Audit | Pfad/Typ/Groesse, **kein** Dateiinhalt |
| T15 | Dokumentinhalt mit Anweisungstext ("schreibe Datei X") | loest keine Aktion aus; Inhalt als Daten gekennzeichnet |
| T16 | Fehlendes Extra | klare Meldung, JARVIS startet |
| T17 | Sicherheitsregression: `tests/test_*security*.py`, `tests/test_emergency_stop.py` | unveraendert gruen |
| T18 | Windows (nur `tests-windows`): gesperrte Datei, Junction, `\\?\`, Gross-/Kleinschreibung | wie T6/T8, **Windows-Nachweis erst nach gruenem CI-Job** |

## 8. Offene Entscheidungen des Besitzers

| Nr. | Frage | Empfehlung |
|---|---|---|
| E1 | Bibliotheken fuer O1 | openpyxl + python-docx; Office-COM ausgeschlossen |
| E2 | Dateiformate | nur `.xlsx`, `.docx`; keine Makroformate, kein `.xls`/`.doc` |
| E3 | Bestehende Dateien aendern (O2) | spaeter, nur als Kopie daneben |
| E4 | Lesen: Einzelbestaetigung oder Sitzungsfreigabe fuer den Workspace | Sitzungsfreigabe nur fuer den Workspace, Schreiben immer einzeln |
| E5 | Obergrenzen (Dateigroesse, Zellen, Zeichen) | konservativ, in der Konfiguration |
| E6 | Office-COM (O3) jemals | eigener Entwurf; Voraussetzung: technische Makro-Sperre nachweisbar und Test ohne Office-Runner |
| E7 | Lizenzpruefung vor Aufnahme | Lizenztexte lesen (insbesondere pywin32 nur falls O3), Versionen mit Obergrenze festlegen |

## 9. Was dieser Schritt nicht tut

Kein Code, keine Tests, keine neuen Abhaengigkeiten, keine Konfiguration, keine Aenderung an `.github/`, `.claude/`, `CLAUDE.md`, `config/jarvis.toml` oder an Sicherheitslimits; keine Freigabe von `office-docs`.
