# pypdf

Prüfbericht nach `docs/INTEGRATIONS.md` für V2-11a (PDF lesen im Datei-/Office-Agenten). Geprüft wurden nur öffentliche Quellen (PyPI-Metadaten, LICENSE-Datei, Sicherheitsmeldungen der Registry); **nichts wurde installiert oder heruntergeladen**, kein Quellcode gelesen oder ausgeführt, keine Verdrahtung.

## Name und Zweck
`pypdf`, Projektseite https://github.com/py-pdf/pypdf, Paket https://pypi.org/project/pypdf/, Dokumentation https://pypdf.readthedocs.io/. Reine Python-Bibliothek zum Lesen (und Bearbeiten) von PDF-Dateien. JARVIS braucht davon **nur das Auslesen von Text** aus lokalen, vom Nutzer bestätigten PDF-Dateien (Erweiterung der bestehenden Lesefunktion des Werkzeugs `office`, Fähigkeit `office.read`). Schreiben, Zusammenführen, Verschlüsseln, Bilder, Formulare und Anhänge werden **nicht** benutzt.

## Lizenz (Wortlaut)
BSD-3-Clause
> "Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met: * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer. * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution. * The name of the author may not be used to endorse or promote products derived from this software without specific prior written permission." (Fundstelle: LICENSE im Repository, Zweig `main`, gelesen 2026-11-11, https://github.com/py-pdf/pypdf/blob/main/LICENSE; Urheberzeile „Copyright (c) 2006-2008, Mathieu Fenniak“ u. a.; PyPI-Metadaten: `license_expression` „BSD-3-Clause“).

Ergebnis: permissiv, kommerziell nutzbar.

## Version und Datum
**7.0.1**, PyPI-Upload am 2026-11-10 (Wheel `pypdf-7.0.1-py3-none-any.whl` 11:47 UTC, Quellpaket `pypdf-7.0.1.tar.gz`). Nicht zurückgezogen. Hinweis zur Reife: die Hauptversion 7 ist am Prüftag **vier Tage alt** (7.0.0 am 2026-11-06, 7.0.1 am 2026-11-10); die letzte 6er-Version ist 6.21.4 (2026-10-28). Die Registry führt für 7.0.1 **0** gemeldete Schwachstellen. Vor einem Einbau ist die dann aktuelle Version erneut zu prüfen (Abschnitt „Entscheidung“).

## Pflege
Sehr aktiv: 129 Veröffentlichungen, zuletzt 6.21.4 (2026-10-28), 7.0.0 (2026-11-06) und 7.0.1 (2026-11-10). Sicherheitsmeldungen werden als GitHub-Advisories (GHSA) veröffentlicht, in der Registry als PYSEC geführt und in der Regel binnen weniger Versionen behoben. Quelle der Zahlen: PyPI-Feld `vulnerabilities` je Version, Stichprobe über acht Versionen (5.0.0, 6.0.0, 6.5.0, 6.10.0, 6.14.0, 6.19.0, 6.20.0, 6.21.0).

## Python- und Windows-Kompatibilitaet
- `requires_python`: **>=3.10** (JARVIS verlangt >= 3.11, also kompatibel); Wheel `py3-none-any` (reines Python, keine plattformabhängigen Bauteile), also auf Windows und Linux dasselbe Artefakt.
- Unter Python >= 3.11 hat pypdf **keine** harte Abhängigkeit (`typing_extensions>=4.0` nur für Python < 3.11).
- **Windows-Nachweis fehlt:** Es gibt keinen CI-Lauf von uns, der pypdf unter Windows installiert und eine Beispiel-PDF liest. Nach `docs/INTEGRATIONS.md` („Ohne belegte Windows-Kompatibilitaet … kein `nehmen`“) ist das der **einzige** formale Hinderungsgrund. Ein Linux-Lauf wäre kein Windows-Nachweis.

## Transitive Abhaengigkeiten
Unter Python >= 3.11 (Zielsystem): **keine**.
Unter Python 3.10 (außerhalb unseres Minimums): `typing_extensions` (PSF-2.0).
Optionale Extras (`crypto` zieht `cryptography` mit nativen Teilen, `image`/`full` ziehen `pillow`, `fonts`, `brotli` u. a.) werden **nicht** aktiviert. Verschlüsselte PDFs werden deshalb nicht entschlüsselt, sondern abgelehnt.

## Sicherheitshinweise
**Bekannte Schwachstellen (Registry, OSV/PYSEC/GHSA):** Es wurden **mindestens 67 verschiedene CVE-Nummern** für 2025 und 2026 gefunden (Untergrenze, weil nur acht Versionen abgefragt wurden). Alle sind in den genannten Fixversionen behoben; die höchste Fixversion in der Stichprobe ist **6.21.4**; für 7.0.1 führt die Registry keine Meldung.

| Klasse | Anzahl (Stichprobe) | Wirkung |
|---|---|---|
| Endlosschleife oder sehr lange Laufzeit durch präparierte PDF | 39 | Denial of Service (CPU) |
| hoher Speicher-/RAM-Verbrauch durch präparierte PDF | 26 | Denial of Service (Speicher) |
| Sonstiges | 2 | z. B. „arbitrary image parsers being called“ (CVE-2026-113786, behoben 6.21.1, erfordert das **Laden von Bildern**); lange Laufzeit beim Lesen von Seitenbezeichnungen (CVE-2026-119206, behoben 6.21.3) |

Beispiele: CVE-2026-27628 (Endlosschleife, behoben 6.7.2), CVE-2026-31826 (Speicher, behoben 6.8.0), CVE-2025-55197 (RAM, behoben 6.0.0), CVE-2026-59935 und -59936 (Endlosschleifen bei Inline-Bildern, behoben 6.14.2 bzw. 6.14.1; die Angaben der Fremdseiten weichen hier ab, die Registry nennt 6.14.1/6.14.2). Einzelne Nummern in den Quellen sind ungewöhnlich (sechsstellige Suffixe); sie stammen aus dem PyPI-Feld und sind vor einem Einbau gegen NVD/GitHub-Advisories zu prüfen.

**Einordnung:** keine gemeldete Code-Ausführung; das Risiko ist **Denial of Service** durch bösartige PDFs (Downloads, Mailanhänge), und es kommen laufend neue Meldungen (rund 67 in etwa 14 Monaten). Die Bibliothek ist ein aktives Ziel von Fuzzing; das ist ein Qualitätszeichen (schnelle Behebung) und zugleich ein Dauerbetriebsrisiko.

**Folgerungen für die Integration (verbindlich für einen Einbau-Schritt):**
1. Das Parsen läuft **in einem eigenen Prozess** (Job Object, Zeit- und Speicherlimit, Beenden bei Notaus/Abbruch), nie im JARVIS-Hauptprozess.
2. Harte Grenzen: Dateigröße, Seitenzahl, Zeichenzahl der Ausgabe, Wanduhrzeit; Überschreitung ergibt einen klaren Fehler, keine Teilausgabe als vollständig.
3. **Nur Textauszug.** Keine Bilder laden/extrahieren, keine Seitenbezeichnungen, Gliederung, Formulare, Anhänge, JavaScript, keine Entschlüsselung (verschlüsselt = abgelehnt), kein Passwort.
4. Ergebnisse sind **nicht vertrauenswürdige Daten** (eingeschleuste Anweisungen im PDF-Text), gekennzeichnet und mit dem vorhandenen `SecretDetector` geschwärzt.
5. Bei jedem Release-Check wird die gepinnte Version gegen die Registry-Meldungen geprüft; eine neue ungepatchte Meldung sperrt die Funktion, bis eine Fixversion geprüft und gepinnt ist.

Native Teile: keine im Paket; Importcode nicht gelesen. Benötigte Rechte: Lesezugriff auf die bestätigte Datei.

## Datenabfluss
Keine Netzwerkzugriffe bekannt oder nötig; Telemetrie ist in der Registry-Beschreibung nicht erwähnt (**Quellcode nicht geprüft**). Speicherorte: keine eigenen. Der Textauszug verbleibt lokal. Ein späterer Test sperrt Sockets im Parser-Prozess (z. B. durch Blockade im Test), um „kein Netz“ zu belegen.

## Integrationsschnittstelle
Entwurf, nichts umgesetzt. Ziel: **keine neue Fähigkeit, kein neues Werkzeug**, sondern Erweiterung der vorhandenen Lesefunktion:
- Werkzeug `office`, Aktion `read`, zusätzlich für `.pdf` (Fähigkeit `office.read` bleibt; `KNOWN_CAPABILITIES` unverändert). Parameter: `path` (bestätigte Wurzel, vorhandene Pfadregeln), `max_pages` (Standard 50, Obergrenze 200), `max_chars` (Standard 100 000).
- Ausführung über einen Hilfsprozess `python -I -m jarvis.office.pdf_worker <Pfad>` unter Job Object (Verdrahtung nur in `bootstrap.py`, wie beim Coding-Anbieter), Wanduhr 20 s, Speicher 512 MB, Datei höchstens 20 MB, Ausgabe als begrenztes JSON auf stdout.
- Rückgabe: `{pages, text_by_page, truncated, warnings}`; Fehlercodes `encrypted`, `too_large`, `too_many_pages`, `parse_error`, `timeout`, `memory`.
- Berechtigung wie jede andere Office-Lesung (vorhandene Regeln, Bestätigung nach Konfiguration); Audit mit Pfad-Hash, Seitenzahl, Ergebnisgröße.
- Abnahmetests (CI-fähig, ohne Netz): präparierte Test-PDFs (eingebaute Endlosschleife/Speicherbombe aus eigenen, harmlosen Fixtures, kein Fremdcode), Timeout- und Speichertest unter dem Job Object auf dem Windows-Runner, verschlüsselte PDF abgelehnt, Bilder werden nie geladen, Ausgabe gekennzeichnet und geschwärzt, Notaus beendet den Worker, Standardzustand aus, kein anderer Importeur von `pypdf`.
Alternativen (nicht geprüft/bewusst zurückgestellt): MarkItDown (MIT; URI- und `file://`-Risiko, mehr Abhängigkeiten, siehe `docs/V2_OPEN_SOURCE_BEWERTUNG.md`), pdfminer.six/pdfplumber (nicht bewertet).

## Pinning mit Hash
Nur zur Dokumentation, **kein Einbau**. Hashes aus den PyPI-Metadaten (nicht heruntergeladen, vor einem Einbau erneut gegen die dann aktuelle Version zu prüfen):
```
pypdf==7.0.1 \
    --hash=sha256:6131b764b046282357037309e7ef2a1b7679d4a5c53eed3db2bfbf7c673ddc2b \
    --hash=sha256:0a78bb99efb41e9088260e9a8e5da134a5cbb9a322014744177bf29b5267ea6d
```
(Wheel `py3-none-any` für Windows und Linux; Quellpaket.) Als Extra im Muster der bestehenden Extras vorgesehen (z. B. `pdf = ["pypdf==7.0.1"]`), nicht im Kern.

## Lizenzausschluss (AGPL/GPL)
`pypdf` ist BSD-3-Clause; unter Python >= 3.11 gibt es keine transitive Abhängigkeit. Weder das Paket noch eine Abhängigkeit ist AGPL oder GPL. (PyMuPDF, eine verbreitete Alternative, ist AGPL/kommerziell und damit ausgeschlossen.)

## Entscheidung
nicht nehmen

Begründung (Stand 2026-11-11; **Wiedervorlage vorgesehen**):
- Technisch und lizenzrechtlich ist pypdf geeignet: BSD-3, reines Python, keine Abhängigkeit unter 3.11+, sehr aktiv gepflegt, 0 gemeldete Schwachstellen in 7.0.1.
- Der **einzige formale Hinderungsgrund** ist der fehlende Windows-CI-Nachweis (Regel in `docs/INTEGRATIONS.md`). Ohne Einbau lässt er sich nicht erbringen.
- **Bedingungen für den Wechsel auf `nehmen`:** (1) ein isolierter Windows-Kompatibilitätslauf nach dem Muster `ci/uia-compat` (Installation nur im Prüflauf aus der gehashten Anforderungsdatei, Lesen einer harmlosen Beispiel-PDF, Ergebnis dokumentiert); falls dafür ein Workflow nötig ist, ist das ein Besitzer-PR für `.github/`; (2) erneute Prüfung der dann aktuellen Version (7.x ist sehr neu) und ihrer Registry-Meldungen; (3) ausdrückliche Besitzerfreigabe des Einbau-Schritts V2-11a mit den Auflagen aus „Sicherheitshinweise“ (eigener Prozess mit Limits, nur Text, nichts anderes).
- Empfehlung: nach Erfüllung von (1) und (2) `nehmen` für den beschriebenen Zweck. Keine Installation, keine Produktivverdrahtung in diesem Schritt.

## Pruefung (Datum und Quelle)
2026-11-11. Quellen: PyPI-JSON `https://pypi.org/pypi/pypdf/json` und `…/pypdf/<Version>/json` (Version, Datum, `requires_python`, `requires_dist`, Wheels, Hashes, `vulnerabilities` je Version); LICENSE im Repository (https://github.com/py-pdf/pypdf/blob/main/LICENSE); Einzelmeldungen: https://advisories.gitlab.com/pypi/pypdf/CVE-2026-27628/ , https://osv.dev/vulnerability/PYSEC-2026-1827 , https://devhub.checkmarx.com/cve-details/cve-2026-41313/ (Sekundärquellen). Nicht geprüft: Quellcode, GitHub-Aktivität, Installation, CI-Lauf, vollständige Liste aller Meldungen vor 5.0.0.
