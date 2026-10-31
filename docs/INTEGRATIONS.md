# Integrationen: Pruefschema fuer externe Bibliotheken und Werkzeuge

Verbindlich fuer jede neue externe Bibliothek, jedes Werkzeug und jeden Dienst, bevor sie in `pyproject.toml`, den Code oder die CI gelangen. Ohne vollstaendige Pruefung und Entscheidung `nehmen` wird nichts uebernommen. Aktuell hat das Projekt keine Laufzeit-Abhaengigkeiten (`dependencies = []`); optionale Extras stehen in `pyproject.toml`.

## Ablauf

1. Pruefung als Datei `docs/integrations/<name>.md` nach der Vorlage unten anlegen (Pull Request, den der Besitzer mergt).
2. Alle Pflichtfelder mit belegten Angaben fuellen. Quelle und Datum jeder Angabe nennen; Unbekanntes als "unbekannt" festhalten, nie raten. Ein unbekanntes Sicherheits- oder Lizenzfeld spricht gegen `nehmen`.
3. Entscheidung eintragen: `nehmen` oder `nicht nehmen`. Erst nach `nehmen` darf ein eigener Schritt die Abhaengigkeit einbauen (mit Hash-Pinning, Verdrahtung nur in `src/jarvis/bootstrap.py`, Tool-Aktionen nur ueber `ToolRegistry.execute` -> `PermissionEngine`).
4. `tests/test_integration_docs.py` prueft jede Datei in `docs/integrations/` automatisch auf Pflichtfelder und Entscheidung. Ohne solche Dateien ist der Test trivial gruen; die Gegenproben im Test belegen, dass ein fehlendes oder leeres Feld rot wird.

## Ausschluss- und Ablehnungsregeln

- **Lizenz:** AGPL und GPL (auch LGPL mit statischer Einbindung) sind ausgeschlossen: Entscheidung `nicht nehmen`. Zulaessig sind nur permissive Lizenzen (MIT, BSD, Apache-2.0, PSF, ISC) oder nach ausdruecklicher Freigabe des Besitzers schwache Copyleft-Lizenzen (MPL-2.0, LGPL bei dynamischer Nutzung). Unklare oder fehlende Lizenz = `nicht nehmen`. Massgeblich ist der Lizenztext im Wortlaut aus der gepruefen Version, nicht ein Schlagwort aus der Paketbeschreibung.
- **Datenabfluss:** Jeder Netzwerkzugriff, jede Telemetrie und jeder Upload muss benannt sein. Standardmaessig gilt: kein Datenabfluss ohne ausdrueckliche, abschaltbare Konfiguration (Standard aus). Nicht abschaltbare Telemetrie = `nicht nehmen`.
- **Sicherheit:** Bekannte, ungepatchte Schwachstellen (Advisories, CVE) in der gepruefen Version, native Binaerteile unbekannter Herkunft, Installationsskripte mit Netzzugriff oder Code-Ausfuehrung beim Import sind Ablehnungsgruende, solange sie nicht begruendet entschaerft sind.
- **Pflege:** Aufgegebene Projekte (keine Veroeffentlichung seit langer Zeit, keine Antworten auf Sicherheitsmeldungen) werden nur mit schriftlicher Begruendung genommen.
- **Plattform:** Zielsystem ist Windows; Linux nur als Zusatzpruefung. Ohne belegte Windows-Kompatibilitaet (Wheel fuer Windows, CI-Lauf) kein `nehmen`. Ein Linux-Lauf ist kein Windows-Nachweis.
- **Pinning:** Genaue Version plus SHA-256-Hash je Artefakt (`pip install --require-hashes`); die Hashes stammen aus der Pruefung, nicht aus einer spaeteren Neuberechnung.

## Pflichtfelder

Jedes Feld ist ein Abschnitt `## <Feld>` mit nicht leerem Inhalt. Die Reihenfolge ist frei, die Ueberschriften muessen woertlich stimmen:

| Feld (Ueberschrift) | Inhalt |
|---|---|
| `## Name und Zweck` | Paketname, Projekt-URL, wofuer JARVIS es braucht |
| `## Lizenz (Wortlaut)` | SPDX-Kennung und der Lizenztext (oder der entscheidende Wortlaut) als Zitat, mit Fundstelle |
| `## Version und Datum` | gepruefte Version und Veroeffentlichungsdatum |
| `## Pflege` | letzte Veroeffentlichung, Aktivitaet der Betreuer, Umgang mit Sicherheitsmeldungen |
| `## Python- und Windows-Kompatibilitaet` | unterstuetzte Python-Versionen (>= 3.11?), Windows-Wheels, Linux-Hinweise |
| `## Transitive Abhaengigkeiten` | vollstaendige Liste samt Lizenz; jede transitive Abhaengigkeit unterliegt denselben Regeln |
| `## Sicherheitshinweise` | Advisories/CVE, native Teile, Code bei Installation/Import, Rechte, die es braucht |
| `## Datenabfluss` | Netzwerkzugriffe, Telemetrie, Speicherorte; was verlaesst den Rechner, wohin, abschaltbar? |
| `## Pinning mit Hash` | genaue Version und SHA-256-Hash(es) der Artefakte (Windows und Linux) |
| `## Lizenzausschluss (AGPL/GPL)` | ausdrueckliche Feststellung, dass weder das Paket noch eine transitive Abhaengigkeit AGPL/GPL ist (oder `nicht nehmen`) |
| `## Entscheidung` | erste Zeile genau `nehmen` oder `nicht nehmen`, danach die Begruendung |
| `## Pruefung (Datum und Quelle)` | Datum der Pruefung (JJJJ-MM-TT) und Quellen (URLs, Registry, Repository, Commit) |

## Vorlage

Kopieren nach `docs/integrations/<name>.md`, alle Platzhalter ersetzen:

```markdown
# <Paketname>

## Name und Zweck
<Name, URL, Zweck>

## Lizenz (Wortlaut)
<SPDX-Kennung>
> <Lizenztext oder entscheidender Wortlaut> (Fundstelle: <URL/Datei, Version>)

## Version und Datum
<Version>, veroeffentlicht am <JJJJ-MM-TT>

## Pflege
<letzte Veroeffentlichung, Aktivitaet, Sicherheitsmeldungen>

## Python- und Windows-Kompatibilitaet
<Python-Versionen, Windows-Wheels, Linux-Hinweise>

## Transitive Abhaengigkeiten
<Paket, Version, Lizenz je Zeile; oder "keine">

## Sicherheitshinweise
<Advisories/CVE, native Teile, Install-/Import-Code, benoetigte Rechte>

## Datenabfluss
<Netzwerk, Telemetrie, Speicherorte, abschaltbar?>

## Pinning mit Hash
<name>==<Version> --hash=sha256:<hash>

## Lizenzausschluss (AGPL/GPL)
<Feststellung fuer Paket und transitive Abhaengigkeiten>

## Entscheidung
nehmen | nicht nehmen   (genau eines davon, dann Begruendung)

## Pruefung (Datum und Quelle)
<JJJJ-MM-TT>, <Quellen>
```

Die Vorlage selbst gilt bewusst als ungueltig, solange `nehmen | nicht nehmen` nicht durch genau eine Entscheidung ersetzt ist.

## Stand

Es liegen noch keine Pruefungen in `docs/integrations/` vor; folgende Schritte der Integrationskette legen sie je Bibliothek an.
