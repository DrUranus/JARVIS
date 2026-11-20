# JARVIS: verbindliche langfristige Zielsetzung und Abgleich mit dem V2-Backlog

**Status: strategische Anforderung des Besitzers, dokumentiert und gegen den Bestand abgeglichen. Keine Freigabe, keine Implementierung.** Stand 2026-11-11; Grundlage: Besitzernachricht „VERBINDLICHE LANGFRISTIGE ZIELSETZUNG“, `CLAUDE.md`, `README.md` (Phase 10), `docs/PHASE14_AUTONOMY.md`, `config/jarvis.toml`, `docs/V2_BACKLOG.md` (PR #229). V1-Windows-Abnahme #186 hat Vorrang; V2-Merges erfolgen erst nach bestandener Abnahme #186 und gesonderter Freigabe des Besitzers. PermissionEngine, X0, Not-Aus und Audit bleiben unverändert. Die Zielsetzung ist **Richtung, nicht Erlaubnis**: jeder Schritt in Richtung Autonomie oder externe Wirkung braucht weiterhin eine eigene ausdrückliche Freigabe.

**Entscheidungen des Besitzers (2026-11-11, eingearbeitet):**
1. Stufenmodell **S0–S2** im bisherigen Berechtigungsrahmen **bestätigt**.
2. **S3 und S4 bleiben gesperrt.**
3. **S-1, S-5, S-3, S-2** werden in dieser Prioritätsreihenfolge als **zukünftige Entwicklungskandidaten** dokumentiert (keine Freigabe zur Umsetzung).
4. **S-4** bleibt vorerst eine **reine Sicherheitskonzeption**.
5. **Lizenzannahmen müssen mögliche kommerzielle Nutzung berücksichtigen**, da JARVIS künftig zur Erzielung von Einnahmen eingesetzt werden soll.
6. **Rancher Desktop** bleibt bevorzugter Prototyp-Kandidat; **keine** Installations- oder Ausführungsfreigabe.
7. V2-Merges erst nach bestandener Abnahme #186 und gesonderter Owner-Freigabe.

## 1. Die Zielsetzung (inhaltlich unverändert übernommen)
**Klarstellung:** JARVIS wird **nicht verkauft**. Es ist ein **persönlicher, möglichst autonomer KI-Assistent**, mit dem der Besitzer **eigene Einnahmequellen und Unternehmen** aufbaut.

Auf **ausdrücklichen Auftrag** des Besitzers soll JARVIS:
1. neue Geschäftsmöglichkeiten und Geschäftsmodelle recherchieren;
2. Marktnachfrage, Konkurrenz, Startkapital, laufende Kosten und Risiken analysieren;
3. Geschäftsmodelle nach realistischem Ertragspotenzial und Umsetzbarkeit bewerten;
4. Wirtschaftlichkeitsrechnungen und konkrete Umsetzungspläne erstellen;
5. **nach Freigabe** geeignete Modelle möglichst eigenständig technisch umsetzen;
6. Websites, digitale Produkte, Software und Geschäftsautomatisierungen entwickeln;
7. bestehende Projekte organisieren, überwachen und verbessern;
8. Fehler selbstständig erkennen und **innerhalb definierter Berechtigungen** beheben;
9. mehrere langfristige Projekte koordinieren und den Fortschritt dokumentieren;
10. Einnahmen, Ausgaben, Zeitaufwand und tatsächliche Rentabilität nachvollziehbar auswerten.

**Architekturvorgaben:** vorhandene Agenten und Fähigkeiten bevorzugt wiederverwenden · keine unnötigen zusätzlichen Agenten oder parallelen Systeme · Effizienz, niedrige Betriebskosten, zuverlässige Ergebnisse · **wirtschaftliche Annahmen von nachgewiesenen Ergebnissen trennen** · **keine Gewinngarantien, keine erfundenen Marktkennzahlen** · **keine eigenständigen Zahlungen, Verträge, Veröffentlichungen, Kontoeröffnungen oder rechtlich relevanten Handlungen** ohne passende ausdrückliche Freigabe · PermissionEngine, X0, Not-Aus, Audit unverändert.

## 2. Einordnung gegen die verbindlichen Grenzen (belegt)
Das Ziel („möglichst autonom“, „selbstständig beheben“, „Projekte überwachen“) berührt Regeln, die **weiter gelten**:
| Grenze | Quelle | Folge für das Ziel |
|---|---|---|
| Keine neue Autonomie (Selbststart, Hintergrundziele, Selbstmodifikation) ohne ausdrückliche Anweisung | `CLAUDE.md` | Überwachung/Koordination läuft heute nur **auf Aufruf**, nicht im Hintergrund. |
| Jedes Teilziel in `PHASE14_AUTONOMY.md` braucht Freigabe; Hintergrund-/zeitgesteuerte Ziele und Selbststart „nicht ohne neue, ausdrückliche Entscheidung“, Mindestvoraussetzungen: `lockdown` oder `confirmation = "deny"`, Gesamtbudget, gemeinsamer Notaus, Sichtbarkeit | `PHASE14_AUTONOMY.md` Teilziel 5 | Punkt 7/9 („überwachen“, „koordinieren“) im Dauerbetrieb ist **eigene Entscheidung**. |
| Alles standardmäßig aus (`enabled = false`), harte Limits (`max_steps` ≤ 50, `max_attempts_per_step` ≤ 5), Rückfrage-Standard `deny` | `config/jarvis.toml`, `PHASE14_AUTONOMY.md` | „Eigenständig umsetzen“ heißt innerhalb der Limits und mit Rückfrage bei jeder YELLOW-Aktion. |
| Jede Tool-Aktion über `ToolRegistry.execute` → `PermissionEngine`; GREEN automatisch, YELLOW fragt, RED immer abgelehnt | `PHASE14_AUTONOMY.md` | Keine Umgehung; neue Fähigkeiten nur als Tools/Daten darunter. |
| Business Agent: `send_email`, `outreach`, `send_offer`, `contract`, `payment`, `publish` enden `BLOCKED (external_action_not_supported)`; Finance: `paper_trading_only` fest, `place_order`/`transfer`/`withdraw` `BLOCKED (live_trading_not_supported)`, Start mit anderer Konfiguration wird abgelehnt | README Phase 10 | **Zahlungen, Verträge, Veröffentlichungen sind im Code heute unmöglich** – das deckt die Vorgabe „nicht ohne Freigabe“ sogar strenger ab. |
| Selbstmodifikation gesperrt: Phase 15 ist ein deaktivierter Vorschlagsworkflow, `ExecutionGuard` gesperrt | `PHASE14_AUTONOMY.md`, `config/jarvis.toml` | Punkt 8 gilt für **Projekte des Besitzers**, nicht für JARVIS’ eigenen Code. |
| Coding arbeitet in **einem** bestätigten Workspace; jede Schreibaktion wird bestätigt | `config/jarvis.toml` `[coding]` | Punkte 5/6 sind lokal und mit Rückfrage möglich, **Hosting/Veröffentlichung nicht**. |

**Stufenmodell (vom Besitzer für S0–S2 bestätigt; S3 und S4 gesperrt):** 
- **S0 Recherche/Analyse** (lesen, rechnen): im Bestand vorhanden, standardmäßig aus.
- **S1 Entwürfe** (Pläne, Texte, Berechnungen als `DRAFT`): vorhanden.
- **S2 Lokale Umsetzung** (Dateien, Code im bestätigten Workspace, mit Rückfrage): vorhanden (Coding/Files/Office), V2-09 würde sie ausbauen.
- **S3 Externe, rechtlich oder finanziell wirksame Handlung** (veröffentlichen, Konto eröffnen, bezahlen, Vertrag): **nicht vorhanden und nicht Teil der V2-Planung**; jede einzelne Handlungsart bräuchte eine **eigene Freigabe** mit Betrags-/Umfangsgrenze, Bestätigung pro Aktion, Audit und Not-Aus.
- **S4 Hintergrund/Selbststart**: gesperrt bis zur gesonderten Entscheidung (Phase 14, Teilziel 5).

## 3. Abgleich der zehn Ziele mit Bestand und V2-Backlog
„Vorhanden“ nur, was im Code/README belegt ist; Schritte `V2-xx` aus `docs/V2_BACKLOG.md`; **Lücke** = nicht abgedeckt.
| # | Ziel | Vorhanden (belegt) | V2-Schritte | Lücke / Anmerkung |
|---|---|---|---|---|
| 1 | Geschäftsmöglichkeiten recherchieren | Research Agent (Quellen mit URL, Abrufzeit, `FACT/INFERENCE/OPINION/UNCERTAIN`, Widersprüche, URL-Filter; Browser-Tool nur lesend); Business-Vorlage `market_analysis` | V2-01 Quellenbewertung (Plan/PR liegt vor), V2-10 Recherche-Ausbau | Ideenfindung ohne vorgegebene URLs ist begrenzt (Research liest die gegebenen URLs; Suchanbindung nur mit Schlüssel/Freigabe). Ergebnisse sind nur so gut wie die Quellen; Heuristik ist kein Wahrheitsbeweis. |
| 2 | Nachfrage, Konkurrenz, Startkapital, laufende Kosten, Risiken | Business: `market_analysis`, `competitor_analysis`, `business_plan`, `business_analysis`; Ergebnis mit `market_data`, `competitors`, `opportunities`, `risks`, `assumptions`, `sources`, `confidence`; jede Zahl mit Basis `GIVEN/FACT/INFERENCE/ESTIMATE` | V2-10 | **Startkapital- und Kostenmodell** (Anlauf-/Fixkosten, Liquiditätsverlauf) nur über die vorhandenen Rechner (Break-even, Szenarien, Amortisation); kein eigener Kosten-/Liquiditätsplan über Monate. |
| 3 | Bewertung nach Ertragspotenzial und Umsetzbarkeit | Szenario-/Break-even-/Amortisationsrechnung, Konfidenzstufe | – | **Lücke:** einheitliche Bewertungsmatrix zum Vergleich mehrerer Modelle (Kriterien, Gewichtung, Sensitivität). → Kandidat **S-1**. |
| 4 | Wirtschaftlichkeitsrechnung, Umsetzungsplan | `/run business action=break_even …`, `price_stats`, Periodenanalyse; Vorlage `business_plan`; Goal Engine/Planer mit Obergrenzen | V2-02 (Plan-Harness), V2-05 (Kosten-/Risikovorschau je **Plan**, nicht je Geschäftsmodell) | V2-05 betrifft die Plan-Freigabe, nicht die Wirtschaftlichkeit des Modells – nicht verwechseln. |
| 5 | Nach Freigabe technisch umsetzen | Goal Engine + Agenten (Coding im bestätigten Workspace, Files, Office); Replanning begrenzt | V2-09 Coding-Schleife, V2-15 isolierter Worker (OpenHands, vorgemerkt) | Umsetzung heißt **lokal und mit Rückfrage**. Hosting/Domain/Deployment gibt es nicht (S3). |
| 6 | Websites, digitale Produkte, Software, Automatisierungen | Coding-Agent (Dateien/Tests lokal), Office-Dokumente, Files; Entwürfe (Mail, Medien) nur als Dokument (`MAIL_DESIGN.md`, `MEDIA_DESIGN.md`) | V2-09, V2-11 (Office), V2-14 (MCP-Gateway, nur Dokumente), V2-15 | **Veröffentlichung, Versand, Zahlungsabwicklung, Konten sind BLOCKED**; das bleibt so, bis je Handlungsart freigegeben (S3). |
| 7 | Projekte organisieren, überwachen, verbessern | Goal Engine (`max_active_goals = 3`), Journal/`/resume`, Gedächtnis (`PROJECT`, `DECISION`, `RESOURCE`), NEXUS (X0, lesende Sichten) | V2-03 (Projektkontext, PR #235 unangebunden), V2-07 (Projekt-Namensräume), V2-12 (NEXUS-Überwachung) | **Überwachen im Dauerbetrieb** = Hintergrund (S4), gesperrt. Heute: Statusabfrage auf Aufruf. |
| 8 | Fehler erkennen und beheben | Orchestrator-Recovery, Selbstreparatur (`self_repair`, aus, nur benannter Workspace), Replanning (≤ 2) | V2-09, V2-08 (Budgets) | Gilt für **Projektcode des Besitzers** mit Rückfrage, nicht für JARVIS selbst (Phase 15 gesperrt). Selbstständiges Erkennen im Hintergrund = S4. |
| 9 | Mehrere Langzeitprojekte koordinieren, Fortschritt dokumentieren | Journal, Gedächtnis, `max_active_goals`, Replanning | V2-03, V2-06 (Übergabeartefakte), V2-07, V2-08 | **Lücke:** ein **Projektregister** mit Zielen, Meilensteinen, Stand und Fortschrittsbericht. → Kandidat **S-3**. Ohne Hintergrundbetrieb entsteht Fortschritt nur durch Aufträge. |
| 10 | Einnahmen, Ausgaben, Zeitaufwand, Rentabilität | Business `business_analysis` (eigene Zahlen), Finance-Kennzahlen (`COMPUTED`/`UNKNOWN`), Basis-Kennzeichnung je Zahl | – | **Größte Lücke:** kein Ledger (Buchungsdaten), keine Zeiterfassung, keine Ist-gegen-Plan-Auswertung. → Kandidat **S-2**. Kein Bank-/Zahlungszugang (S3). Kein Ersatz für Buchhaltung oder Steuerberatung. |

## 4. Umsetzung der Architekturvorgaben
- **Wiederverwenden, keine neuen Agenten:** Neue Fähigkeiten (S-1 bis S-3) wären **Datenmodelle und Berechnungen in den vorhandenen Modulen** (`business/`, Gedächtnis, Goal-Vorlagen), **keine** neuen Agenten, keine neuen Tools mit Wirkung. Das entspricht dem Muster von V2-01/V2-03: reine Funktionen, unangebunden bis zur Freigabe.
- **Annahmen von Nachweisen trennen:** Das Modell kennt bereits die Basis `GIVEN` (vom Nutzer), `FACT` (Quelle), `INFERENCE` (berechnet), `ESTIMATE` (Annahme) und `UNKNOWN` bei fehlenden Daten. Für Ist-Zahlen (Ledger) kommt eine weitere Trennung hinzu: **Plan/Annahme** gegenüber **Ist/belegt (mit Beleg-Referenz)**. Regel: Annahmen werden nie als Ergebnis ausgegeben.
- **Keine Gewinngarantien, keine erfundenen Kennzahlen:** fehlende Marktdaten bleiben `UNKNOWN` (bestehendes Verhalten); jede Marktzahl braucht eine Quelle; Ausgaben tragen den Hinweis „Annahme/Schätzung, keine Zusage“. Als Abnahmetest vorstellbar: Ausgabe enthält keine Zahl ohne Basis und keine Garantieformulierung.
- **Effizienz, niedrige Betriebskosten:** Das Gesamtbudget pro Sitzung deckt Tool-Aufrufe und Laufzeit, **nicht Kosten/Token** (`PHASE14_AUTONOMY.md`, Lücke). Für dauerhafte Arbeit wäre ein **Kostenbudget** (LLM-Kosten) nötig. → Ergänzung zu V2-08 (Kandidat **S-5**).
- **Externe, rechtlich relevante Handlungen:** bleiben **menschliche Schritte**. JARVIS bereitet Entwürfe und Checklisten (`DRAFT`) vor, der Besitzer führt aus. Eine spätere Automatisierung wäre je Handlungsart eine eigene Freigabe (Kandidat **S-4** beschreibt nur die Einordnung, ohne Code).

## 5. Wichtiger Konflikt mit früheren Entscheidungen: Lizenzannahme „privat, nicht gewerblich“
Die Lizenzprüfung (`docs/V2_LIZENZPRUEFUNG_PRIVAT.md`, PR #238) ging von **ausschließlich privater, nichtkommerzieller Nutzung** aus. Wenn JARVIS und die damit genutzten Werkzeuge künftig **zum Aufbau von Einnahmequellen** dienen, trifft diese Annahme **nicht mehr zu**:
- **Docker Desktop:** „Developer Use“ ist auf eine „personal, non-commercial capacity“ beschränkt und schließt Nutzung im Zusammenhang mit einer Beauftragung durch ein Unternehmen aus. Kostenlos wären nur nichtkommerzielle Open-Source-Projekte oder „commercial undertaking“ unter 250 Beschäftigten **und** unter 10 Mio. US-$ Umsatz (§3.3); „commercial undertaking“ ist nicht definiert. → Docker Desktop bleibt **zurückgestellt**, das stützt die Entscheidung für Rancher Desktop.
- **Rancher Desktop, Podman Desktop, Docker Engine (Apache-2.0), OpenHands (MIT), `pypdf` (BSD), `mcp` (MIT), VirtualBox ohne Extension Pack (GPLv3):** gewerbliche Nutzung ist nach dem Lizenztext unkritisch, soweit Lizenzhinweise beachtet werden.
- **VirtualBox Extension Pack:** kostenlos nur privat/Bildung → ungeeignet bei Einnahmezweck. **VMware Workstation:** laut Ankündigung für alle kostenlos, Lizenztext nicht lesbar, **vor gewerblichem Einsatz prüfen**.
- **Festlegung des Besitzers:** Lizenzprüfungen müssen mögliche kommerzielle Nutzung berücksichtigen. **Folge:** Die Lizenz-Tabelle (`docs/V2_LIZENZPRUEFUNG_PRIVAT.md`) ist für jede künftige Komponente neu zu bewerten, sobald eine Einnahmetätigkeit beginnt. Die 415 OpenHands-Abhängigkeiten sind nicht lizenzgeprüft (zwei Lizenzen ungeklärt, ein LGPL-Paket).

## 6. Bewertung der V2-Schritte für dieses Ziel
| V2 | Beitrag zum Ziel | Hinweis zur Priorität (Empfehlung, Besitzerentscheidung) |
|---|---|---|
| V2-01 Quellenbewertung | hoch (Ziel 1, 3) | PR #229; unverdrahtet |
| V2-02 Plan-Harness | mittel (zuverlässige Pläne) | PR #230 |
| V2-03 Projektkontext | hoch (Ziel 7, 9) | PR #235; unverdrahtet |
| V2-04 CI | gering | – |
| V2-05 Kosten-/Risikovorschau je Plan | mittel (Betriebskosten, Freigabe) | nicht mit Wirtschaftlichkeit verwechseln |
| V2-06 Artefakte | mittel | Voraussetzung für V2-08/10/11 |
| V2-07 Gedächtnis-Namensräume | hoch (Ziel 9, 10) | Datenschutz beachten (Geschäftsdaten) |
| V2-08 Budgets je Agent | hoch (Kosten) | um Kostenbudget (S-5) ergänzbar |
| V2-09 Coding-Schleife | hoch (Ziel 5, 6, 8) | hohes Risiko; erst nach Sandbox-Entscheidung |
| V2-10 Recherche-Ausbau | hoch (Ziel 1, 2) | |
| V2-11 Office-Ausbau | mittel (Berichte, Belege) | |
| V2-12 NEXUS-Überwachung | mittel (Ziel 7) | nur lesend |
| V2-13 GUI-Skills | gering/hoch Risiko | zurückstellen |
| V2-14 MCP-Gateway, V2-15 OpenHands-Worker | mittel (Ziel 6) | nur nach Sandbox-Prototyp |

### Neue Kandidaten (nicht im Backlog, **nicht freigegeben, nicht begonnen**); Prioritätsreihenfolge laut Besitzer: **S-1, S-5, S-3, S-2**; S-4 nur Sicherheitskonzeption
| ID | Inhalt | Art | Risiko |
|---|---|---|---|
| S-1 | **Geschäftsmodell-Bewertungsmatrix**: Kriterien, Gewichtung, Sensitivität, Vergleich mehrerer Modelle, jede Zahl mit Basis | reine Funktion/Daten im Business-Modul, Vorlage; keine Wirkung | niedrig |
| S-2 | **Projekt-Ledger**: vom Besitzer eingegebene Einnahmen/Ausgaben/Zeit mit Beleg-Referenz, Plan-gegen-Ist, Rentabilität; lokal, **ohne Bank-/Zahlungszugang** | Daten + Berechnung; Datenschutz, kein Buchhaltungsersatz | mittel |
| S-3 | **Projektregister und Fortschrittsbericht**: Projekt → Ziele/Meilensteine/Stand, aus Journal und Gedächtnis (lesend), Bericht auf Aufruf | baut auf V2-03/V2-07 | niedrig bis mittel |
| S-4 | **Klassifikation externer, rechtlich relevanter Handlungen**: Dokument + Invarianten-Tests (bleibt BLOCKED/`DRAFT`), Checklisten für menschliche Schritte (Gewerbeanmeldung, Impressum, Steuern …) ohne Rechts-/Steuerberatung | Dokument, Tests | niedrig |
| S-5 | **Kostenbudget** (LLM-Kosten/Token) als Ergänzung zu V2-08 | Budgetprüfung unter dem Orchestrator | mittel |
Alle fünf folgen dem V2-Muster (reine Bausteine, Tests, unverdrahtet) und würden **vor** Umsetzung eine gesonderte Freigabe brauchen.

## 7. Reihenfolge (Besitzer-Prioritäten, nach #186; keine Umsetzungsfreigabe)
1. Vorhandene Entwürfe sichten und erst nach #186 und gesonderter Freigabe mergen (PRs #229–#240, Reihenfolge in `docs/V2_ABSCHLUSS_VORBEREITUNG.md`).
2. Zukünftige Entwicklungskandidaten in Besitzer-Reihenfolge: **S-1** Bewertungsmatrix → **S-5** Kostenbudget → **S-3** Projektregister → **S-2** Projekt-Ledger. Jeder Schritt braucht vor Beginn eine eigene Freigabe.
3. Fundament-Schritte aus dem Backlog (V2-06, V2-07, V2-08) nach Bedarf der Kandidaten; Wirkungsschritte (V2-09, V2-15) erst nach Sandbox-Prototyp und Freigabe.
4. **S-4** bleibt eine reine Sicherheitskonzeption (Einordnung externer Handlungen, Checklisten, Invarianten); **S3/S4 (externe Handlungen, Hintergrundbetrieb) bleiben gesperrt.**

## 8. Abnahmekriterien für die Zielsetzung (vorgeschlagen)
- Jede Zahl in einem Geschäftsergebnis trägt eine Basis; Annahmen sind als `ESTIMATE` erkennbar, Ist-Daten mit Beleg-Referenz.
- Keine Garantie- oder Prognoseformulierung ohne Annahmehinweis; Marktzahlen nur mit Quelle, sonst `UNKNOWN`.
- Zahlungen, Verträge, Veröffentlichungen, Kontoeröffnungen, Versand bleiben `BLOCKED`; Test (Invariante) schlägt an, wenn dies gelockert wird.
- Alle Wirkungen über `ToolRegistry.execute` → `PermissionEngine`; Not-Aus beendet laufende Arbeit; Audit schreibt.
- Betriebskosten (LLM, Laufzeit) pro Auftrag sichtbar und begrenzt.

## 9. Entscheidungen des Besitzers: erledigt und offen
**Erledigt (2026-11-11):** Stufenmodell S0–S2 bestätigt, S3/S4 gesperrt; Prioritätsreihenfolge S-1, S-5, S-3, S-2 als Kandidaten; S-4 nur Sicherheitskonzeption; Lizenzannahmen berücksichtigen kommerzielle Nutzung; Rancher Desktop bevorzugter Prototyp-Kandidat ohne Installationsfreigabe; V2-Merges erst nach #186 und gesonderter Freigabe.
**Weiter offen:**
1. Freigabe je Kandidat vor Beginn (S-1, S-5, S-3, S-2) und je V2-Schritt.
2. Land, Rechtsform und Steuerlage des geplanten Unternehmens (bestimmt Kategorien im Ledger, Pflichten); JARVIS gibt keine Rechts- oder Steuerberatung.
3. Budgetrahmen für Betriebskosten (LLM, Hosting) und Umgang mit Geschäftsdaten (Speicherort, Löschung).
4. Welche Branchen/Projekte zuerst; sie werden bewusst **nicht** einkodiert, sondern als normale Ziele mit eigenen Daten behandelt.
5. Hardware- und BIOS-Angaben (Checkliste) und Prototyp-Freigabe nach #186.

## 10. Was dieses Dokument nicht tut
Es implementiert nichts, ändert keine Konfiguration, installiert nichts, enthält keine Markt-, Ertrags- oder Kostenzahlen und keine Prognosen und erteilt keine Rechts-, Steuer- oder Anlageberatung.
