# openpyxl

## Name und Zweck
openpyxl, https://openpyxl.readthedocs.io/ (Quelltext: https://foss.heptapod.net/openpyxl/openpyxl). Liest und schreibt `.xlsx` in reinem Python, ohne installiertes Office. JARVIS braucht es nur fuer das Tool `office` (Schritt `office-docs`, Stufe O1 aus `docs/OFFICE_DESIGN.md`): Tabellen im bestaetigten Workspace lesen und **neue** Dateien erzeugen. Aufnahme nur als optionales Extra `office`, lazy importiert; `dependencies = []` bleibt.

## Lizenz (Wortlaut)
MIT
> This software is under the MIT Licence ... Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction ... (Fundstelle: `openpyxl-3.1.5.dist-info/LICENCE.rst` im Wheel; PyPI-Klassifikator "License :: OSI Approved :: MIT License")

## Version und Datum
3.1.5, veroeffentlicht am 2024-06-28 (PyPI). Festlegung im Extra: `openpyxl>=3.1.5,<3.2`.

## Pflege
Letzte Veroeffentlichung 2024-06-28 (rund 16 Monate vor der Pruefung); stabile Reihe 3.1.x, keine neuere Version auf PyPI. Aktivitaet und Umgang mit Sicherheitsmeldungen der Betreuer: nicht belegt (Projektseite nicht ausgewertet). Wegen der ruhigen Entwicklung wird die Obergrenze `<3.2` gesetzt und die Bibliothek nur fuer das Lesen und Neuanlegen genutzt; JARVIS aendert nie bestehende Dateien (Verlust nicht unterstuetzter Inhalte beim Speichern ist damit ausgeschlossen).

## Python- und Windows-Kompatibilitaet
`Requires-Python >=3.8`, Wheel `py2.py3-none-any` (reines Python): laeuft auf Python >= 3.11 und unter Windows ohne Office. CI-Nachweis fuer Windows: ausstehend bis zum gruenen Lauf `tests-windows` dieses Pull Requests (siehe Pruefstand). Linux: `tests/test_office.py` lief auf Python 3.13.

## Transitive Abhaengigkeiten
| Paket | Version | Lizenz | Quelle |
|---|---|---|---|
| et-xmlfile | 2.0.0 (2024-10-25) | MIT (LICENCE.rst im Wheel; `LICENCE.python` fuer uebernommenen Code) | https://pypi.org/pypi/et-xmlfile/json |


## Sicherheitshinweise
PyPI `vulnerabilities` fuer 3.1.5: leer (2026-11-07). Native Teile: keine. Code beim Installieren/Importieren: nur das Wheel, kein Installationsskript mit Netzzugriff. Die offizielle Dokumentation warnt, dass openpyxl standardmaessig nicht gegen "quadratic blowup" und "billion laughs" schuetzt; Abhilfe: `defusedxml` (siehe `docs/integrations/defusedxml.md`, wird von openpyxl automatisch genutzt, wenn installiert). JARVIS lehnt zusaetzlich jede XML-Datei mit DTD/Entity-Deklaration ab, prueft ZIP-Bombe-Grenzen und lehnt Makro-/Aktivinhalte vor dem Laden ab (`src/jarvis/office/safety.py`); `keep_vba` wird nie gesetzt, `keep_links=False`, Formeln bleiben Text (`data_only=False`, es wird nichts berechnet). Rechte: nur Lesen/Schreiben der vom Tool uebergebenen Datei.

## Datenabfluss
Keine Netzwerkzugriffe und keine Telemetrie (Durchsicht der Importe im Paket: kein `socket`/`urllib`/`requests`/`http` ausser einem Kommentar in `compat/__init__.py`). Speicherorte: nur die vom Tool angegebene Datei im Workspace. Nicht abschaltbare Telemetrie: nicht vorhanden.

## Pinning mit Hash
openpyxl==3.1.5 --hash=sha256:5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2   (Wheel `openpyxl-3.1.5-py2.py3-none-any.whl`, gleiches Artefakt fuer Windows und Linux)
openpyxl==3.1.5 --hash=sha256:cf0e3cf56142039133628b5acffe8ef0c12bc902d2aadd3e0fe5878dc08d1050   (sdist `openpyxl-3.1.5.tar.gz`)
et-xmlfile==2.0.0 --hash=sha256:7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa   (Wheel `et_xmlfile-2.0.0-py3-none-any.whl`)

## Lizenzausschluss (AGPL/GPL)
Weder openpyxl (MIT) noch die transitive Abhaengigkeit et-xmlfile (MIT) ist AGPL oder GPL.

## Entscheidung
nehmen
Nur als optionales Extra `office` (`openpyxl>=3.1.5,<3.2`), lazy importiert, Standard aus (`[office] enabled = false`), fuer Lesen und Neuanlegen im bestaetigten Workspace. Freigabe wirkt erst mit dem Merge dieses Pull Requests durch den Besitzer; der gruene Windows-CI-Lauf ist Voraussetzung dafuer.

## Pruefung (Datum und Quelle)
2026-11-07, https://pypi.org/pypi/openpyxl/json , https://pypi.org/pypi/et-xmlfile/json , Wheel-Inhalt `LICENCE.rst`, `docs/OFFICE_DESIGN.md` (Abschnitt 2.1, Anforderung A7).

Pruefstand und Grenzen: Die Angaben stammen aus den PyPI-JSON-Daten (`https://pypi.org/pypi/<paket>/json`, Feld `vulnerabilities` und Dateihashes), aus den im Wheel mitgelieferten Lizenzdateien und aus einer Durchsicht der Importe im installierten Paket (Linux, Python 3.13, 2026-11-07). Nicht belegt: GitHub-Advisory-Seiten und CVE-Datenbanken wurden nicht durchsucht (keine offizielle Projektquelle abgerufen); das leere PyPI-Feld `vulnerabilities` ist keine Aussage ueber fehlende Schwachstellen. Der Windows-Nachweis steht aus: er entsteht erst durch den gruenen CI-Job `tests-windows` des Pull Requests, der `tests/test_office.py` mit diesen Bibliotheken ausfuehrt (`.[dev]` enthaelt sie); ein Linux-Lauf ist kein Windows-Nachweis.
