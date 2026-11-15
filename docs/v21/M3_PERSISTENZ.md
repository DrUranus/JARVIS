# M3 – Persistenz des Projektgedächtnisses (Konzept, nicht freigegeben)

Status: **keine produktive Persistenz.** `ProjectMemory` bleibt im Speicher (`to_dict`/`from_dict`). Es existiert nur ein **Testadapter** (`tests/support/project_memory_file_adapter.py`, nirgends verdrahtet, per Test belegt), der dieses Konzept prüfbar macht.

## 1. Speicherformat (Vorschlag)
- Verzeichnis, **eine Datei je Projekt**: `<projekt>.json` (Name nur `[a-z0-9][a-z0-9_-]{0,63}`).
- Inhalt: `{"format": 1, "version": <Snapshot-Version>, "project": "...", "saved_at": "...", "records": [...], "mac": "<HMAC-SHA256>"}`; der MAC läuft über den kanonischen Rest (sortierte Schlüssel). Der Schlüssel liegt **außerhalb** des Verzeichnisses (wie `self_improvement`: Datei mit geprüfter ACL, `winsec`), wird nie gespeichert.
- Schreiben atomar: Temp-Datei im selben Verzeichnis → `fsync` → `os.replace`. Ein Abbruch hinterlässt höchstens eine `.tmp`-Datei, die beim Laden ignoriert wird.
- Alternative SQLite (bestehender Speicher): bessere Abfragen, aber ein gemeinsamer Container erschwert Löschen und Isolation je Projekt. Empfehlung: Dateien je Projekt, bis ein Bedarf nach Abfragen belegt ist.

## 2. Projektisolationsmodell
- Eine Datei = ein Projekt; der Projektname steht im Dateinamen **und** im signierten Inhalt (eine umbenannte Datei wird abgelehnt).
- Eine Satz-ID gilt nur in ihrem Projekt (Kerneigenschaft von `ProjectMemory`); kein Lesen/Schreiben über Projektgrenzen, keine projektübergreifende Suche.
- Fehler in einer Datei (Manipulation, Schemafehler, Geheimnis) setzen **dieses** Projekt in Quarantäne; die übrigen laden weiter.

## 3. Migrationsstrategie
`format` (Dateiaufbau) und `version` (Snapshot-Schema) sind getrennt. Regeln: (1) unbekannte höhere Version → Projekt unlesbar melden, **nie** raten; (2) Migration nur vorwärts, als reine Funktion `n → n+1`, die zuerst eine Kopie der Altdatei als `<projekt>.v<n>.bak` ablegt; (3) nach der Migration erneut vollständig validieren (`from_dict`); (4) kein stilles Verwerfen von Feldern. Bis zur Freigabe existiert nur Version 1.

## 4. Lösch- und Aufbewahrungskonzept
- Alter löscht **nichts**: Datensätze werden `stale` (Kern: `mark_stale`); `working` nach 1 Tag, `knowledge` nach 180 Tagen, `confirmed`/`issue` nach 365 Tagen, `decision` nie.
- Löschen nur auf ausdrücklichen Befehl des Besitzers, je Projekt (`delete_project`); eine Korrektur behält den alten Satz (`superseded`), ein falscher Satz wird `retracted`.
- Endgültiges Entfernen alter/zurückgezogener Sätze: nur durch eine bewusste Aufräumaktion des Besitzers mit Vorschau (nicht Teil des Kerns). Offen: Aufbewahrungsfrist für `.bak`-Dateien (Empfehlung 30 Tage).
- Löschen ist nicht „sicheres Überschreiben“: auf SSD/Journaling-Dateisystemen nicht garantiert; die Zusage lautet „aus JARVIS entfernt“, nicht „forensisch gelöscht“.

## 5. Datenschutz und Geheimnisschutz
- Beim Schreiben und **erneut beim Laden** prüft der Kern über `SecretDetector` (inkl. Bearer) und lehnt Geheimnisse sowie unnötige personenbezogene Daten (E-Mail, Telefon, IBAN) ab – auch in einer gültig signierten Datei.
- Die Datei enthält nur Inhalte, die der Kern schon akzeptiert hat; keine Rohantworten, keine Modelleingaben, keine Pfade des Hosts.
- Verzeichnis außerhalb aller `allowed_roots`/`workspace_roots`, nur für den Besitzer lesbar (wie `self_improvement.data_dir`); Anzeigen (Mission Control) zeigen nur Zähler.
- Kein Netzzugriff, kein Export; ein Export wäre eine eigene, bestätigte Aktion.

## 6. Wiederherstellung nach Prozessabbruch
Abbruch zwischen Schreiben und Austausch → alter Stand bleibt vollständig; Neustart lädt ihn, der Schreibvorgang wird wiederholt (idempotent). Beschädigte Datei → Quarantäne und Meldung, keine automatische Reparatur. Das Journal/die Wiederaufnahme der Zielmotor-Ebene bleibt davon unabhängig.

## 7. Belegt durch Test (`tests/test_v21_project_memory_persistence.py`)
Roundtrip exakt · eine Datei je Projekt ohne Vermischung · Abbruch vor dem Austausch · Manipulation und falscher Schlüssel · umbenannte Datei · Geheimnis in gültig signierter Datei · Löschen genau eines Projekts und Ablehnung von Pfadnamen · Veralten statt Löschen · Adapter nirgends verdrahtet.

## 8. Offene Entscheidungen
P1 Dateien je Projekt vs. SQLite · P2 Speicherort und Rechte (ACL) · P3 Schlüsselverwaltung (derselbe Mechanismus wie `self_improvement`?) · P4 Aufbewahrung der `.bak`-Dateien · P5 wer darf löschen (nur Besitzer, per bestätigter Aktion) · P6 Zeitpunkt der Speicherung (bei Abschluss einer Aufgabe, nie im Hintergrund).
