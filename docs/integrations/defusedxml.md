# defusedxml

## Name und Zweck
defusedxml, https://github.com/tiran/defusedxml. Schutz vor XML-Angriffen ("billion laughs", "quadratic blowup", externe Entitaeten). openpyxl nutzt es automatisch, wenn installiert; `docs/OFFICE_DESIGN.md` (A7) macht es zur Pflicht-Voraussetzung fuer das Lesen von `.xlsx`. Aufnahme nur als optionales Extra `office`, lazy importiert.

## Lizenz (Wortlaut)
PSF-2.0 (PyPI-Klassifikator "License :: OSI Approved :: Python Software Foundation License", Metadaten `PSFL`)
> PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2 / 1. This LICENSE AGREEMENT is between the Python Software Foundation ("PSF"), and the Individual or Organization ("Licensee") accessing and otherwise using this software ("Python") in source or binary form and its associated documentation. (Fundstelle: `defusedxml-0.7.1.dist-info/LICENSE` im Wheel)

## Version und Datum
0.7.1, veroeffentlicht am 2021-03-08 (PyPI). Festlegung im Extra: `defusedxml>=0.7.1,<0.8`.

## Pflege
Letzte stabile Veroeffentlichung 2021-03-08 (ueber fuenf Jahre vor der Pruefung): **ruhendes Projekt**. Begruendung fuer die Aufnahme trotzdem: sehr kleine, reine Python-Bibliothek ohne Abhaengigkeiten, die nur Parser der Standardbibliothek absichert; das Paket ist die von der openpyxl-Dokumentation genannte Abhilfe. Zusatzschutz in JARVIS unabhaengig davon: DTD/Entity-Deklarationen werden vor dem Laden abgelehnt (`src/jarvis/office/safety.py`). Umgang mit Sicherheitsmeldungen: nicht belegt. Auf PyPI gibt es die Vorabversionen 0.8.0rc1 und 0.8.0rc2, aber keine stabile 0.8; nur 0.7.1 wurde geprueft, die Obergrenze `<0.8` schliesst die Vorabversionen aus.

## Python- und Windows-Kompatibilitaet
`Requires-Python >=2.7, !=3.0.*..!=3.4.*` (schliesst Python >= 3.11 ein), Wheel `py2.py3-none-any` (reines Python): laeuft unter Windows. CI-Nachweis fuer Windows: ausstehend bis zum gruenen Lauf `tests-windows` dieses Pull Requests. Linux: `tests/test_office.py` lief auf Python 3.13 mit defusedxml 0.7.1 ohne Fehler im Importpfad.

## Transitive Abhaengigkeiten
keine (PyPI `requires_dist`: leer)

## Sicherheitshinweise
PyPI `vulnerabilities` fuer 0.7.1: leer (2026-11-07). Native Teile: keine. Code beim Installieren/Importieren: nur das Wheel. Rechte: keine. Ruhendes Projekt: siehe Pflege.

## Datenabfluss
Keine Netzwerkzugriffe und keine Telemetrie (Durchsicht der Importe im Paket: kein `socket`/`urllib`/`requests`/`http`/`subprocess`/`ctypes`). Speicherorte: keine. Nicht abschaltbare Telemetrie: nicht vorhanden.

## Pinning mit Hash
defusedxml==0.7.1 --hash=sha256:a352e7e428770286cc899e2542b6cdaedb2b4953ff269a210103ec58f6198a61   (Wheel `defusedxml-0.7.1-py2.py3-none-any.whl`, Windows und Linux)
defusedxml==0.7.1 --hash=sha256:1bb3032db185915b62d7c6209c5a8792be6a32ab2fedacc84e01b52c51aa3e69   (sdist)

## Lizenzausschluss (AGPL/GPL)
Weder defusedxml (PSF-2.0) noch eine transitive Abhaengigkeit (keine) ist AGPL oder GPL.

## Entscheidung
nehmen
Nur als optionales Extra `office` (`defusedxml>=0.7.1,<0.8`), Standard aus. Freigabe wirkt erst mit dem Merge dieses Pull Requests durch den Besitzer; der gruene Windows-CI-Lauf ist Voraussetzung dafuer.

## Pruefung (Datum und Quelle)
2026-11-07, https://pypi.org/pypi/defusedxml/json , Wheel-Inhalt `LICENSE`, `docs/OFFICE_DESIGN.md` (Abschnitte 2.1, 5 A7).

Pruefstand und Grenzen: Die Angaben stammen aus den PyPI-JSON-Daten (`https://pypi.org/pypi/<paket>/json`, Feld `vulnerabilities` und Dateihashes), aus den im Wheel mitgelieferten Lizenzdateien und aus einer Durchsicht der Importe im installierten Paket (Linux, Python 3.13, 2026-11-07). Nicht belegt: GitHub-Advisory-Seiten und CVE-Datenbanken wurden nicht durchsucht (keine offizielle Projektquelle abgerufen); das leere PyPI-Feld `vulnerabilities` ist keine Aussage ueber fehlende Schwachstellen. Der Windows-Nachweis steht aus: er entsteht erst durch den gruenen CI-Job `tests-windows` des Pull Requests, der `tests/test_office.py` mit diesen Bibliotheken ausfuehrt (`.[dev]` enthaelt sie); ein Linux-Lauf ist kein Windows-Nachweis.
