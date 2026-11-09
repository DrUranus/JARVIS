# JARVIS Windows V1: Abnahme-Plan (Ziel 21.11.2026)

Dieses Dokument ist ein **Plan und eine Vorlage**. Es enthaelt keine Ergebnisse, aendert keine Freigabe und ersetzt nicht die interaktive Abnahme (Issue #186). Ergebnisse werden nur eingetragen, wenn der Befehl/die Pruefung tatsaechlich gelaufen ist und ein Beleg vorliegt.

Nachweisstufen: **CI-Linux** · **CI-Windows** (Runner ohne Mensch am Desktop) · **Mensch** (interaktive Abnahme auf echtem Windows, #186). Eine Stufe ersetzt nie die naechsthoehere.

## 1. Eintrittskriterien (vor der Abnahme)
| # | Kriterium | Wie geprueft | Ergebnis |
|---|---|---|---|
| E-1 | Alle fuer V1 vorgesehenen PRs gemergt (Stand: #216 bis #227, soweit vom Besitzer freigegeben) | GitHub | |
| E-2 | Release-Commit festgelegt (SHA) | `git rev-parse HEAD` auf `main` | |
| E-3 | CI auf dem Release-Commit gruen: `tests-linux`, `tests-windows`, `browser-e2e (windows-latest)`, `native-desktop`, `fresh-install` (Windows/Linux, 3.11/3.13), `real-browser` (Windows/Linux) | GitHub Actions, Skips im JUnit kontrolliert (`-rs`) | |
| E-4 | Keine offenen Sicherheits-/Blocker-Issues | GitHub Issues | |
| E-5 | Workflow-Aenderungen (#219, #223) vom Besitzer geprueft und gemergt | PR-Review | |

## 2. Vorpruefung auf dem Zielrechner (Mensch, ca. 15 Minuten)
Ordner **ausserhalb von OneDrive**, Python 3.13 (python.org, mit tkinter). Schritte nach `docs/WINDOWS_QUICKSTART.md`.

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python ci\fresh-install\smoke.py     # Rauchtest: Import, CLI, doctor, jarvis-cc Start/Stopp
.venv\Scripts\jarvis doctor                         # Exit-Code 0 erwartet
```
Beleg: Ausgabe des Rauchtests und von `jarvis doctor` (Text/Screenshot) ablegen.

## 3. Funktionspruefung (Mensch)
Fuer jede Zeile: bestanden / fehlgeschlagen / nicht geprueft, plus Beleg. Nichts als bestanden eintragen, was nicht geprueft wurde.

| # | Bereich | Pruefung | Erwartung | Maschinell belegt durch | Ergebnis | Beleg |
|---|---|---|---|---|---|---|
| 1 | Start | `jarvis-cc -c config\nexus.example.toml --open` | NEXUS im Browser, "verbunden" | CI-Windows: `fresh-install`, `browser-e2e` | | |
| 2 | Einrichtung | Experten-Modus, "Einrichtung und Diagnose" -> Pruefen | Python, Komponenten, Schluessel nur gesetzt/nicht gesetzt, deutsche Hinweise, nichts wird aktiviert | #217 Tests + Chromium-E2E | | |
| 3 | Datei lesen | Chat: `Lies die Datei notiz.txt` (Testdatei im Arbeitsbereich) | Inhalt als Daten gekennzeichnet; keine Rueckfrage | #216/#220 | | |
| 4 | Datei schreiben | Chat: `Erstelle den Ordner Archiv` | Freigabedialog; Ablehnen (Standard) legt nichts an; Zustimmen legt an | #216/#220 | | |
| 5 | Office | Chat: Tabelle/Dokument erstellen und zuruecklesen | wie 4, nur neue Dateien, keine Makros | #216 | | |
| 6 | Aufgabenansicht | Aufgabe mit Fehler ausloesen (z. B. Datei fehlt) | Status mit Verlauf, Zeile "Fehler", Ergebnis <-> Aufgabe | #221 | | |
| 7 | Not-Aus | NOTAUS im Orb, Dashboard und bei offenem Dialog | wirkt sofort, Eingaben abgelehnt, Aufhebung nur ueber Rueckfrage | Engine- und Browser-E2E | | |
| 8 | Freigabedialog | Dialog offen lassen / Verbindung trennen | gilt als abgelehnt | Browser-E2E | | |
| 9 | Recherche | `Recherchiere ...` ohne Suche eingerichtet | verstaendliche BLOCKED-Meldung; mit Brave-Schluessel (optional): Antwort mit Quellen | #194, #222/#223 (lokale Seite) | | |
| 10 | Sprache | nur wenn Hardware geprueft werden soll, sonst "nicht geprueft" | Start/Ende, erkannter Satz, Antwort, Notaus beendet Sprachmodus | #224 (Fakes) | | |
| 11 | Resume | `jarvis-cc` mitten in einem Ziel hart beenden, neu starten, `/resume` | Auflisten startet nichts; Fortsetzen nur auf Befehl; riskante Schritte fragen neu | #226 | | |
| 12 | Mini-Overlay | `jarvis-cc --overlay --overlay-on-top` (mit `.[ui]`, WebView2) | ca. 140x140, immer im Vordergrund, NOTAUS erreichbar | `native-desktop` (Runner) | | |
| 13 | Beenden | Strg+C | Port geschlossen, keine haengenden Prozesse (Task-Manager) | `fresh-install` | | |

## 4. Entscheidungsregel (Go / No-Go)
- **Go** nur, wenn E-1 bis E-5 erfuellt sind, Zeilen 1 bis 9, 11 und 13 *bestanden* sind und kein Sicherheitsverhalten (4, 7, 8) abweicht.
- **No-Go** bei jedem Fehlschlag in 4, 7 oder 8 oder wenn Belege fehlen.
- Zeilen 10 (Hardware-Sprache), 12 und die Live-Recherche (9, Schluessel) duerfen als "nicht geprueft" in die Release-Notiz, wenn der Besitzer das ausdruecklich entscheidet.

## 5. Bekannte Grenzen (in die Release-Notiz)
Kein 3D-Kern (Canvas-2D), Sprache auf echter Hardware ungetestet, echtes LLM ungetestet (Standard `mock`), Python 3.14 auf Windows nicht in der Voll-CI, Brave-Suche nie live in der CI. Siehe `docs/RELEASE_READINESS_20261108.md` (Abschnitte 2, 3, 8).

## 6. Ablage der Belege
Screenshots und Logs in Issue #186 anhaengen (Dateiname = Zeilennummer, z. B. `abnahme-04-freigabedialog.png`). Datum, Commit-SHA, Windows- und Python-Version oben in #186 eintragen.
