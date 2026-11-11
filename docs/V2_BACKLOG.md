# JARVIS V2: priorisierter Entwicklungsplan (Entwurf, nichts freigegeben)

Gehört zu `docs/V2_ARCHITEKTUR.md`. **Dieser Plan ist weder Teil von `.github/automation/backlog.json` noch eine Freigabe**: Der Controller-Backlog pflegt nur der Besitzer. Der Release-Freeze für Windows V1 bleibt bestehen; V1-Abnahme (#186) hat Vorrang. Umsetzung beginnt je Schritt erst nach ausdrücklicher Freigabe.

Aufwand = realistische Schätzung in Arbeitstagen (AT) für Entwurf, Umsetzung, Tests und Reparaturzyklen mit KI-Unterstützung **ohne** Wartezeit auf Besitzer-Review; Spanne statt Zusage. Risiko: niedrig (reine Daten/Tests), mittel (neue Verdrahtung), hoch (neue Wirkung oder Sicherheitsnähe).

## Phasen und Reihenfolge
| Phase | Ziel | Schritte | Gesamtaufwand |
|---|---|---|---|
| **A: Fundament** | reine Bausteine, Tests, CI-Hygiene; keine neue Wirkung | V2-01, V2-02, V2-03, V2-04 | 7 bis 11 AT |
| **B: Kontext und Gedächtnis** | Projektkontext wird nutzbar | V2-07, V2-05 | 8 bis 13 AT |
| **C: Multi-Agent** | typisierte Übergaben, Budgets | V2-06, V2-08 | 7 bis 10 AT |
| **D: Fähigkeiten** | Recherche, Office, NEXUS-Sichten | V2-10, V2-11, V2-12 | 14 bis 22 AT |
| **E: Hohe Wirkung (Besitzerentscheidungen)** | Coding-Schleife, GUI-Skills | V2-09, V2-13 | 16 bis 24 AT |

## Schritte
| ID | Titel und Umfang | Abhängigkeiten | Risiko | Abnahmekriterien | Automatisierte Tests / CI | Aufwand |
|---|---|---|---|---|---|---|
| **V2-01** | **Quellenbewertung** (`research/credibility.py`): reine, erklärbare Heuristik (https, Institutionsendung, auffällige Hosts, erkennbares Jahr, Werbesprache, Fremdbestätigung) | keine | niedrig | Score 0..1 mit Gründen je Signal; wirft nie; Heuristik-Hinweis immer dabei; nicht verdrahtet | `tests/test_research_credibility.py` (23 Tests), Analyse-Layering- und Autonomie-Tests; Linux und Windows | **1 AT (Entwurfs-PR erstellt)** |
| V2-02 | **Plan-Evaluationsharness**: feste Aufträge → erwartete Planeigenschaften (Schritte, Fähigkeiten, Obergrenzen, Nebenwirkung markiert) gegen Vorlagen-Planer und Mock-LLM; manueller Lauf gegen echtes Modell | keine | niedrig | Regression bei Planänderung wird sichtbar; keine Netzwerknutzung in CI | reine Tests (`goals_util`-Rig), CI-Linux/Windows | 2 bis 3 AT |
| V2-03 | **Projektkontext-Modell**: unveränderliches Datenobjekt (Projekt, Ziele, Entscheidungen, Ressourcen), baut Kontext nur **lesend** aus `MemoryStore` (Typen `PROJECT`, `DECISION`, `RESOURCE`) mit Zeichenbudget und Schwärzung | V2-07 optional | niedrig | Kontext ist begrenzt, geschwärzt, reproduzierbar; kein Schreibweg | Unit-Tests mit `InMemoryStore`, Layering-Test | 3 bis 4 AT |
| V2-04 | **Nächtliche Voll-CI und Release-Matrix automatisiert**: bestehende Workflows zeitgesteuert, Ergebnisübersicht | keine | niedrig (aber `.github/`: **Besitzer-PR**) | Läufe `tests scope=full`, `fresh-install`, `browser-research`, `control-center-gui-e2e` täglich; Skips sichtbar | Workflow-Selbsttest | 1 bis 2 AT |
| V2-05 | **Kosten-/Risikovorschau je Plan**: aus Schritten (Wirkung, Zeit, Versuche) eine Vorschau für die Freigabe | V2-03 | mittel | Vorschau ändert nie Rechte; stimmt mit tatsächlichen Obergrenzen überein | Property-Tests gegen `validation.py` | 3 bis 5 AT |
| V2-06 | **Typisierte Artefakte und Übergabestandard**: gemeinsames Schema (Art, Quelle, Hash, Länge) für Ergebnisse zwischen Agenten; `research/handoff.py` als Vorbild | keine | mittel | Übergabe nur deklarierter Eingänge; Größenlimits; Redaktion | Orchestrator-Integrationstests, Sicherheitsregression | 4 bis 6 AT |
| V2-07 | **Gedächtnis: Projekt-Namensräume, Verdichtung, Aufbewahrung** (lokal, ohne Netz; optional LLM nur mit eigener Freigabe) | keine | mittel (Daten) | Löschen und Export je Projekt; `SecretGuard` bleibt davor | Store-Tests, Datenschutz-Tests (`test_memory_privacy`-Muster) | 5 bis 8 AT |
| V2-08 | **Budgets je Agent**: Zeit-, Schritt- und Aufrufbudgets zusätzlich zum Sitzungsbudget | V2-06 | mittel | Budget überschritten → Aufgabe BLOCKED mit Grund; Obergrenzen nicht anhebbar | Orchestrator-/Recovery-Tests | 3 bis 4 AT |
| V2-09 | **Coding-Schleife lokal**: Test → Diagnose → begrenzte Reparatur → PR-**Entwurf**; Branch isoliert; Mensch gibt frei; vorher Sandbox-Entscheidung (`SANDBOX_DESIGN.md`) | V2-06, Besitzerentscheidung | **hoch** | nie Änderung an Sicherheitsgrenzen (BLOCKED); kein automatischer Merge | Tests mit Fake-Anbieter, Windows-Prozessbaum-CI | 8 bis 12 AT |
| V2-10 | **Recherche-Ausbau**: Quellenbewertung (V2-01) in die Antwort, Zitatabgleich, Mehrfachanfragen | V2-01, V2-06 | mittel | jede Aussage mit Quelle und Bewertung; Widersprüche sichtbar | Fake-Web-Tests, Echt-Browser-CI (`browser-research`) | 4 bis 6 AT |
| V2-11 | **Office-Ausbau**: bestehende Dateien nur als **Kopie** ändern (Versionsstand), PDF lesen | V2-06 | mittel | Original nie verändert; Rückfrage je Änderung | Office-/Files-Tests, Server-E2E | 6 bis 10 AT |
| V2-12 | **NEXUS-Agentenüberwachung**: lesende Sichten `GET /view/agents` (Zeitleiste) und `GET /view/trace` (Werkzeugaufrufe aus Audit/Verlauf), Budgetanzeige; **kein neues X0-Ereignis** | V2-08 optional | niedrig bis mittel | nur GET mit Token, geschwärzt, begrenzt | Node-DOM- und Chromium-E2E, `tests/test_control_center_*` | 4 bis 6 AT |
| V2-13 | **Skill-Bibliothek für GUI-Abläufe**: verifizierte Abläufe als Daten, App-Profile, Prüfung per Screenshot/UIA-Baum | Besitzerentscheidung | **hoch** | jede Eingabe weiter einzeln freigegeben; Notaus wirkt sofort | Fake-Provider, aufgezeichnete UIA-Bäume, Notepad-E2E auf dem Runner | 8 bis 12 AT |

## Abhängigkeiten (Kurzform)
`V2-07 → V2-03 → V2-05` · `V2-06 → V2-08 → V2-12` · `V2-01 + V2-06 → V2-10` · `V2-06 → V2-11` · `V2-06 + Sandbox-Entscheidung → V2-09` · `V2-13` nach V1-Abnahme und Besitzerentscheidung.

## Technische Risiken
1. **Autonomie-Creep:** V2-05/V2-09/V2-13 nähern sich Wirkung. Gegenmittel: jede Wirkung weiter über `ToolRegistry`/`PermissionEngine`, Obergrenzen als Test.
2. **Datenschutz im Gedächtnis (V2-07):** Verdichtung darf Geheimnisse nicht konservieren. Gegenmittel: `SecretGuard` vor jedem Schreiben, Lösch- und Exporttest.
3. **Modellabhängigkeit:** Planqualität mit echtem LLM ist offen. Gegenmittel: V2-02 mit manuellem Lauf, Vorlagen-Rückfall bleibt.
4. **Windows-Eigenheiten:** Prozessbäume, UIA, OneDrive. Gegenmittel: Runner-Tests, Doctor-Warnungen.
5. **CI-Laufzeit:** Windows-Vollsuite rund 25 Minuten. Gegenmittel: kleine PRs, Branch-Updates gebündelt.
6. **Heuristik als Wahrheit missverstanden (V2-01):** Gegenmittel: Hinweis in jedem Ergebnis, nur Anzeige, nie automatische Ablehnung.

## Was nur manuell am Windows-PC geprüft werden muss
Echte Mikrofon-/Lautsprecher-Ausgabe, Overlay-Fokus und Mehrmonitor, echte Eingaben in Fremdfenstern (V2-13), Live-Brave mit Schlüssel, echtes LLM, OneDrive-Pfade. Alles andere ist über die GitHub-CI (Windows- und Linux-Runner) abdeckbar. Abnahmeplan V1: `docs/WINDOWS_V1_ABNAHME.md`.

## Empfehlung für die nächste Phase
Phase A in dieser Reihenfolge: **V2-01** (Entwurfs-PR liegt vor) → **V2-02** (Testharness, macht jede spätere Planänderung messbar) → **V2-03** (Projektkontext, lesend) → **V2-04** (nächtliche Voll-CI, Besitzer-PR). Erst danach Phase B. Phase E erst nach V1-Abnahme, Sandbox-Entscheidung und ausdrücklicher Freigabe.
