# pywinauto (Windows-UI-Automation)

Pruefbericht nach `docs/INTEGRATIONS.md`, Schritt `uia-vetting` (zweiter Anlauf nach dem Stopp von Issue #59). Geprueft wurde nur an den genannten offiziellen Quellen (PyPI, Projekt-Repository, Snyk-Datenbank, Microsoft Learn). Es wurde nichts installiert, kein Paketcode gelesen oder ausgefuehrt und kein Produktionscode geaendert. Angaben, die die Quellen nicht hergeben, stehen als "unbekannt" oder "offen" da.

## Name und Zweck
`pywinauto`, Projektseite https://github.com/pywinauto/pywinauto, Paket https://pypi.org/project/pywinauto/. Python-Bibliothek zur Steuerung von Windows-Anwendungen; ihr UIA-Backend liest den UI-Automation-Baum (Fenster, Steuerelemente) und bedient Steuerelemente ueber UIA-Muster. JARVIS braucht sie als optionales Extra `uia` fuer die Schritte `uia-provider-readonly`, `uia-tools-readonly` und `uia-actions`, damit die Bedienung des Windows-PCs ueber Steuerelemente statt ueber Bildschirmkoordinaten laeuft. Alle Zugriffe blieben ueber `ToolRegistry.execute` und die `PermissionEngine`; die Bibliothek liefert nur Primitive.

## Lizenz (Wortlaut)
BSD-3-Clause
> "Starting from 0.6.0 pywinauto is distributed under the BSD 3-clause license." (Fundstelle: README im Repository https://github.com/pywinauto/pywinauto, abgerufen 2026-10-31)
> "Redistributions of source code must retain the above copyright notice" (Fundstelle: Lizenzdatei des Repositories, Inhalt am 2026-10-31 nur zusammengefasst abgerufen; Urheber laut Datei: "Mark Mc Mahon and Contributors")

Uebereinstimmend: PyPI-Metadaten beider Versionen (`license`: "BSD 3-clause", Klassifikator-Seite: "BSD License (BSD 3-clause)") und Snyk ("BSD-3-Clause" fuer Versionen ab 0.6.0; fuer 0.1.3 bis vor 0.6.0 "LGPL-3.0"). Der Lizenztext der Datei wurde in dieser Pruefung nicht vollstaendig woertlich abgerufen (das Abrufwerkzeug fasste ihn zusammen; der Pfad `LICENSE.txt` lieferte 404, `LICENSE` lieferte die Zusammenfassung). **Offen:** vollstaendigen Wortlaut aus dem gepinnten sdist (`pywinauto-0.6.9.tar.gz`) beim Einbau gegenpruefen. Alle gepruefen Versionen (0.6.9, 1.0.0b1) liegen ueber 0.6.0.

## Version und Datum
Gepruefte Kandidaten:
- **0.6.9**, veroeffentlicht am 2025-01-06 (PyPI-Upload 2025-01-06T11:29:55Z), auf PyPI und GitHub als neueste stabile Version gefuehrt.
- **1.0.0b1**, veroeffentlicht am 2026-10-15 (PyPI-Upload 2026-10-15T16:32:42Z), als Vorabversion (Pre-release) gefuehrt, nicht zurueckgezogen (`yanked: false`).

Empfohlen wird 0.6.9 (siehe Entscheidung).

## Versionsvergleich 0.6.9 gegen 1.0.0b1
| Merkmal | 0.6.9 (stabil) | 1.0.0b1 (Beta) | Quelle |
|---|---|---|---|
| Datum | 2025-01-06 | 2026-10-15 | PyPI |
| Status | stabil, "Latest" | Pre-release | PyPI, GitHub Releases |
| Deklarierte Python-Versionen (Klassifikatoren) | 2.7, 3.5, 3.6, 3.7 | 3.7 bis 3.14 | PyPI-JSON |
| `requires_python` | nicht gesetzt (`null`) | nicht gesetzt (`null`) | PyPI-JSON |
| Direkte Abhaengigkeiten (Windows, Python > 3.6) | `six`, `comtypes`, `pywin32` | `comtypes`, `pywin32`, `injectlib` (kein `six`) | PyPI-JSON |
| Weitere Plattformen | Linux (`python-xlib`) | Linux, macOS (neue Beta-Backends) | PyPI-JSON, Releases |
| Standard-Backend unter Windows | `win32` | `uia` | Release-Notizen 1.0.0b1 |
| Neue Backends | – | `atspi`, `ax`, `wpf` (laut Notiz "uses DLL injection"), `qt5`/`qt6` (Beta) | Release-Notizen 1.0.0b1 |
| Python 2.7 | letzte Version mit Unterstuetzung, Abhaengigkeiten festgelegt | entfaellt | Release-Notizen |
| Artefakt | Wheel `py2.py3-none-any`, 363041 Byte; sdist | Wheel `py2.py3-none-any`, 474234 Byte; sdist | PyPI-JSON |
| Snyk-Abdeckung | gescannt, keine bekannten Schwachstellen | nicht gescannt (Snyk nennt als neueste Version 0.6.9) | Snyk |

## Pflege
- Repository https://github.com/pywinauto/pywinauto ist nicht archiviert. Die Commit-Liste zeigt Aktivitaet bis 2026-10-28 (Dokumentationsaenderung), davor am 2026-10-23, 2026-10-21 und 2026-10-15 (Aenderungsprotokoll 1.0.0b1) von mehreren Personen (u. a. `vasily-v-ryabov`, `junkmd`, `Blues-berry`). PyPI nennt drei Betreuer (`aireilil`, `markm`, `vasily-v-ryabov`).
- Offene Meldungen: 498 offene Issues und 24 offene Pull Requests (Repository-Seite, 2026-10-31).
- Veroeffentlichungen: 0.6.8 (Oktober, Jahr auf der Seite nicht angegeben), 0.6.9 am 2025-01-06, 1.0.0b1 am 2026-10-15; zwischen 0.6.9 und 1.0.0b1 liegen rund neun Monate ohne Veroeffentlichung. Snyk (Seite undatiert) bewertet die Wartung als "SUSTAINABLE", Paketgesundheit "71/100" und merkte an, dass 12 Monate keine neue Version erschien; diese Angabe stammt vermutlich aus der Zeit vor der Beta (die Snyk-Seite ist undatiert; das ist eine Annahme).
- Sicherheitsmeldungen: Das Repository hat laut GitHub-Sicherheitsseite keine Sicherheitsrichtlinie (kein `SECURITY.md`) und keine veroeffentlichten Advisories. Wie Schwachstellen gemeldet und behandelt werden, ist daher **unbekannt**.
- PyPI-Seite der 0.6.9: keine Herkunftsbescheinigungen (Provenance), Veroeffentlichung nicht ueber Trusted Publishing.
- Die CI-Plaketten im README verweisen auf AppVeyor und Travis; ob deren Stand aktuell ist, ist aus den Quellen nicht ersichtlich.

## Python- und Windows-Kompatibilitaet
- Projekt: Python >= 3.11 (`pyproject.toml`), die CI testet unter Python 3.13 (`pr-tests.yml`, `tests.yml`). **Python 3.14 wird von der CI nicht getestet.** Ob eine Python-3.14-Umgebung auf dem PC des Besitzers vorliegt, laesst sich aus dem Repository nicht pruefen; das bleibt offen.
- **0.6.9:** deklariert nur Python bis 3.7 und setzt `requires_python` nicht. Das Wheel ist reines Python (`py2.py3-none-any`) und deshalb fuer jede Windows-Python-Version installierbar. **Ob 0.6.9 unter Python 3.13 oder 3.14 funktioniert, ist nicht belegt.**
- **1.0.0b1:** deklariert Python 3.7 bis 3.14 (Klassifikatoren), ebenfalls ohne `requires_python`. Das ist eine Angabe des Projekts, kein Testnachweis fuer JARVIS. Die Version ist erst seit 16 Tagen veroeffentlicht und eine Beta.
- Gemeinsame Windows-Bausteine: `pywin32` 312 deklariert Python 3.9 bis 3.15 und bietet Windows-Wheels fuer CPython 3.11 bis 3.14 (cp311, cp312, cp313, cp314, `win_amd64`); `comtypes` 1.4.17 verlangt Python >= 3.9 und ist ein reines Python-Wheel (`py3-none-any`). **Ob pywinauto 0.6.9 mit `comtypes` 1.4.17 zusammenarbeitet, ist nicht belegt** (die Version 0.6.9 entstand vor diesem `comtypes`).
- Microsoft UI Automation: Die Microsoft-Seite "UI Automation - Win32 apps" (Stand 2025-07-14) nennt als unterstuetzte Systeme Windows XP bis Windows 10 und Windows Server 2003 bis 2019. **Windows 11 wird auf dieser Seite nicht ausdruecklich genannt**; ob das UIA auf dem Zielsystem des Besitzers gleichwertig funktioniert, ist nicht belegt. Die Seite richtet sich an "experienced C/C++ developers" und setzt COM-Kenntnisse voraus.
- Linux: pywinauto 0.6.9 braucht dort `python-xlib`; fuer JARVIS ist das Extra nur fuer Windows vorgesehen. Ein Linux-Lauf ist kein Windows-Nachweis.
- Verhalten laut Release-Notizen, das fuer JARVIS zaehlt: COM im Multithread-Modus standardmaessig seit 0.6.4, Administratorpruefung seit 0.6.5, `kill()` standardmaessig hart und `connect()` mit `visible_only=False` seit 0.6.6. Die Funktion "Prozess beenden" wird in JARVIS nicht freigegeben.

## Transitive Abhaengigkeiten
Fuer 0.6.9 unter Windows (Python > 3.6), je nach PyPI-Metadaten am 2026-10-31; zu den vier Paketen listen die geprueften Metadaten keine weiteren Abhaengigkeiten (`requires_dist` fuer `comtypes` und `pywin32`: keine Angabe):

| Paket | Version | Lizenz (PyPI) | Veroeffentlicht | Hinweis |
|---|---|---|---|---|
| `pywinauto` | 0.6.9 | BSD-3-Clause | 2025-01-06 | direkt |
| `six` | 1.17.0 | MIT | 2024-12-04 | direkt, reines Python |
| `comtypes` | 1.4.17 | MIT (`license_expression`) | 2026-09-21 | direkt, Python >= 3.9 |
| `pywin32` | 312 | PSF (Feld `license`: "PSF") | 2026-06-04 | direkt, native Windows-Binaerteile |

Fuer 1.0.0b1 statt `six` zusaetzlich `injectlib` 0.0.3 (BSD-3-Clause, veroeffentlicht 2026-10-10, erste Version 0.0.2 am 2026-04-25, Python >= 3.7, verlangt `pywin32` unter Windows; Autoren laut PyPI aus dem Kreis der pywinauto-Betreuer). Die zweite Ebene (Abhaengigkeiten dieser Pakete) wurde ueber die PyPI-Metadaten nur mit "keine Angabe" gefunden; **offen:** vollstaendiges Aufloesen mit `pip install --dry-run` im Einbauschritt, vor dem Merge.

## Sicherheitshinweise
- Snyk (Seite undatiert): "No direct vulnerabilities have been found for this package in Snyk's vulnerability database." Neueste gescannte Version: 0.6.9, "No vulnerabilities found in the latest version." Fuer 1.0.0b1 gibt es keine Snyk-Aussage. Das beweist keine Sicherheit, es nennt nur, was die Datenbank kennt.
- GitHub: keine veroeffentlichten Sicherheitshinweise, keine Sicherheitsrichtlinie (siehe Pflege).
- Native Teile: `pywinauto` selbst ist reines Python (Wheel `py2.py3-none-any`). `pywin32` bringt native Windows-Binaerteile; `comtypes` greift per COM auf `UIAutomationCore` zu. Code bei Installation oder Import: nicht untersucht (Paketcode wurde nicht gelesen, nichts installiert); **offen**.
- Beta 1.0.0b1: enthaelt laut Release-Notizen ein Backend `wpf`, das "DLL injection" nutzt, und die neue, junge Abhaengigkeit `injectlib`. Das erhoeht die Angriffsflaeche gegenueber 0.6.9 und ist ein Grund, die Beta nicht einzubauen.
- Rechte und UIA: UIA liest Inhalte fremder Fenster. Auf Passwortfelder weist Microsoft in der Eigenschaftsliste hin: `UIA_IsPasswordPropertyId` "indicates whether the automation element contains protected content or a password"; "Attempting to access the **Value** property of the protected element (edit control) may cause an error to occur." Die Anforderung fuer JARVIS bleibt daher: Passwortfelder nie lesen, nie beschreiben, `IsPassword` immer pruefen, gesperrte Fenster ablehnen. Zur Stabilitaet nennt Microsoft: "AutomationId is not guaranteed to be stable across different releases or builds of an application." Aktionen muessen daher nach der Ausfuehrung den tatsaechlichen Zustand lesen.
- Bei erhoehten Rechten (Administrator, UAC) und Anwendungen mit hoeherer Integritaetsstufe: nicht belegt, wie sich UIA verhaelt; **offen**.
- Keine Herkunftsbescheinigung und kein Trusted Publishing bei 0.6.9; Gegenmassnahme ist das Hash-Pinning unten.

## Datenabfluss
In den geprueften Quellen (PyPI-Metadaten, README-Auszug, Release-Notizen, Snyk) wird weder Telemetrie noch Netzwerkzugriff der Bibliothek erwaehnt. Das ist keine Pruefung des Quellcodes: **unbekannt, nicht belegt**, ob die Pakete beim Installieren oder Laufen Netzverbindungen aufbauen. Speicherorte: nicht angegeben. Vor dem Einbau gilt: Strukturtest, dass das Extra im Betrieb keine Netzwerkzugriffe ausloest, und `pip install --require-hashes` ohne weitere Downloads.

## Pinning mit Hash
Empfohlene Pins (SHA-256 aus den PyPI-Metadaten vom 2026-10-31, nicht neu berechnet):

```
pywinauto==0.6.9 --hash=sha256:5924b3072864a1d730c5546bbeb17cf4063ba518b618dbc5e43c18276c7c9356
six==1.17.0 --hash=sha256:4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274
comtypes==1.4.17 --hash=sha256:4e0a221dde2c589b82977bed802efd71cd5eb67a380347b732e02735e597f586
pywin32==312 --hash=sha256:c53e878d15a1c44788082bfe712a905433473aa38f86375b7cf8b45e3acbaaf9   # cp313, win_amd64
pywin32==312 --hash=sha256:a4dd3a848290ef724347b19f301045831d8e802fa4464f491b98b1e0a081432e   # cp314, win_amd64
```

Weitere Artefakt-Hashes zur Gegenpruefung: `pywinauto-0.6.9.tar.gz` `94d710bfa796df245250f952ffa65d97233d9807bcd42e052b71b81af469b6de`. Fuer die Beta (nur zur Dokumentation, nicht empfohlen): Wheel `pywinauto-1.0.0b1-py2.py3-none-any.whl` `dab6686c02dec1ef664229efe89cd6d23c04b9795bacd5dacbaaf9383a177608`, sdist `dfe52e89bdcebb05f1af05f5d899b1432ef64ef1289d046e3d749a88bfe6a953`; `injectlib` 0.0.3 Wheel `7eebfdb6a161203dc71b183d6f0c721b7b4d01bd0f272ec2f895dbb127cabb11`.
**Offen:** Hashes fuer `pywin32` unter CPython 3.11 und 3.12 (Wheels existieren) sind nicht erhoben; der Einbauschritt muss alle von der CI genutzten Zielversionen hashen. Die Hashes der Pins sind vor dem Einbau erneut gegen die Registry zu pruefen.

## Lizenzausschluss (AGPL/GPL)
Weder `pywinauto` 0.6.9 (BSD-3-Clause) noch seine vier geprueften Pakete (`six` MIT, `comtypes` MIT, `pywin32` PSF, `injectlib` nur Beta, BSD-3-Clause) tragen laut PyPI-Metadaten AGPL oder GPL. Die fruehe LGPL-3.0-Lizenz betrifft nur Versionen vor 0.6.0 (Snyk) und wird nicht verwendet. Einschraenkung: Die Feststellung beruht auf den Lizenzfeldern der Metadaten, der Lizenztext jedes Pakets wurde nicht einzeln gelesen. Unbekannte weitere Abhaengigkeiten der zweiten Ebene sind nicht ausgeschlossen (siehe Transitive Abhaengigkeiten, offener Punkt).

## Entscheidung
nehmen

Die Empfehlung gilt nur fuer **pywinauto 0.6.9**, nur als optionales Windows-Extra `uia`, und **unter Bedingungen**. Die Beta 1.0.0b1 wird **nicht** genommen.

Begruendung:
- Permissive Lizenz (BSD-3-Clause) uebereinstimmend in PyPI, Repository und Snyk; keine bekannte Schwachstelle fuer 0.6.9 in der geprueften Datenbank; Projekt wird aktiv gepflegt; reines Python mit wenigen, ueblichen Abhaengigkeiten.
- Die Beta ist erst 16 Tage alt, erweitert den Umfang stark (neue Backends, DLL-Injection im `wpf`-Backend, junge Abhaengigkeit `injectlib` von 2026) und ist von Snyk nicht erfasst. Ihr Vorteil, die Deklaration von Python 3.14, ist eine Projektangabe ohne Testnachweis fuer JARVIS.

Bedingungen und Spannung zum Pruefschema (der Besitzer entscheidet):
1. Das Pruefschema verlangt eine belegte Windows-Kompatibilitaet. Ein Windows-Wheel ist belegt (reines Wheel, `pywin32`-Wheels cp313 und cp314), ein CI-Lauf mit pywinauto 0.6.9 unter Python 3.13 gibt es noch nicht. Diesen Nachweis liefert erst `uia-provider-readonly` (echter Windows-Test an einem echten Fenster; der Schritt darf nicht ueber Skip gruen werden). Faellt er rot aus, wird der Schritt nicht gemergt und die Entscheidung gilt als widerrufen (`nicht nehmen` oder Neubewertung der Beta).
2. Python 3.14: nicht getestet, bleibt offen. Es wird erst nach einem CI-Lauf mit 3.14 als unterstuetzt gefuehrt.
3. Der Besitzer muss, wie in `backlog.json` vorgesehen, selbst eine Freigabezeile in diese Datei eintragen (per PR). Diese Pruefung traegt keine solche Zeile ein und setzt keine Freigabe; ohne sie bleibt `uia-provider-readonly` auf `blocked`.
4. Offene Punkte vor dem Einbau: Lizenz-Wortlaut im sdist gegenpruefen, Abhaengigkeiten aufloesen (`pip install --dry-run`), Hashes aller Ziel-Wheels, Netzwerk- und Importverhalten, Verhalten mit erhoehten Rechten, Windows 11.
5. Nicht Gegenstand dieses Anlaufs: das Paket `uiautomation` und `microsoft/UFO` (nur Architekturvergleich) sind hier nicht neu bewertet; fuer sie gibt es keine Aussage. Falls der Besitzer eine Alternative zu pywinauto will, braucht es einen eigenen Pruefbericht.

## Pruefung (Datum und Quelle)
2026-10-31. Quellen (alle am Pruefdatum abgerufen):
- https://github.com/pywinauto/pywinauto (README, Lizenzaussage, offene Issues und Pull Requests)
- https://github.com/pywinauto/pywinauto/releases (Release-Notizen 0.6.9 und 1.0.0b1)
- https://github.com/pywinauto/pywinauto/commits/master (Aktivitaet bis 2026-10-28)
- https://github.com/pywinauto/pywinauto/security (keine Richtlinie, keine Advisories)
- https://raw.githubusercontent.com/pywinauto/pywinauto/master/LICENSE (zusammengefasst abgerufen; `LICENSE.txt` 404)
- https://pypi.org/project/pywinauto/ (Betreuer, Lizenzfeld, Pre-release-Eintrag)
- https://pypi.org/project/pywinauto/1.0.0b1/ (Seite wurde nicht geladen; stattdessen die PyPI-JSON-Schnittstelle derselben Version, https://pypi.org/pypi/pywinauto/1.0.0b1/json)
- https://pypi.org/pypi/pywinauto/0.6.9/json, https://pypi.org/pypi/comtypes/json, https://pypi.org/pypi/pywin32/json, https://pypi.org/pypi/six/1.17.0/json, https://pypi.org/pypi/injectlib/json (Metadaten, Dateien, SHA-256)
- https://security.snyk.io/package/pip/pywinauto (Seite undatiert)
- https://learn.microsoft.com/en-us/windows/desktop/winauto/entry-uiauto-win32 (kanonisch `.../windows/win32/winauto/entry-uiauto-win32`, Stand 2025-07-14)
- https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-automation-element-propids (Eigenschaften, `IsPassword`)

Hinweis zu den uebernommenen Angaben aus dem Auftrag: BSD-3-Clause ab 0.6.0, Stabil 0.6.9 vom 2025-01-06, Beta 1.0.0b1 vom 2026-10-15 und die Python-3.14-Deklaration der Beta wurden unabhaengig bestaetigt; die Snyk-Aussage ("keine direkten Schwachstellen") bestaetigt sich nur fuer 0.6.9.
