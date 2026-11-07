# python-docx

## Name und Zweck
python-docx, https://python-docx.readthedocs.io/ (Quelltext: https://github.com/python-openxml/python-docx). Liest und erzeugt `.docx` in Python ohne installiertes Office. JARVIS braucht es nur fuer das Tool `office` (Schritt `office-docs`, O1): Texte und Tabellen im bestaetigten Workspace lesen und **neue** Dateien erzeugen. Aufnahme nur als optionales Extra `office`, lazy importiert.

## Lizenz (Wortlaut)
MIT
> The MIT License (MIT) / Copyright (c) 2013 Steve Canny ... Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction ... (Fundstelle: `python_docx-1.2.0.dist-info/licenses/LICENSE` im Wheel; Metadaten `License: MIT`)

## Version und Datum
1.2.0, veroeffentlicht am 2025-06-16 (PyPI). Festlegung im Extra: `python-docx>=1.2.0,<1.3`.

## Pflege
Letzte Veroeffentlichung 2025-06-16 (rund 17 Monate vor der Pruefung). Aktivitaet und Umgang mit Sicherheitsmeldungen der Betreuer: nicht belegt (Projektseite nicht ausgewertet). Obergrenze `<1.3` begrenzt das Risiko unbeabsichtigter Aenderungen.

## Python- und Windows-Kompatibilitaet
`Requires-Python >=3.9`, Wheel `py3-none-any` (reines Python); die Abhaengigkeit lxml bringt fuer Windows fertige Wheels mit (geprueft: `lxml-6.1.3-cp311-cp311-win_amd64.whl` vorhanden). CI-Nachweis fuer Windows: ausstehend bis zum gruenen Lauf `tests-windows` dieses Pull Requests. Linux: `tests/test_office.py` lief auf Python 3.13.

## Transitive Abhaengigkeiten
| Paket | Version | Lizenz | Quelle |
|---|---|---|---|
| lxml | 6.1.3 (2026-09-02) | BSD-3-Clause (`licenses/LICENSE.txt`; die Wheels enthalten zusaetzlich libxml2/libxslt, Lizenztexte in `licenses/LICENSES.txt`) | https://pypi.org/pypi/lxml/json |
| typing_extensions | 4.16.0 (2026-07-02) | PSF-2.0 (`licenses/LICENSE`) | https://pypi.org/pypi/typing-extensions/json |

## Sicherheitshinweise
PyPI `vulnerabilities` fuer python-docx 1.2.0, lxml 6.1.3 und typing_extensions 4.16.0: jeweils leer (2026-11-07). Native Teile: nur lxml (Binaerwheels der lxml-Projekte mit eingebautem libxml2/libxslt; Herkunft PyPI, Hash unten). Code beim Installieren/Importieren: nur Wheels. Dokumente sind unvertrauenswuerdig: JARVIS lehnt vor dem Laden Makro-/Aktivinhalte, ZIP-Bomben und jede XML-Datei mit DTD/Entity-Deklaration ab (`src/jarvis/office/safety.py`); es werden keine Bilder oder Medien extrahiert, kein Programm gestartet. Rechte: nur die vom Tool uebergebene Datei.

## Datenabfluss
Keine Netzwerkzugriffe und keine Telemetrie in python-docx (Durchsicht der Importe im Paket: kein `socket`/`urllib`/`requests`/`http`). Externe Verknuepfungen/Bilder in Dokumenten werden nicht aufgeloest. Speicherorte: nur die vom Tool angegebene Datei im Workspace. Nicht abschaltbare Telemetrie: nicht vorhanden.

## Pinning mit Hash
python-docx==1.2.0 --hash=sha256:3fd478f3250fbbbfd3b94fe1e985955737c145627498896a8a6bf81f4baf66c7   (Wheel `python_docx-1.2.0-py3-none-any.whl`, Windows und Linux)
python-docx==1.2.0 --hash=sha256:7bc9d7b7d8a69c9c02ca09216118c86552704edc23bac179283f2e38f86220ce   (sdist)
lxml==6.1.3 --hash=sha256:7ae4949f212a53b007dbc355884fda122545c5764a54256c9217e419a62a6559   (Windows, `cp311-cp311-win_amd64`)
lxml==6.1.3 --hash=sha256:49fbc2682a9306135b7ec49e93f97f9c26689b9b7f96ed2742d8d6497e994d13   (Linux, `cp311-cp311-manylinux2014_x86_64`)
typing_extensions==4.16.0 --hash=sha256:481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8   (Wheel)
Hinweis: lxml hat je Python-Version und Plattform eigene Wheels; die Hashes weiterer Python-Versionen sind nicht Teil dieser Pruefung und werden bei einem Einbau mit `--require-hashes` neu zu den dann verwendeten Artefakten erhoben.

## Lizenzausschluss (AGPL/GPL)
Weder python-docx (MIT) noch lxml (BSD-3-Clause) noch typing_extensions (PSF-2.0) ist AGPL oder GPL. Nicht gelesen wurden die Lizenztexte der in lxml-Wheels gebuendelten C-Bibliotheken im Wortlaut ausser der Datei `LICENSES.txt` selbst (nur als vorhanden festgestellt): offen, siehe Pruefstand.

## Entscheidung
nehmen
Nur als optionales Extra `office` (`python-docx>=1.2.0,<1.3`), lazy importiert, Standard aus, fuer Lesen und Neuanlegen im bestaetigten Workspace. Freigabe wirkt erst mit dem Merge dieses Pull Requests durch den Besitzer; der gruene Windows-CI-Lauf ist Voraussetzung dafuer.

## Pruefung (Datum und Quelle)
2026-11-07, https://pypi.org/pypi/python-docx/json , https://pypi.org/pypi/lxml/json , https://pypi.org/pypi/typing-extensions/json , Wheel-Inhalte (Lizenzdateien), `docs/OFFICE_DESIGN.md` (Abschnitt 2.2, Anforderung A7).

Pruefstand und Grenzen: Die Angaben stammen aus den PyPI-JSON-Daten (`https://pypi.org/pypi/<paket>/json`, Feld `vulnerabilities` und Dateihashes), aus den im Wheel mitgelieferten Lizenzdateien und aus einer Durchsicht der Importe im installierten Paket (Linux, Python 3.13, 2026-11-07). Nicht belegt: GitHub-Advisory-Seiten und CVE-Datenbanken wurden nicht durchsucht (keine offizielle Projektquelle abgerufen); das leere PyPI-Feld `vulnerabilities` ist keine Aussage ueber fehlende Schwachstellen. Der Windows-Nachweis steht aus: er entsteht erst durch den gruenen CI-Job `tests-windows` des Pull Requests, der `tests/test_office.py` mit diesen Bibliotheken ausfuehrt (`.[dev]` enthaelt sie); ein Linux-Lauf ist kein Windows-Nachweis.
